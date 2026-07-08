"""
qaqc_checker module — P10 QA/QC Validation Workflows (W7, W9).

Commands:
  run_check     — Run a YAML rule pack against a snapshot, store findings in SQLite.
  list_issues   — Query issue store (filtered by status/severity).
  resolve_issue — Mark an issue as resolved.
  list_rules    — Enumerate rules in a pack.

Architecture:
  - Rule packs: YAML files in modules/qaqc_checker/rules/ (P10.2)
  - Issue store: SQLite per workspace, one row per issue with lifecycle (P10.3)
  - Rules run synchronously (P10.4 async via JobManager is wired as a future extension)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).parent / "rules"
DB_FILENAME = "qaqc_issues.db"


# ---------------------------------------------------------------------------
# Issue store (SQLite)
# ---------------------------------------------------------------------------

def _db_path(workspace: Any) -> Path:
    return workspace.allowed_directories[0] / DB_FILENAME

def _get_conn(workspace: Any) -> sqlite3.Connection:
    path = _db_path(workspace)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            doc_guid TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            element_uid TEXT,
            label TEXT,
            message TEXT NOT NULL,
            fix_template TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

def _load_rule_pack(pack_name: str) -> List[Dict[str, Any]]:
    # Support path or name
    path = Path(pack_name)
    if not path.is_absolute() or not path.exists():
        path = RULES_DIR / f"{pack_name}.yaml"
    
    if not path.exists():
        raise ValueError(f"Rule pack '{pack_name}' not found at {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    return data.get("rules", [])

def _match_element(el: Dict[str, Any], filter_dsl: Dict[str, Any]) -> bool:
    """Apply DSL filter (subset of full DSL — covers common YAML rule patterns)."""
    for key, val in filter_dsl.items():
        if key == "category":
            cats = val if isinstance(val, list) else [val]
            if el.get("category") not in cats:
                return False
        elif key == "placed":
            is_placed = el.get("level_uid") is not None or el.get("location") is not None
            if val and not is_placed:
                return False
            elif not val and is_placed:
                return False
        elif key == "parameter":
            pname = val.get("name")
            params = el.get("params", {})
            param = params.get(pname) if params else None
            if val.get("empty") is True:
                if param is not None and param.get("v") not in (None, ""):
                    return False
            elif "value" in val:
                if param is None or str(param.get("v")) != str(val["value"]):
                    return False
        elif key == "workset" and el.get("workset") != val:
            return False
        elif key == "family_source":
            # Will be matched via types, not elements
            pass
    return True

def _evaluate_assertion(assertion: str, matched: List[Dict[str, Any]]) -> bool:
    """Returns True if assertion passes (no issue)."""
    if assertion == "element_count == 0":
        return len(matched) == 0
    if assertion.startswith("all elements have "):
        field = assertion[len("all elements have "):]
        return all(el.get(field) not in (None, "") for el in matched)
    # Default: no violation
    return True

def _run_rule(
    rule: Dict[str, Any],
    elements: List[Dict[str, Any]],
    types: List[Dict[str, Any]],
    doc_guid: str,
) -> List[Dict[str, Any]]:
    """Evaluate one rule. Returns list of issue dicts (one per offending element)."""
    filter_dsl = rule.get("filter", {})
    assertion = rule.get("assertion", "element_count == 0")
    
    # Special handling for family-level rules
    if "family_source" in filter_dsl:
        src = filter_dsl["family_source"]
        offending = [t for t in types if t.get("family_source") == src]
        matched = offending
    else:
        matched = [el for el in elements if _match_element(el, filter_dsl)]
    
    passes = _evaluate_assertion(assertion, matched)
    if passes:
        return []
    
    # Produce one issue per offending element (or one aggregate)
    if assertion == "element_count == 0":
        return [
            {
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "element_uid": el.get("uid") if isinstance(el, dict) else None,
                "label": (el.get("type_name") or el.get("category", "") if isinstance(el, dict) else str(el)),
                "message": rule["description"],
                "fix_template": rule.get("fix_template", ""),
                "doc_guid": doc_guid,
            }
            for el in matched
        ]
    else:
        # "all elements have <field>" — report elements missing the field
        field = assertion[len("all elements have "):]
        return [
            {
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "element_uid": el.get("uid"),
                "label": el.get("type_name") or el.get("category", ""),
                "message": rule["description"],
                "fix_template": rule.get("fix_template", ""),
                "doc_guid": doc_guid,
            }
            for el in matched
            if el.get(field) in (None, "")
        ]


def _upsert_issues(conn: sqlite3.Connection, findings: List[Dict[str, Any]], doc_guid: str, elements_uids: set) -> None:
    """
    Upsert findings into issue store:
    - New issues → inserted as 'open'
    - Existing issues for same (doc_guid, rule_id, element_uid) already 'open' → keep open (updated_at)
    - Issues previously open but NOT in current findings → resolved (element still exists) or orphaned (uid gone)
    """
    now = _now()
    
    # Load existing open issues for this doc
    existing = {
        (row["rule_id"], row["element_uid"]): row["id"]
        for row in conn.execute(
            "SELECT id, rule_id, element_uid FROM issues WHERE doc_guid=? AND status='open'",
            (doc_guid,)
        )
    }
    
    new_keys = set()
    for f in findings:
        key = (f["rule_id"], f.get("element_uid"))
        new_keys.add(key)
        
        if key in existing:
            # Update timestamp
            conn.execute("UPDATE issues SET updated_at=? WHERE id=?", (now, existing[key]))
        else:
            # Insert new issue
            conn.execute(
                """
                INSERT INTO issues (id, doc_guid, rule_id, severity, element_uid, label, message, fix_template, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    doc_guid,
                    f["rule_id"],
                    f["severity"],
                    f.get("element_uid"),
                    f.get("label", ""),
                    f["message"],
                    f.get("fix_template", ""),
                    now,
                    now,
                )
            )
    
    # Resolve or orphan issues that didn't reappear
    for (rule_id, uid), issue_id in existing.items():
        if (rule_id, uid) not in new_keys:
            if uid and uid not in elements_uids:
                # Element gone → orphaned
                conn.execute("UPDATE issues SET status='orphaned', updated_at=? WHERE id=?", (now, issue_id))
            else:
                # Issue fixed → resolved
                conn.execute("UPDATE issues SET status='resolved', updated_at=? WHERE id=?", (now, issue_id))
    
    conn.commit()


