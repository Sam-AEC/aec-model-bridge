"""Human-run command-line approval: ``aec-model-bridge-approve list|show|approve|reject|recover``.

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
import math
import re
import sys
import textwrap
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import config
from .errors import BridgeError
from .security import proof as proof_mod
from .security.approval import STALE_RUNNING_SECONDS, ApprovalGate, local_user, plan_hash, running_actions
from .security.plan_review import review_aids
from .security.proof import normalize_review
from .security.recipe_store import RecipeError, RecipeStore, validate_recipe_id

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
            reasons.append(f"review block is invalid ({safe_text(e)})")
    return reasons


_SPACE_RUN = re.compile(r"[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]{2,}")


def _field(prefix: str, text: Any, indent: str = "  ") -> List[str]:
    """One review field as indented, wrapped lines: runs of spaces are collapsed and every
    continuation line is indented, so field text cannot pose as a separate line."""
    cleaned = safe_text(_SPACE_RUN.sub(" ", str(text)))
    return textwrap.wrap(cleaned, width=78, initial_indent=indent + prefix,
                         subsequent_indent=indent + " " * len(prefix), break_long_words=True) or [indent + prefix]


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
        lines.extend(_field("Summary: ", review["summary"]))
    if review["reasoning"]:
        lines.append("  Reasoning:")
        for part in review["reasoning"].split("\n"):
            lines.extend(_field("", part, "    "))
    if review["citations"]:
        lines.append("  Citations (stated by the drafter, not checked by this tool):")
        for c in review["citations"]:
            lines.extend(_field("- ", f"{c['rule_id']}  clause: {c['clause'] or '-'}  source: {c['source'] or '-'}", "    "))
    if review["assumptions"]:
        lines.append("  Assumptions:")
        for a in review["assumptions"]:
            lines.extend(_field("- ", a, "    "))
    if review["excluded"]:
        lines.append("  Left out:")
        for x in review["excluded"]:
            lines.extend(_field("- ", f"element {x['element_id']}: {x['reason'] or '-'}", "    "))
    if review["conflicts"]:
        lines.append(f"  Conflicts ({len(review['conflicts'])}; the model changed since the original plan ran):")
        for c in review["conflicts"]:
            lines.extend(_field(
                "- ", f"element {c['element_id']}/{c['parameter']}: model now {c['actual_current']}, "
                      f"plan wrote {c['expected_current']}, revert sets {c['revert_to']}", "    "))
    if review["warnings"]:
        lines.append("  Warnings:")
        for w in review["warnings"]:
            lines.extend(_field("! ", w, "    "))
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


def _describe_binding(plan: Dict[str, Any]) -> List[str]:
    if "binding" not in plan:
        return []
    b = plan["binding"]
    if not isinstance(b, dict):
        return ["Document: NOT BOUND to a Revit document (no live document could be read when it was drafted); "
                "it will not be refused for being run in another model."]
    view = f", view {safe_text(b['active_view_id'])}" if b.get("active_view_id") is not None else ""
    return [f"Document: {safe_text(b.get('doc_title'))} (Revit {safe_text(b.get('revit_version'))}{view}); "
            "refused if another document is active when it runs."]


def describe_plan(plan: Dict[str, Any], expired: Optional[str] = None) -> str:
    actions = _actions(plan)
    lines = [
        f"Plan {safe_text(plan.get('plan_id'))}  [{safe_text(plan.get('state'))}]",
        f"Created: {safe_text(plan.get('created_at', 'unknown'))}",
        *([f"EXPIRED: {safe_text(expired)}"] if expired else []),
        *_describe_binding(plan),
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
    stuck = running_actions(plan)
    if stuck:
        lines.append("\nActions stuck in 'running' (claimed, no result recorded; the process may have died):")
        for r in stuck:
            age = r["age_seconds"]
            age_txt = "unknown age" if age is None else f"{int(age // 60)} min {int(age % 60)} s"
            flag = "STALE" if r["stale"] else "recent"
            lines.append(f"  - {safe_text(r['action_id'])} {safe_text(r['tool'])}: running for {age_txt} [{flag}]")
        lines.append(f"  Nothing recovers these automatically. After {STALE_RUNNING_SECONDS // 60} minutes a person can run "
                     f"`aec-model-bridge-approve recover {safe_text(plan.get('plan_id'))} --reason ...` "
                     "(the action is abandoned and never re-run).")
    for a in actions:
        if isinstance(a, dict) and a.get("state") == "abandoned":
            lines.append(f"Abandoned: {safe_text(a.get('action_id'))} at {safe_text(a.get('abandoned_at', '-'))} by "
                         f"{safe_text(a.get('abandoned_by', '-'))}: {safe_text(a.get('abandoned_reason', '-'))}")
    if plan.get("reverts_plan_id"):
        lines.append(f"Reverts plan: {safe_text(plan['reverts_plan_id'])}")
    lines.extend(_describe_review(plan))
    legacy = [k for k in ("conflicts", "notes", "warnings") if k in plan]
    if legacy:
        lines.append("\nNOT covered by the approval (stored outside the hashed content, drafted before the review block):")
        for k in legacy:
            lines.extend(_field(f"{k}: ", repr(plan[k])[:1500], "  "))
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


def _confirm(plan_id: str, verb: str, assume_yes: bool, what: str = "plan id", target: str = "it") -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            f"Refusing to {verb} without a terminal. Run this command yourself in a terminal, "
            "or pass --yes if you are a person scripting your own approvals.",
            file=sys.stderr,
        )
        return False
    typed = input(f"Type the {what} ({plan_id}) to {verb} {target}, or anything else to cancel: ").strip()
    return typed == plan_id


def _recipe_command(gate: ApprovalGate, args: Any) -> int:
    """Standing approval of one recipe. Humans only: no MCP tool, panel route or plan can reach this."""
    store = RecipeStore(gate.workspace_dir)
    try:
        rid = validate_recipe_id(args.recipe_id)
        if args.command == "recipe-revoke":
            print(f"Recipe {rid}: standing approval removed." if store.revoke_standing(rid) else f"Recipe {rid} had no standing approval.")
            return 0
        recipe = store.load(rid)
        print(f"Recipe {safe_text(rid)}  version {recipe.version}  mode {recipe.mode}")
        print(f"Title: {safe_text(recipe.manifest.get('title', ''))}")
        print(f"sha256: {recipe.sha256}")
        print("\nCode:")
        for line in recipe.code.split("\n"):
            print("  " + safe_text(line))
        if args.sha256 != recipe.sha256:
            print(f"\n--sha256 does not match the code above ({recipe.sha256}). Nothing was granted.", file=sys.stderr)
            return 1
        print("\nA standing approval lets this exact code run without a plan each time, with any parameter values. "
              "It ends when the recipe is saved, edited or deleted. Look only mode still blocks it.")
        if not _confirm(rid, "grant a standing approval to", args.yes, what="recipe id"):
            print("Cancelled; nothing granted.", file=sys.stderr)
            return 2
        store.grant_standing(rid, args.sha256, local_user())
    except RecipeError as e:
        print(safe_text(e), file=sys.stderr)
        return 1
    print(f"Recipe {rid}: standing approval granted for sha256 {recipe.sha256[:12]}...")
    return 0


def _older_than(plan: Dict[str, Any], days: float) -> bool:
    """True only when created_at parses and is more than ``days`` days ago."""
    try:
        created = datetime.fromisoformat(str(plan.get("created_at")))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created < datetime.now(timezone.utc) - timedelta(days=days)


def _reject_pending(gate: ApprovalGate, args: Any) -> int:
    """Bulk cleanup for a person: reject pending plans only, via the normal reject path."""
    plans = gate.list_pending_plans(include_expired=True)  # clearing stale drafts is the point
    if args.older_than is not None:
        plans = [p for p in plans if _older_than(p, args.older_than)]
    ids = [p["plan_id"] for p in sorted(plans, key=lambda p: str(p.get("created_at", "")))]
    if not ids:
        print("No pending plans match; nothing to reject.")
        return 0
    print(f"{'Would reject' if args.dry_run else 'Pending plans to reject'} ({len(ids)}):")
    for plan_id in ids:
        print(f"  {safe_text(plan_id)}")
    if args.dry_run:
        print("Dry run: nothing changed.")
        return 0
    if not _confirm("reject", "reject", args.yes, what="word", target=f"all {len(ids)} pending plan(s) above"):
        print("Cancelled; no plan changed.", file=sys.stderr)
        return 2
    failed = 0
    for plan_id in ids:
        try:
            gate.update_plan_state(plan_id, "rejected", via="cli", only_if_state="pending")
        except (ValueError, BridgeError) as e:
            failed += 1
            print(f"Skipped {safe_text(plan_id)}: {safe_text(e)}", file=sys.stderr)
            continue
        print(f"Rejected {safe_text(plan_id)}")
    return 1 if failed else 0


_PAST_TENSE = {"approve": "approved", "reject": "rejected"}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aec-model-bridge-approve",
        description="Review and approve or reject plans drafted by an AI assistant. Humans only.",
    )
    parser.add_argument("--workspace", help="workspace folder holding plans/ (default: the configured workspace)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list pending plans").add_argument(
        "--all", action="store_true", help="also list expired pending plans (they cannot be approved)")
    for name in ("show", "approve", "reject"):
        p = sub.add_parser(name, help=f"{name} a plan")
        p.add_argument("plan_id", nargs="?" if name == "reject" else None)
        if name != "show":
            p.add_argument("--yes", action="store_true", help=f"{name} without the typed confirmation")
        if name == "reject":
            p.add_argument("--older-than", type=float, metavar="DAYS",
                           help="instead of one plan id: reject every pending plan older than DAYS days")
            p.add_argument("--all-pending", action="store_true",
                           help="instead of one plan id: reject every pending plan")
            p.add_argument("--dry-run", action="store_true",
                           help="with --older-than or --all-pending: list what would be rejected, change nothing")
    rec = sub.add_parser("recover", help="abandon actions stuck in 'running' after a crash (never re-run)")
    rec.add_argument("plan_id")
    rec.add_argument("--reason", required=True, help="why the action is being abandoned (recorded)")
    rec.add_argument("--force", action="store_true", help="also abandon actions younger than the stale threshold")
    rec.add_argument("--yes", action="store_true", help="recover without the typed confirmation")
    std = sub.add_parser("recipe-standing", help="give one write recipe a standing approval, bound to its id and code hash")
    std.add_argument("recipe_id")
    std.add_argument("--sha256", required=True, help="sha256 of the recipe code you reviewed (revit_recipe_get shows it)")
    std.add_argument("--yes", action="store_true", help="grant without the typed confirmation")
    rev = sub.add_parser("recipe-revoke", help="remove the standing approval of a recipe")
    rev.add_argument("recipe_id")
    args = parser.parse_args(argv)
    if args.command == "reject":
        bulk = args.all_pending or args.older_than is not None
        if bool(args.plan_id) == bulk or (args.all_pending and args.older_than is not None):
            parser.error("reject needs exactly one of: a plan id, --older-than DAYS, or --all-pending")
        if args.dry_run and not bulk:
            parser.error("--dry-run goes with --older-than or --all-pending")
        if args.older_than is not None and not (math.isfinite(args.older_than) and args.older_than >= 0):
            parser.error("--older-than must be a finite number of days, zero or more")

    gate = _gate(args.workspace)

    if args.command in ("recipe-standing", "recipe-revoke"):
        return _recipe_command(gate, args)

    if args.command == "list":
        plans, hidden = gate.pending_listing(include_expired=args.all)
        if not plans:
            print("No pending plans.")
        for plan in sorted(plans, key=lambda p: str(p.get("created_at", ""))):
            acts = _actions(plan)
            tools = sorted({safe_text(a.get("tool") if isinstance(a, dict) else "<malformed>") for a in acts})
            print(f"{safe_text(plan['plan_id'])}  {safe_text(plan.get('created_at', ''))}  {len(acts)} action(s)  "
                  f"{', '.join(tools)}{'  [EXPIRED]' if plan.get('expired') else ''}")
        if hidden:
            print(f"{hidden} expired pending plan(s) not shown (pending_ttl); "
                  "list --all shows them, reject --older-than clears them.")
        return 0

    if args.command == "reject" and not args.plan_id:
        return _reject_pending(gate, args)

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
    expired = gate.expiry_reason(plan)
    print(describe_plan(plan, expired))
    aids = review_aids(plan, gate.workspace_dir)
    if aids.get("preview_markdown"):
        print("\nPreview (computed from the actions above, not part of the hash):\n" + "\n".join(safe_text(ln) for ln in aids["preview_markdown"].split("\n")))
    print(f"\nPlan hash: {shown_hash}")

    if args.command == "show":
        return 0

    if args.command == "recover":
        if not running_actions(plan):
            print("\nNo action is in state 'running'; nothing to recover.", file=sys.stderr)
            return 1
        print("\nRecovering marks every 'running' action above as abandoned. It is never run again, and the "
              "plan's remaining actions cannot run; a new plan must be drafted and approved for them.")
        if not _confirm(args.plan_id, "recover", args.yes):
            print("Cancelled; plan unchanged.", file=sys.stderr)
            return 2
        try:
            gate.recover_running_actions(args.plan_id, args.reason, by=local_user(), force=args.force)
        except (ValueError, BridgeError) as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"Plan {args.plan_id}: running actions abandoned.")
        return 0

    allowed = ("pending",) if args.command == "approve" else ("pending", "approved")
    if plan.get("state") not in allowed:
        print(f"\nPlan is '{safe_text(plan.get('state'))}'; it cannot be {_PAST_TENSE[args.command]}.", file=sys.stderr)
        return 1
    if expired and args.command == "approve":
        print("\nThis plan has expired and cannot be approved. Reject it and ask for a new plan.", file=sys.stderr)
        return 1
    problems = malformed_reasons(plan)
    if problems and args.command == "approve":
        print("\nThis plan is malformed (" + safe_text("; ".join(problems)) + ") and cannot be approved. "
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
