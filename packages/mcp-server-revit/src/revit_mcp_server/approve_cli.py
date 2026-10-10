"""Human-run command-line approval: ``aec-model-bridge-approve list|show|approve|reject``.

A model can draft a plan but must not approve it. The Revit panel is one place a
person does that; this is the other. It reads and writes the same plan store as the
server (``<workspace>/plans``), prints the plan in plain language and its content
hash first, and only approves after the person types the plan id. The approval is
bound to that hash: it is refused if the plan changed after it was printed. Without
a terminal it refuses unless ``--yes`` is given. Model-written text is printed with
control characters escaped.

Honest limit: an agent that can run shell commands as the same user can also run this
tool with ``--yes``. Keep agents' shell access off, or require a terminal, if that
matters to you.
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import config
from .errors import BridgeError
from .security import proof as proof_mod
from .security.approval import ApprovalGate, local_user, plan_hash
from .security.proof import normalize_review

ELEMENT_ID_KEYS = ("element_id", "element_ids", "id", "ids", "elementIds")


def _gate(workspace: Optional[str]) -> ApprovalGate:
    base = Path(workspace) if workspace else (
        config.allowed_directories[0] if config.allowed_directories else config.workspace_dir
    )
    return ApprovalGate(base, config.approval_mode)


def safe_text(value: Any) -> str:
    """Make model-controlled text safe to print: control and format characters
    (ESC/ANSI/OSC sequences, carriage returns, bidi overrides, zero-width marks)
    are shown as visible escapes instead of being sent to the terminal."""
    out = []
    for ch in str(value):
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"):
            code = ord(ch)
            out.append(f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}")
        else:
            out.append(ch)
    return "".join(out)


def _actions(plan: Dict[str, Any]) -> List[Any]:
    actions = plan.get("actions", [])
    return actions if isinstance(actions, list) else []


def malformed_reasons(plan: Dict[str, Any]) -> List[str]:
    """Reasons a plan cannot be shown faithfully (and so must not be approved)."""
    reasons = []
    if not isinstance(plan.get("actions", []), list):
        reasons.append("'actions' is not a list")
    for i, a in enumerate(_actions(plan), 1):
        if not isinstance(a, dict):
            reasons.append(f"action {i} is not an object")
        elif not isinstance(a.get("arguments", {}), dict):
            reasons.append(f"action {i} has arguments that are not an object")
    if "review" in plan or "hash_version" in plan:
        try:
            proof_mod.plan_hash_version(plan)
            normalize_review(plan.get("review"))
        except ValueError as e:
            reasons.append(f"review block is invalid ({e})")
    return reasons


def _describe_review(plan: Dict[str, Any]) -> List[str]:
    """Lines for the plan's hashed review block; every string goes through safe_text."""
    review = plan.get("review")
    if review is None:
        return []
    try:
        review = normalize_review(review)
    except ValueError as e:
        return ["", f"Review: MALFORMED, not shown ({safe_text(e)})"]
    lines = ["", "Review (covered by the plan hash):"]
    if review["summary"]:
        lines.append(f"  Summary: {safe_text(review['summary'])}")
    if review["reasoning"]:
        lines.append("  Reasoning:")
        lines.extend(f"    {safe_text(part)}" for part in review["reasoning"].split("\n"))
    if review["citations"]:
        lines.append("  Citations (stated by the drafter, not checked by this tool):")
        for c in review["citations"]:
            lines.append(f"    - {safe_text(c['rule_id'])}  clause: {safe_text(c['clause'] or '-')}  "
                         f"source: {safe_text(c['source'] or '-')}")
    if review["assumptions"]:
        lines.append("  Assumptions:")
        lines.extend(f"    - {safe_text(a)}" for a in review["assumptions"])
    if review["excluded"]:
        lines.append("  Left out:")
        lines.extend(f"    - element {safe_text(x['element_id'])}: {safe_text(x['reason'] or '-')}"
                     for x in review["excluded"])
    if review["warnings"]:
        lines.append("  Warnings:")
        lines.extend(f"    ! {safe_text(w)}" for w in review["warnings"])
    return lines


def _element_ids(arguments: Any) -> List[str]:
    found: List[str] = []
    if not isinstance(arguments, dict):
        return found
    for key in ELEMENT_ID_KEYS:
        value = arguments.get(key)
        if value is None:
            continue
        found.extend(str(v) for v in (value if isinstance(value, (list, tuple)) else [value]))
    return found