# ---------------------------------------------------------------------------
# Module class
# ---------------------------------------------------------------------------

class QaqcCheckerModule:

    def run_check(
        self,
        snapshot_id: str = "",
        rule_pack: str = "core",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        elements, types = self._get_data(snapshot_id, workspace)
        rules = _load_rule_pack(rule_pack)
        
        # Derive doc_guid from snapshot or fallback
        doc_guid = "mock-doc"
        if snapshot_id:
            snap_path = workspace.allowed_directories[0] / "snapshots" / f"{snapshot_id}.json"
            if snap_path.exists():
                with open(snap_path, encoding="utf-8") as f:
                    data = json.load(f)
                doc_guid = data.get("source", {}).get("doc_guid", snapshot_id)
        
        elements_uids = {el.get("uid") for el in elements if el.get("uid")}
        
        all_findings = []
        rules_run = []
        for rule in rules:
            try:
                findings = _run_rule(rule, elements, types, doc_guid)
                all_findings.extend(findings)
                rules_run.append({
                    "id": rule["id"],
                    "severity": rule["severity"],
                    "findings": len(findings),
                    "passed": len(findings) == 0,
                })
            except Exception as e:
                logger.error(f"Rule '{rule.get('id')}' failed: {e}")
                rules_run.append({"id": rule["id"], "error": str(e)})
        
        # Persist to issue store
        if workspace:
            conn = _get_conn(workspace)
            _upsert_issues(conn, all_findings, doc_guid, elements_uids)
            conn.close()
        
        return {
            "doc_guid": doc_guid,
            "rule_pack": rule_pack,
            "rules_run": len(rules_run),
            "total_findings": len(all_findings),
            "by_severity": {
                sev: sum(1 for f in all_findings if f["severity"] == sev)
                for sev in ("error", "warning", "info")
            },
            "rules": rules_run,
            "findings": all_findings,
        }

    def list_issues(
        self,
        doc_guid: str = "",
        status: Optional[str] = None,
        severity: Optional[str] = None,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        conn = _get_conn(workspace)
        query = "SELECT * FROM issues WHERE 1=1"
        params: List[Any] = []
        
        if doc_guid:
            query += " AND doc_guid=?"
            params.append(doc_guid)
        if status:
            query += " AND status=?"
            params.append(status)
        if severity:
            query += " AND severity=?"
            params.append(severity)
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        
        issues = [dict(row) for row in rows]
        return {
            "total": len(issues),
            "issues": issues,
        }

    def resolve_issue(self, issue_id: str, workspace: Any = None, **_) -> Dict[str, Any]:
        conn = _get_conn(workspace)
        conn.execute(
            "UPDATE issues SET status='resolved', updated_at=? WHERE id=?",
            (_now(), issue_id)
        )
        affected = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        conn.close()
        
        if affected == 0:
            raise ValueError(f"Issue '{issue_id}' not found.")
        
        return {"status": "resolved", "issue_id": issue_id}

    def list_rules(self, rule_pack: str = "core", **_) -> Dict[str, Any]:
        rules = _load_rule_pack(rule_pack)
        return {
            "rule_pack": rule_pack,
            "rules_count": len(rules),
            "rules": [
                {
                    "id": r["id"],
                    "severity": r["severity"],
                    "category": r.get("category", ""),
                    "description": r.get("description", ""),
                }
                for r in rules
            ],
        }

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _get_data(self, snapshot_id: str, workspace: Any):
        if not snapshot_id:
            from revit_mcp_server.semantic.engine import generate_mock_snapshot
            snap = generate_mock_snapshot()
            return (
                [el.model_dump(by_alias=True) for el in snap.elements],
                [t.model_dump() for t in snap.types],
            )
        snap_path = workspace.allowed_directories[0] / "snapshots" / f"{snapshot_id}.json"
        if not snap_path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(snap_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("elements", []), data.get("types", [])
