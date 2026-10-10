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


def plan_content_hash(plan: Dict[str, Any]) -> str:
    """SHA-256 over the immutable content of a plan (not its mutable state/results)."""
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
