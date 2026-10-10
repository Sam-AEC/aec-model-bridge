"""Human-run command-line approval: ``aec-model-bridge-approve list|show|approve|reject``.

A model can draft a plan but must not approve it. The Revit panel is one place a
person does that; this is the other. It reads and writes the same plan store as the
server (``<workspace>/plans``), prints the plan in plain language first, and only
approves after the person types the plan id. Without a terminal it refuses unless
``--yes`` is given.

Honest limit: an agent that can run shell commands as the same user can also run this
tool with ``--yes``. Keep agents' shell access off, or require a terminal, if that
matters to you.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import config
from .security.approval import ApprovalGate

ELEMENT_ID_KEYS = ("element_id", "element_ids", "id", "ids", "elementIds")


def _gate(workspace: Optional[str]) -> ApprovalGate:
    base = Path(workspace) if workspace else (
        config.allowed_directories[0] if config.allowed_directories else config.workspace_dir
    )
    return ApprovalGate(base, config.approval_mode)


def _element_ids(arguments: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    for key in ELEMENT_ID_KEYS:
        value = arguments.get(key)
        if value is None:
            continue
        found.extend(str(v) for v in (value if isinstance(value, (list, tuple)) else [value]))
    return found


def describe_plan(plan: Dict[str, Any]) -> str:
    actions = plan.get("actions", [])
    lines = [
        f"Plan {plan.get('plan_id')}  [{plan.get('state')}]",
        f"Created: {plan.get('created_at', 'unknown')}",
        f"Actions: {len(actions)}",
    ]
    tools: Dict[str, int] = {}
    for a in actions:
        tools[str(a.get('tool'))] = tools.get(str(a.get('tool')), 0) + 1
    if tools:
        lines.append("Tools:   " + ", ".join(f"{t} x{n}" for t, n in sorted(tools.items())))
    all_ids = sorted({i for a in actions for i in _element_ids(a.get("arguments", {}) or {})})
    if all_ids:
        shown = ", ".join(all_ids[:20]) + (f" ... (+{len(all_ids) - 20} more)" if len(all_ids) > 20 else "")
        lines.append(f"Elements touched: {len(all_ids)} ({shown})")
    lines.append("")
    for i, a in enumerate(actions, 1):
        args = a.get("arguments", {}) or {}
        detail = ", ".join(f"{k}={v!r}" for k, v in args.items() if k != "plan_id")
        lines.append(f"  {i}. {a.get('tool')}  {detail}")
        before = (a.get("diff") or {}).get("before")
        if before:
            lines.append(f"     current value: {before}")
    if plan.get("skipped"):
        lines.append(f"\nSkipped when drafting: {len(plan['skipped'])}")
    if plan.get("approved_by") or plan.get("approved_via"):
        lines.append(f"\nApproved by: {plan.get('approved_by', '-')} via {plan.get('approved_via', '-')} at {plan.get('approved_at', '-')}")
    return "\n".join(lines)


def _confirm(plan_id: str, verb: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            f"Refusing to {verb} without a terminal. Run this command yourself in a terminal, "
            "or pass --yes if you are a person scripting your own approvals.",
            file=sys.stderr,
        )
        return False
    typed = input(f"Type the plan id ({plan_id}) to {verb} it, or anything else to cancel: ").strip()
    return typed == plan_id


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aec-model-bridge-approve",
        description="Review and approve or reject plans drafted by an AI assistant. Humans only.",
    )
    parser.add_argument("--workspace", help="workspace folder holding plans/ (default: the configured workspace)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list pending plans")
    for name in ("show", "approve", "reject"):
        p = sub.add_parser(name, help=f"{name} a plan")
        p.add_argument("plan_id")
        if name != "show":
            p.add_argument("--yes", action="store_true", help=f"{name} without the typed confirmation")
    args = parser.parse_args(argv)

    gate = _gate(args.workspace)

    if args.command == "list":
        plans = gate.list_pending_plans()
        if not plans:
            print("No pending plans.")
        for plan in sorted(plans, key=lambda p: p.get("created_at", "")):
            tools = sorted({str(a.get("tool")) for a in plan.get("actions", [])})
            print(f"{plan['plan_id']}  {plan.get('created_at', '')}  {len(plan.get('actions', []))} action(s)  {', '.join(tools)}")
        return 0

    plan = gate.load_plan(args.plan_id)
    if not plan:
        print(f"Plan '{args.plan_id}' not found in {gate.plans_dir}.", file=sys.stderr)
        return 1
    print(describe_plan(plan))

    if args.command == "show":
        return 0

    if plan.get("state") != "pending":
        print(f"\nPlan is '{plan.get('state')}', not pending; nothing to {args.command}.", file=sys.stderr)
        return 1

    verb = args.command
    print()
    if not _confirm(args.plan_id, verb, args.yes):
        print("Cancelled; plan unchanged.", file=sys.stderr)
        return 2

    try:
        if verb == "approve":
            gate.update_plan_state(args.plan_id, "approved", approver="cli", via="cli")
        else:
            gate.update_plan_state(args.plan_id, "rejected", via="cli")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Plan {args.plan_id} {verb}d.")
    return 0


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