def describe_plan(plan: Dict[str, Any]) -> str:
    actions = _actions(plan)
    lines = [
        f"Plan {safe_text(plan.get('plan_id'))}  [{safe_text(plan.get('state'))}]",
        f"Created: {safe_text(plan.get('created_at', 'unknown'))}",
        f"Actions: {len(actions)}",
    ]
    tools: Dict[str, int] = {}
    for a in actions:
        t = safe_text(a.get("tool") if isinstance(a, dict) else "<malformed action>")
        tools[t] = tools.get(t, 0) + 1
    if tools:
        lines.append("Tools:   " + ", ".join(f"{t} x{n}" for t, n in sorted(tools.items())))
    all_ids = sorted({safe_text(i) for a in actions if isinstance(a, dict) for i in _element_ids(a.get("arguments"))})
    if all_ids:
        shown = ", ".join(all_ids[:20]) + (f" ... (+{len(all_ids) - 20} more)" if len(all_ids) > 20 else "")
        lines.append(f"Elements touched: {len(all_ids)} ({shown})")
    lines.append("")
    for i, a in enumerate(actions, 1):
        if not isinstance(a, dict):
            lines.append(f"  {i}. MALFORMED ACTION: {safe_text(repr(a))}")
            continue
        args = a.get("arguments", {})
        if isinstance(args, dict):
            detail = ", ".join(f"{safe_text(k)}={safe_text(repr(v))}" for k, v in args.items() if k != "plan_id")
        else:
            detail = f"MALFORMED ARGUMENTS (not an object): {safe_text(repr(args))}"
        lines.append(f"  {i}. {safe_text(a.get('tool'))}  {detail}")
        before = (a.get("diff") or {}).get("before") if isinstance(a.get("diff"), dict) else None
        if before:
            lines.append(f"     current value: {safe_text(before)}")
    lines.extend(_describe_review(plan))
    if plan.get("skipped"):
        skipped = plan["skipped"]
        lines.append(f"\nSkipped when drafting: {len(skipped) if isinstance(skipped, list) else safe_text(skipped)}")
    try:
        metadata = proof_mod.unhashed_metadata_keys(plan)
    except Exception:
        metadata = []
    if metadata:
        lines.append("\nNot part of the approval (metadata, not shown as approved content): "
                     + ", ".join(safe_text(k) for k in metadata))
    if plan.get("approved_by") or plan.get("approved_via"):
        lines.append(
            f"\nApproved by: {safe_text(plan.get('approved_by', '-'))} via {safe_text(plan.get('approved_via', '-'))} "
            f"at {safe_text(plan.get('approved_at', '-'))}"
        )
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
        for plan in sorted(plans, key=lambda p: str(p.get("created_at", ""))):
            acts = _actions(plan)
            tools = sorted({safe_text(a.get("tool") if isinstance(a, dict) else "<malformed>") for a in acts})
            print(f"{safe_text(plan['plan_id'])}  {safe_text(plan.get('created_at', ''))}  {len(acts)} action(s)  "
                  f"{', '.join(tools)}")
        return 0

    try:
        plan = gate.load_plan(args.plan_id)
    except BridgeError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not plan:
        print(f"Plan '{safe_text(args.plan_id)}' not found in {gate.plans_dir}.", file=sys.stderr)
        return 1
    # The hash of exactly what is printed below; the approval is refused if the plan
    # on disk differs from it when the person confirms.
    try:
        shown_hash = plan_hash(plan)
    except ValueError as e:
        print(f"Plan cannot be verified: {safe_text(e)}", file=sys.stderr)
        return 1
    print(describe_plan(plan))
    print(f"\nPlan hash: {shown_hash}")

    if args.command == "show":
        return 0

    allowed = ("pending",) if args.command == "approve" else ("pending", "approved")
    if plan.get("state") not in allowed:
        print(f"\nPlan is '{safe_text(plan.get('state'))}'; it cannot be {args.command}ed.", file=sys.stderr)
        return 1
    problems = malformed_reasons(plan)
    if problems and args.command == "approve":
        print("\nThis plan is malformed (" + "; ".join(problems) + ") and cannot be approved. "
              "Reject it and ask for a new plan.", file=sys.stderr)
        return 1

    verb = args.command
    print()
    if not _confirm(args.plan_id, verb, args.yes):
        print("Cancelled; plan unchanged.", file=sys.stderr)
        return 2

    try:
        if verb == "approve":
            gate.update_plan_state(args.plan_id, "approved", approver=local_user(), via="cli",
                                   expected_hash=shown_hash)
        else:
            gate.update_plan_state(args.plan_id, "rejected", via="cli")
    except (ValueError, BridgeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Plan {args.plan_id} {verb}{'d' if verb.endswith('e') else 'ed'}.")
    return 0


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
