"""Read-only MCP resources over the workspace: snapshots, plans, proof bundles, latest QA run.

Nothing here writes, approves or runs a tool. Every id taken from a URI is validated with
the same allow-lists the tools use (``validate_plan_id``, ``snapshot_file``, ``proof_path``)
and every result passes through ``redact_data``, like tool results do. Snapshot resources
return counts, source and coverage only, never the element list.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from mcp.types import Resource, ResourceTemplate

from .security.approval import ApprovalGate, validate_plan_id
from .security.audit import redact_data
from .security.proof import read_proof
from .security.safe_paths import SNAPSHOT_ID_RE, snapshot_file

MIME = "application/json"
MAX_SNAPSHOTS_LISTED = 100
QAQC_DB = "qaqc_issues.db"

STATIC_RESOURCES = (
    ("aec://workspace/snapshots", "Workspace snapshots", "Saved model snapshots, newest first (id, time, model, element count)."),
    ("aec://plans/pending", "Pending plans", "Plans waiting for a person to approve them (id, state, summary). No element data."),
    ("aec://qa/latest", "Latest QA run", "Issue counts by severity and status for the most recent QA/QC run."),
)
TEMPLATES = (
    ("aec://snapshot/{id}/summary", "Snapshot summary", "Counts, source and coverage of one snapshot. Not the element list."),
    ("aec://plan/{id}", "Plan", "One plan with its actions and state."),
    ("aec://proof/{id}", "Proof bundle", "The proof bundle recorded for an executed plan."),
)


class ResourceError(ValueError):
    """The URI is unknown, malformed or names an id that is not allowed."""


def list_resources() -> list[Resource]:
    return [Resource(uri=u, name=n, description=d, mimeType=MIME) for u, n, d in STATIC_RESOURCES]


def list_resource_templates() -> list[ResourceTemplate]:
    return [ResourceTemplate(uriTemplate=u, name=n, description=d, mimeType=MIME) for u, n, d in TEMPLATES]


def _dump(value: Any) -> str:
    return json.dumps(redact_data(value), indent=2, default=str)


def _snapshots_dir(workspace_dir: Path) -> Path:
    return Path(workspace_dir) / "snapshots"


def _snapshot_path(workspace_dir: Path, snapshot_id: str) -> Path:
    try:
        return snapshot_file(_snapshots_dir(workspace_dir), snapshot_id)
    except ValueError as exc:
        raise ResourceError(str(exc)) from None


def _load_json(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _source(data: dict) -> dict:
    src = data.get("source") if isinstance(data.get("source"), dict) else {}
    return {k: src.get(k) for k in ("app", "app_version", "doc_guid", "doc_title", "units") if src.get(k) is not None}


def _snapshots_list(workspace_dir: Path) -> dict:
    folder = _snapshots_dir(workspace_dir)
    files = []
    if folder.is_dir():
        files = [p for p in folder.glob("*.json") if SNAPSHOT_ID_RE.fullmatch(p.stem) and p.is_file() and not p.is_symlink()]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    rows = []
    for path in files[:MAX_SNAPSHOTS_LISTED]:
        data = _load_json(path)
        if data is None:
            continue
        rows.append({
            "snapshot_id": path.stem,
            "taken_at": data.get("taken_at"),
            "model": _source(data).get("doc_title"),
            "element_count": len(data.get("elements") or []),
        })
    return {"total": len(files), "listed": len(rows), "snapshots": rows}


def _snapshot_summary(workspace_dir: Path, snapshot_id: str) -> dict:
    path = _snapshot_path(workspace_dir, snapshot_id)
    data = _load_json(path) if path.is_file() else None
    if data is None:
        raise ResourceError(f"Snapshot '{snapshot_id}' was not found or could not be read.")
    elements = [e for e in (data.get("elements") or []) if isinstance(e, dict)]
    per_category: dict[str, int] = {}
    for el in elements:
        key = str(el.get("category") or "unknown")
        per_category[key] = per_category.get(key, 0) + 1
    return {
        "snapshot_id": snapshot_id,
        "schema": data.get("schema"),
        "taken_at": data.get("taken_at"),
        "source": _source(data),
        "element_count": len(elements),
        "relation_count": len(data.get("relations") or []),
        "counts_per_category": dict(sorted(per_category.items(), key=lambda kv: (-kv[1], kv[0]))),
        "coverage": data.get("counts") if isinstance(data.get("counts"), dict) else {},
        "dirty_only": bool(data.get("dirty_only")),
    }


def _plan_brief(plan: dict) -> dict:
    actions = [a for a in (plan.get("actions") or []) if isinstance(a, dict)]
    review = plan.get("review") if isinstance(plan.get("review"), dict) else {}
    return {
        "plan_id": plan.get("plan_id"),
        "state": plan.get("state"),
        "created_at": plan.get("created_at"),
        "snapshot_id": plan.get("snapshot_id"),
        "action_count": len(actions),
        "tools": sorted({str(a.get("tool")) for a in actions}),
        "summary": review.get("summary") or review.get("title"),
    }


def _plans_pending(gate: ApprovalGate) -> dict:
    live, expired = gate.pending_listing()
    return {"pending": [_plan_brief(p) for p in live], "expired_hidden": expired}


def _plan(gate: ApprovalGate, plan_id: str) -> dict:
    try:
        plan_id = validate_plan_id(plan_id)
        plan = gate.load_plan(plan_id)
    except Exception as exc:
        raise ResourceError(str(exc)) from None
    if plan is None:
        raise ResourceError(f"Plan '{plan_id}' was not found.")
    return plan


def _proof(workspace_dir: Path, plan_id: str) -> dict:
    try:
        bundle = read_proof(Path(workspace_dir), plan_id)
    except (ValueError, OSError) as exc:
        raise ResourceError(str(exc)) from None
    if bundle is None:
        raise ResourceError(f"No proof bundle exists for plan '{plan_id}'.")
    return bundle


def _qa_latest(workspace_dir: Path) -> dict:
    db = Path(workspace_dir) / QAQC_DB
    if not db.is_file():
        return {"available": False, "message": "No QA/QC run has been recorded in this workspace."}
    try:
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"available": False, "message": "The QA/QC database could not be opened."}
    try:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM qaqc_runs ORDER BY id DESC LIMIT 1").fetchone()
        if run is None:
            return {"available": False, "message": "No QA/QC run has been recorded in this workspace."}
        rows = conn.execute(
            "SELECT severity, status, COUNT(*) AS n FROM issues WHERE doc_guid=? AND rule_pack=? "
            "AND last_seen_at=? GROUP BY severity, status ORDER BY severity, status",
            (run["doc_guid"], run["rule_pack"], run["run_at"]),
        ).fetchall()
    except sqlite3.Error:
        return {"available": False, "message": "The QA/QC database could not be read."}
    finally:
        conn.close()
    return {
        "available": True,
        "run_at": run["run_at"],
        "rule_pack": run["rule_pack"],
        "snapshot_id": run["snapshot_id"] or None,
        "document": run["doc_guid"],
        "issues": [{"severity": r["severity"], "status": r["status"], "count": r["n"]} for r in rows],
        "issue_total": sum(r["n"] for r in rows),
    }


_URI = re.compile(r"aec://(?P<rest>[A-Za-z0-9_\-/]+)")


def read_resource(uri: Any, workspace_dir: Path, gate: ApprovalGate) -> str:
    """Return the redacted JSON text for ``uri`` or raise ResourceError."""
    text = str(uri)
    match = _URI.fullmatch(text)
    if not match:
        raise ResourceError("Unknown resource URI.")
    parts = match.group("rest").split("/")
    if parts == ["workspace", "snapshots"]:
        return _dump(_snapshots_list(workspace_dir))
    if parts == ["plans", "pending"]:
        return _dump(_plans_pending(gate))
    if parts == ["qa", "latest"]:
        return _dump(_qa_latest(workspace_dir))
    if len(parts) == 3 and parts[0] == "snapshot" and parts[2] == "summary":
        return _dump(_snapshot_summary(workspace_dir, parts[1]))
    if len(parts) == 2 and parts[0] == "plan":
        return _dump(_plan(gate, parts[1]))
    if len(parts) == 2 and parts[0] == "proof":
        return _dump(_proof(workspace_dir, parts[1]))
    raise ResourceError("Unknown resource URI.")
