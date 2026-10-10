"""Proof bundles: a verifiable per-plan record of what an executed ActionPlan did.

A bundle is written to ``<workspace>/proofs/<plan_id>.json`` when a plan finishes
executing (fully, partially or not at all). It is the single input to ``plan_revert``.

What a bundle proves, and what it does not: it records the plan content (hashed),
the before values captured when the plan was drafted, the values the plan asked to
write, and the per-action outcome *reported by the provider*. It does not re-read the
model after writing, so write-back to Revit is only as verified as the live provider
call that reported success.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "amb.proof/1"
PARAM_TOOL = "revit_set_parameter_value"
_ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,128}")


def validate_plan_id(plan_id: Any) -> str:
    if not isinstance(plan_id, str) or not _ID_RE.fullmatch(plan_id):
        raise ValueError("Invalid plan_id.")
    return plan_id


def proof_path(workspace_dir: Path, plan_id: str) -> Path:
    return Path(workspace_dir) / "proofs" / f"{validate_plan_id(plan_id)}.json"


def _hashable_arguments(arguments: Any) -> Any:
    if isinstance(arguments, dict):
        return {k: v for k, v in arguments.items() if k != "plan_id"}
    return {"__not_an_object__": arguments}


# --- review block ---------------------------------------------------------------
# A plan may carry a ``review`` block: the rationale a person reads next to the actions
# (summary, reasoning, citations, assumptions, elements left out, warnings). It is
# canonicalised, size-capped and part of the plan hash (hash_version 2), so editing it
# after approval invalidates the approval. Plans without a review keep the original
# hash rule (hash_version absent) and still verify.
HASH_VERSION_REVIEW = 2
REVIEW_MAX_BYTES = 65536
REVIEW_LIMITS = {
    "summary": 2000, "reasoning": 8000, "citation_field": 500, "assumption": 1000,
    "excluded_reason": 500, "warning": 1000, "element_id": 128,
}
REVIEW_MAX_ITEMS = {"citations": 100, "assumptions": 100, "excluded": 500, "warnings": 200, "conflicts": 500}
REVIEW_KEYS = ("summary", "reasoning", "citations", "assumptions", "excluded", "warnings", "conflicts")
CITATION_KEYS = ("rule_id", "clause", "source")
CONFLICT_KEYS = ("element_id", "parameter", "expected_current", "actual_current", "revert_to")
CONFLICT_FIELD_LIMIT = 200
REVIEW_BUDGET_BYTES = 56000  # builders stay under this so a review never hits REVIEW_MAX_BYTES
EXCLUDED_KEYS = ("element_id", "reason")

# Plan keys outside ``actions`` and ``review`` that are NOT covered by the hash. They are
# bookkeeping or caller-supplied metadata: never shown as approved content, and editing
# them does not invalidate an approval.
HASHED_PLAN_KEYS_V1 = ("plan_id", "created_at", "snapshot_id", "skipped", "actions")
HASHED_PLAN_KEYS_V2 = HASHED_PLAN_KEYS_V1 + ("hash_version", "review", "reverts_plan_id")
STATE_PLAN_KEYS = frozenset({
    "state", "plan_hash", "approved_hash", "approved_at", "approved_by", "approved_via",
    "rejected_at", "rejected_via", "rejected_after_approval", "executed_at", "results",
    "is_reversible", "reversible_strategy",
})


def unhashed_metadata_keys(plan: Dict[str, Any]) -> List[str]:
    """Keys on the plan that are not part of the approval hash (excluding the plan's own
    lifecycle state). Treat their content as metadata, not approved content."""
    hashed = HASHED_PLAN_KEYS_V2 if plan.get("hash_version") == HASH_VERSION_REVIEW else HASHED_PLAN_KEYS_V1
    return sorted(str(k) for k in plan if k not in hashed and k not in STATE_PLAN_KEYS)


def _review_str(value: Any, field: str, limit: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"review.{field} must be a string.")
    if len(value) > limit:
        raise ValueError(f"review.{field} is longer than {limit} characters.")
    return value


def _review_list(value: Any, field: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"review.{field} must be a list.")
    if len(value) > REVIEW_MAX_ITEMS[field]:
        raise ValueError(f"review.{field} has more than {REVIEW_MAX_ITEMS[field]} entries.")
    return value


def _review_obj(item: Any, field: str, allowed: Tuple[str, ...]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"review.{field} entries must be objects.")
    unknown = sorted(str(k)[:40] for k in item if k not in allowed)
    if unknown:
        raise ValueError(f"review.{field} entry has unknown key(s): {', '.join(unknown)}.")
    return item


def normalize_review(review: Any) -> Dict[str, Any]:
    """Validate and canonicalise a review block. Strict: unknown keys, wrong types and
    over-long or over-large content raise ValueError. Text is stored as given (control and
    bidi characters included); it is escaped when displayed (approve_cli.safe_text)."""
    if not isinstance(review, dict):
        raise ValueError("review must be an object.")
    unknown = sorted(str(k)[:40] for k in review if k not in REVIEW_KEYS)
    if unknown:
        raise ValueError(f"review has unknown key(s): {', '.join(unknown)}.")
    out: Dict[str, Any] = {
        "summary": _review_str(review.get("summary"), "summary", REVIEW_LIMITS["summary"]),
        "reasoning": _review_str(review.get("reasoning"), "reasoning", REVIEW_LIMITS["reasoning"]),
        "citations": [], "assumptions": [], "excluded": [], "warnings": [], "conflicts": [],
    }
    for c in _review_list(review.get("citations"), "citations"):
        c = _review_obj(c, "citations", CITATION_KEYS)
        out["citations"].append({
            "rule_id": _review_str(c.get("rule_id"), "citations.rule_id", REVIEW_LIMITS["citation_field"], True),
            "clause": _review_str(c.get("clause"), "citations.clause", REVIEW_LIMITS["citation_field"]),
            "source": _review_str(c.get("source"), "citations.source", REVIEW_LIMITS["citation_field"]),
        })
    for a in _review_list(review.get("assumptions"), "assumptions"):
        out["assumptions"].append(_review_str(a, "assumptions", REVIEW_LIMITS["assumption"], True))
    for x in _review_list(review.get("excluded"), "excluded"):
        x = _review_obj(x, "excluded", EXCLUDED_KEYS)
        eid = x.get("element_id")
        if isinstance(eid, bool) or not isinstance(eid, (int, str)):
            raise ValueError("review.excluded.element_id must be an integer or string.")
        if isinstance(eid, str) and (not eid or len(eid) > REVIEW_LIMITS["element_id"]):
            raise ValueError("review.excluded.element_id is empty or too long.")
        out["excluded"].append({
            "element_id": eid,
            "reason": _review_str(x.get("reason"), "excluded.reason", REVIEW_LIMITS["excluded_reason"]),
        })
    for c in _review_list(review.get("conflicts"), "conflicts"):
        c = _review_obj(c, "conflicts", CONFLICT_KEYS)
        eid = c.get("element_id")
        if isinstance(eid, bool) or not isinstance(eid, (int, str)):
            raise ValueError("review.conflicts.element_id must be an integer or string.")
        entry: Dict[str, Any] = {"element_id": eid}
        for key in CONFLICT_KEYS[1:]:
            entry[key] = _review_str(c.get(key), f"conflicts.{key}", CONFLICT_FIELD_LIMIT)
        out["conflicts"].append(entry)
    for w in _review_list(review.get("warnings"), "warnings"):
        out["warnings"].append(_review_str(w, "warnings", REVIEW_LIMITS["warning"], True))
    size = len(json.dumps(out, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    if size > REVIEW_MAX_BYTES:
        raise ValueError(f"review is too large ({size} bytes; the limit is {REVIEW_MAX_BYTES}).")
    return out


def review_view(plan: Dict[str, Any]) -> Dict[str, Any]:
    """What the panel may show of a plan's review, computed here so the page never has to
    trust the raw plan file. ``status`` is ``none`` (a hash_version 1 plan: no review),
    ``ok`` (a v2 plan whose review is canonical and whose stored hash matches) or
    ``invalid`` (anything else; the panel must not offer Approve). ``review`` is present
    only when ``ok`` and is the normalised block that the plan hash covers."""
    view: Dict[str, Any] = {"status": "invalid", "hash_version": None, "reverts_plan_id": None,
                            "review": None, "error": ""}
    try:
        version = plan_hash_version(plan)
        view["hash_version"] = version
        if version != HASH_VERSION_REVIEW:
            view["status"] = "none"
            return view
        review = plan["review"]
        if normalize_review(review) != review:
            raise ValueError("The review block is not in canonical form.")
        reverts = plan.get("reverts_plan_id")
        if reverts is not None:
            validate_plan_id(reverts)
        if plan.get("plan_hash") != plan_content_hash(plan):
            raise ValueError("The plan content does not match its stored hash.")
        view.update(status="ok", review=review, reverts_plan_id=reverts)
    except Exception as exc:  # noqa: BLE001 - any failure means "do not show as approvable"
        view.update(status="invalid", review=None, error=str(exc)[:300])
    return view


def panel_plans(plans: Any) -> Any:
    """Shape a ``list_pending_plans`` result for the panel: each plan gets ``review_view``
    and loses its raw ``review`` (the panel reads only the validated copy). Read-only; the
    plan files and the MCP result are not changed."""
    if not isinstance(plans, dict) or not isinstance(plans.get("plans"), list):
        return plans
    out = []
    for plan in plans["plans"]:
        if not isinstance(plan, dict):
            out.append(plan)
            continue
        shaped = {k: v for k, v in plan.items() if k != "review"}
        shaped["review_view"] = review_view(plan)
        out.append(shaped)
    return {**plans, "plans": out}


def plan_hash_version(plan: Dict[str, Any]) -> int:
    """1 for plans without a review block, 2 for plans that carry one. A plan that mixes
    the two (a review without hash_version 2, or version 2 without a review) is refused."""
    has_review = "review" in plan
    if "hash_version" not in plan and not has_review:
        return 1
    version = plan.get("hash_version")
    # Strict: exactly the integer 2 (not 2.0, True, "2" or null).
    if type(version) is int and version == HASH_VERSION_REVIEW and isinstance(plan.get("review"), dict):
        return HASH_VERSION_REVIEW
    raise ValueError("Plan has an inconsistent review/hash_version combination; it cannot be verified.")


def plan_content_hash(plan: Dict[str, Any]) -> str:
    """SHA-256 over the immutable content of a plan (not its mutable state/results).

    Version 1 (no ``review``): ids, snapshot, skipped list and each action. Version 2
    additionally covers ``hash_version``, ``review`` and ``reverts_plan_id``."""
    version = plan_hash_version(plan)
    content = {
        "plan_id": plan.get("plan_id"),
        "created_at": plan.get("created_at"),
        "snapshot_id": plan.get("snapshot_id"),
        "skipped": plan.get("skipped", []),
        "actions": [
            {
                "action_id": a.get("action_id"),
                "tool": a.get("tool"),
                "arguments": _hashable_arguments(a.get("arguments")),
                "before": (a.get("diff") or {}).get("before"),
            }
            for a in plan.get("actions", [])
        ],
    }
    if version == HASH_VERSION_REVIEW:
        content["hash_version"] = HASH_VERSION_REVIEW
        content["review"] = plan["review"]
        content["reverts_plan_id"] = plan.get("reverts_plan_id")
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_snapshot_doc(workspace_dir: Path, snapshot_id: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """Return (document identity or None, element_id -> uid map)."""
    if not snapshot_id:
        return None, {}
    doc: Dict[str, Any] = {"snapshot_id": snapshot_id, "doc_guid": None, "doc_title": None}
    uids: Dict[str, str] = {}
    try:
        if not _ID_RE.fullmatch(snapshot_id):
            raise ValueError("bad snapshot id")
        with open(Path(workspace_dir) / "snapshots" / f"{snapshot_id}.json", "r", encoding="utf-8") as f:
            snap = json.load(f)
        src = snap.get("source") or {}
        doc["doc_guid"] = src.get("doc_guid")
        doc["doc_title"] = src.get("doc_title")
        for el in snap.get("elements", []):
            if el.get("element_id") is not None and el.get("uid"):
                uids[str(el["element_id"])] = el["uid"]
    except Exception:
        doc["note"] = "snapshot file could not be read; document identity unavailable"
    return doc, uids


def build_proof(
    plan: Dict[str, Any],
    workspace_dir: Path,
    results: Optional[List[Dict[str, Any]]] = None,
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the bundle. ``results`` is the per-action list from execute_plan; without
    it the outcome is derived from recorded action states only."""
    document, uids = _load_snapshot_doc(workspace_dir, plan.get("snapshot_id"))
    by_action = {r.get("action_id"): r for r in (results or [])}

    elements: List[Dict[str, Any]] = []
    other_actions: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = list(plan.get("skipped", []))
    n_ok = n_bad = 0

    for action in plan.get("actions", []):
        res = by_action.get(action.get("action_id"))
        if res is not None:
            ok = "error" not in res
            error = res.get("error")
        else:
            ok = action.get("state") == "executed"
            error = None if ok else "no per-action result recorded"
        n_ok += ok
        n_bad += not ok
        args = action.get("arguments") or {}
        if action.get("tool") == PARAM_TOOL:
            eid = args.get("element_id")
            pname = args.get("parameter_name")
            before_map = ((action.get("diff") or {}).get("before") or {}).get(str(eid), {})
            if not isinstance(before_map, dict):
                before_map = {}
            entry = {
                "action_id": action.get("action_id"),
                "element_id": eid,
                "uid": args.get("element_uid") or uids.get(str(eid)),
                "parameter": pname,
                "before": before_map.get(pname),
                "before_recorded": before_map.get(pname) is not None,
                "before_storage_type": (action.get("diff") or {}).get("before_storage_type"),
                "new": args.get("value"),
                "status": "executed" if ok else "failed",
            }
            if ok:
                elements.append(entry)
            else:
                skipped.append({**entry, "reason": error})
        else:
            other_actions.append({
                "action_id": action.get("action_id"),
                "tool": action.get("tool"),
                "status": "executed" if ok else "failed",
                **({"error": error} if error else {}),
            })

    if outcome is None:
        outcome = "success" if n_bad == 0 and n_ok > 0 else ("failed" if n_ok == 0 else "partial")

    tools = sorted({a.get("tool") for a in plan.get("actions", []) if a.get("tool")})
    return {
        "schema": SCHEMA,
        "plan_id": plan["plan_id"],
        "tool": tools[0] if len(tools) == 1 else "mixed",
        "tools": tools,
        "created_at": plan.get("created_at"),
        "approved_at": plan.get("approved_at"),
        "executed_at": plan.get("executed_at") or datetime.now(timezone.utc).isoformat(),
        "approved_by": plan.get("approved_by"),
        "approver_note": "OS account running the approving panel hub or command-line tool "
                         f"(approved via {plan.get('approved_via') or 'unknown'}); not an authenticated identity"
        if plan.get("approved_by") else "approver identity was not recorded",
        "document": document,
        "plan_hash": plan_content_hash(plan),
        "hash_version": plan_hash_version(plan),
        "review": plan.get("review"),
        "outcome": outcome,
        "reverts_plan_id": plan.get("reverts_plan_id"),
        "elements": elements,
        "skipped": skipped,
        "other_actions": other_actions,
        "verification": "UNVERIFIED against the live model: outcome is what the provider reported; "
                        "values were not re-read after writing.",
    }


def write_proof(workspace_dir: Path, bundle: Dict[str, Any]) -> Path:
    path = proof_path(workspace_dir, bundle["plan_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, default=str)
    os.replace(tmp, path)
    return path


def read_proof(workspace_dir: Path, plan_id: str) -> Optional[Dict[str, Any]]:
    path = proof_path(workspace_dir, plan_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
