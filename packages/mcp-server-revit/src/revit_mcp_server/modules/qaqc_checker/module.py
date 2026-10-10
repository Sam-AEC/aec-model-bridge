"""
qaqc_checker module — P10 QA/QC Validation Workflows (W7, W9).

Commands:
  run_check     — Run a YAML rule pack against a snapshot, store findings in SQLite.
  list_issues   — Query issue store (filtered by status/severity).
  resolve_issue — Mark an issue as resolved.
  list_rules    — Enumerate rules in a pack.
  list_rule_packs / validate_rule_pack / import_rule_pack / export_rule_pack
                — Shareable packs: built-ins plus <workspace>/rule_packs/*.yaml.

Architecture:
  - Rule packs: YAML files in modules/qaqc_checker/rules/ (P10.2)
  - Issue store: SQLite per workspace, one row per issue with lifecycle (P10.3)
  - Rules run synchronously (P10.4 async via JobManager is wired as a future extension)
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from revit_mcp_server.errors import WorkspaceViolation

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

USER_PACKS_DIRNAME = "rule_packs"
MAX_PACK_BYTES = 1_000_000
PACK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
SEVERITIES = ("error", "warning", "info")
# Exactly what _match_element / _run_rule implement. Do not add names here
# without adding engine support.
FILTER_KEYS = ("category", "placed", "parameter", "workset", "family_source")
PARAMETER_KEYS = ("name", "empty", "value")
RULE_KEYS = ("id", "severity", "category", "description", "filter", "assertion", "fix_template")
ASSERTION_COUNT = "element_count == 0"
ASSERTION_PREFIX = "all elements have "


def _workspace_root(workspace: Any) -> Path:
    return Path(workspace.allowed_directories[0])


def _assert_in_workspace(workspace: Any, candidate: Path) -> Path:
    """Resolve candidate (following symlinks) and require it inside the workspace."""
    checker = getattr(workspace, "assert_in_workspace", None)
    if callable(checker):
        return checker(candidate)
    resolved = Path(candidate).resolve()
    roots = [Path(d).resolve() for d in workspace.allowed_directories]
    if not any(resolved.is_relative_to(r) for r in roots):
        raise WorkspaceViolation(f"{resolved} is outside the allowed workspace directories")
    return resolved


def _check_pack_name(name: Any) -> str:
    if not isinstance(name, str) or not PACK_NAME_RE.match(name) or name.endswith("."):
        raise ValueError(
            f"Invalid rule pack name {name!r}: use letters, digits, '_', '-' or '.' only "
            "(max 64 chars, no path separators)."
        )
    return name


def _user_packs_dir(workspace: Any) -> Path:
    return _workspace_root(workspace) / USER_PACKS_DIRNAME


def _resolve_pack_path(pack_name: str, workspace: Any = None) -> Path:
    """Resolve a pack name to a YAML file: built-in first, then workspace rule_packs/."""
    _check_pack_name(pack_name)
    builtin = RULES_DIR / f"{pack_name}.yaml"
    if builtin.is_file():
        return builtin
    if workspace is not None:
        user = _user_packs_dir(workspace) / f"{pack_name}.yaml"
        if user.is_file():
            return _assert_in_workspace(workspace, user)
    raise ValueError(
        f"Rule pack '{pack_name}' not found (looked for a built-in pack and "
        f"'{USER_PACKS_DIRNAME}/{pack_name}.yaml' in the workspace)."
    )


def _load_yaml_file(path: Path) -> Any:
    if path.stat().st_size > MAX_PACK_BYTES:
        raise ValueError(f"Rule pack file is larger than {MAX_PACK_BYTES} bytes.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_rule_pack(pack_name: str, workspace: Any = None) -> List[Dict[str, Any]]:
    path = _resolve_pack_path(pack_name, workspace)
    data = _load_yaml_file(path)
    errors = _validate_pack_data(data)["errors"]
    if errors:
        first = errors[0]
        raise ValueError(
            f"Rule pack '{pack_name}' is invalid ({len(errors)} error(s)); first: "
            f"{first.get('rule_id') or 'pack'}: {first['message']}"
        )
    return data.get("rules", [])


def _err(rule_id: Any, field: str, message: str) -> Dict[str, Any]:
    return {"rule_id": rule_id, "field": field, "message": message}


def _validate_filter(rid: Any, flt: Any, errors: List[Dict[str, Any]]) -> None:
    if not isinstance(flt, dict):
        errors.append(_err(rid, "filter", "filter must be a mapping."))
        return
    for key, val in flt.items():
        f = f"filter.{key}"
        if key not in FILTER_KEYS:
            errors.append(_err(rid, f, f"Unknown filter operator '{key}'. Supported: {', '.join(FILTER_KEYS)}."))
        elif key == "category":
            cats = val if isinstance(val, list) else [val]
            if not cats or not all(isinstance(c, str) and c for c in cats):
                errors.append(_err(rid, f, "category must be a non-empty string or list of strings (e.g. OST_Doors)."))
        elif key == "placed":
            if not isinstance(val, bool):
                errors.append(_err(rid, f, "placed must be true or false."))
        elif key in ("workset", "family_source"):
            if not isinstance(val, str) or not val:
                errors.append(_err(rid, f, f"{key} must be a non-empty string."))
        elif key == "parameter":
            if not isinstance(val, dict):
                errors.append(_err(rid, f, "parameter must be a mapping with 'name' and 'empty' or 'value'."))
                continue
            for k in val:
                if k not in PARAMETER_KEYS:
                    errors.append(_err(rid, f"{f}.{k}", f"Unknown parameter operator '{k}'. Supported: {', '.join(PARAMETER_KEYS)}."))
            if not isinstance(val.get("name"), str) or not val.get("name"):
                errors.append(_err(rid, f"{f}.name", "parameter.name is required and must be a non-empty string."))
            has_empty, has_value = "empty" in val, "value" in val
            if has_empty == has_value:
                errors.append(_err(rid, f, "parameter needs exactly one of 'empty: true' or 'value: <text>'."))
            if has_empty and val["empty"] is not True:
                errors.append(_err(rid, f"{f}.empty", "parameter.empty only supports true."))
            if has_value and isinstance(val["value"], (dict, list)):
                errors.append(_err(rid, f"{f}.value", "parameter.value must be a scalar (compared as text)."))


def _validate_pack_data(data: Any) -> Dict[str, Any]:
    """Schema-check parsed pack data. Pure: never evaluates anything."""
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if not isinstance(data, dict):
        errors.append(_err(None, "", "Top level must be a mapping with a 'rules' list."))
        return {"errors": errors, "warnings": warnings, "rules_count": 0}
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append(_err(None, "rules", "'rules' must be a non-empty list."))
        return {"errors": errors, "warnings": warnings, "rules_count": 0}
    seen: set = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(_err(f"rules[{i}]", "", "Each rule must be a mapping."))
            continue
        rid = rule.get("id")
        label: Any = rid if isinstance(rid, str) and rid else f"rules[{i}]"
        if not isinstance(rid, str) or not RULE_ID_RE.match(rid):
            errors.append(_err(label, "id", "id is required: letters, digits, '_', '-' or '.' (e.g. door_missing_mark)."))
        elif rid in seen:
            errors.append(_err(label, "id", f"Duplicate rule id '{rid}'."))
        else:
            seen.add(rid)
        if rule.get("severity") not in SEVERITIES:
            errors.append(_err(label, "severity", f"severity is required and must be one of {', '.join(SEVERITIES)}."))
        desc = rule.get("description")
        if not isinstance(desc, str) or not desc.strip():
            errors.append(_err(label, "description", "description is required (it becomes the issue message)."))
        for opt in ("category", "fix_template"):
            if opt in rule and not isinstance(rule[opt], str):
                errors.append(_err(label, opt, f"{opt} must be a string."))
        for k in rule:
            if k not in RULE_KEYS:
                warnings.append(_err(label, k, f"Unknown rule field '{k}' is ignored."))
        if "filter" not in rule:
            warnings.append(_err(label, "filter", "No filter: the rule applies to every element."))
        else:
            _validate_filter(label, rule["filter"], errors)
        assertion = rule.get("assertion", ASSERTION_COUNT)
        if not isinstance(assertion, str):
            errors.append(_err(label, "assertion", "assertion must be a string."))
        elif assertion != ASSERTION_COUNT and not (
            assertion.startswith(ASSERTION_PREFIX) and assertion[len(ASSERTION_PREFIX):].strip()
        ):
            errors.append(_err(
                label, "assertion",
                f"Unknown assertion '{assertion}'. Supported: '{ASSERTION_COUNT}' or '{ASSERTION_PREFIX}<field>'.",
            ))
    return {"errors": errors, "warnings": warnings, "rules_count": len(rules)}


def _validate_file(path: Path) -> Dict[str, Any]:
    try:
        data = _load_yaml_file(path)
    except yaml.YAMLError as e:
        return {"errors": [_err(None, "", f"YAML parse error: {e}")], "warnings": [], "rules_count": 0}
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return {"errors": [_err(None, "", f"Cannot read file: {e}")], "warnings": [], "rules_count": 0}
    return _validate_pack_data(data)


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
        rules = _load_rule_pack(rule_pack, workspace)
        
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

    def list_rules(self, rule_pack: str = "core", workspace: Any = None, **_) -> Dict[str, Any]:
        rules = _load_rule_pack(rule_pack, workspace)
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
    # Shareable rule packs
    # -----------------------------------------------------------------------

    def list_rule_packs(self, workspace: Any = None, **_) -> Dict[str, Any]:
        packs: List[Dict[str, Any]] = []

        def describe(path: Path, source: str) -> Dict[str, Any]:
            result = _validate_file(path)
            return {
                "name": path.stem,
                "source": source,
                "path": str(path),
                "rules_count": result["rules_count"],
                "valid": not result["errors"],
                "error_count": len(result["errors"]),
            }

        for p in sorted(RULES_DIR.glob("*.yaml")):
            packs.append(describe(p, "builtin"))
        if workspace is not None:
            udir = _user_packs_dir(workspace)
            if udir.is_dir():
                for p in sorted(udir.glob("*.yaml")):
                    if p.is_file() and PACK_NAME_RE.match(p.stem):
                        try:
                            _assert_in_workspace(workspace, p)
                        except WorkspaceViolation:
                            continue
                        packs.append(describe(p, "user"))
        return {"total": len(packs), "packs": packs}

    def validate_rule_pack(self, path: str = "", rule_pack: str = "", workspace: Any = None, **_) -> Dict[str, Any]:
        if bool(path) == bool(rule_pack):
            raise ValueError("Provide exactly one of 'path' (YAML file in the workspace) or 'rule_pack' (pack name).")
        if rule_pack:
            target = _resolve_pack_path(rule_pack, workspace)
        else:
            target = _assert_in_workspace(workspace, Path(path))
            if not target.is_file():
                raise ValueError(f"File not found: {path}")
        result = _validate_file(target)
        return {
            "path": str(target),
            "valid": not result["errors"],
            "rules_count": result["rules_count"],
            "errors": result["errors"],
            "warnings": result["warnings"],
        }

    def import_rule_pack(
        self, source_path: str, name: str = "", overwrite: bool = False, workspace: Any = None, **_
    ) -> Dict[str, Any]:
        src = _assert_in_workspace(workspace, Path(source_path))
        if not src.is_file():
            raise ValueError(f"File not found: {source_path}")
        if src.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError("Rule pack files must have a .yaml or .yml extension.")
        pack_name = _check_pack_name(name or src.stem)
        if (RULES_DIR / f"{pack_name}.yaml").exists():
            raise ValueError(f"'{pack_name}' is a built-in pack name; choose another name.")
        result = _validate_file(src)
        if result["errors"]:
            raise ValueError(
                f"Refusing to import invalid rule pack ({len(result['errors'])} error(s)): "
                + "; ".join(f"{e['rule_id'] or 'pack'}: {e['message']}" for e in result["errors"][:5])
            )
        udir = _user_packs_dir(workspace)
        _assert_in_workspace(workspace, udir)
        dest = udir / f"{pack_name}.yaml"
        _assert_in_workspace(workspace, dest)
        if dest.exists() and not overwrite:
            raise ValueError(f"Rule pack '{pack_name}' already exists; pass overwrite=true to replace it.")
        udir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return {
            "status": "imported", "name": pack_name, "path": str(dest),
            "rules_count": result["rules_count"], "warnings": result["warnings"],
        }

    def export_rule_pack(
        self, rule_pack: str, destination: str = "", overwrite: bool = False, workspace: Any = None, **_
    ) -> Dict[str, Any]:
        src = _resolve_pack_path(rule_pack, workspace)
        result = _validate_file(src)
        if result["errors"]:
            raise ValueError(f"Refusing to export invalid rule pack '{rule_pack}'; run validate_rule_pack.")
        if destination:
            dest = _assert_in_workspace(workspace, Path(destination))
            if dest.is_dir():
                dest = dest / f"{rule_pack}.yaml"
                _assert_in_workspace(workspace, dest)
        else:
            dest = _workspace_root(workspace) / "exports" / f"{rule_pack}.yaml"
            _assert_in_workspace(workspace, dest)
        if dest.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError("Destination must end in .yaml or .yml.")
        if dest.exists() and not overwrite:
            raise ValueError(f"Destination '{dest}' already exists; pass overwrite=true to replace it.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return {"status": "exported", "name": rule_pack, "path": str(dest), "rules_count": result["rules_count"]}

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _get_data(self, snapshot_id: str, workspace: Any):
        if not snapshot_id:
            from revit_mcp_server.semantic.engine import generate_mock_snapshot, require_snapshot_or_mock
            require_snapshot_or_mock(snapshot_id, "qaqc_checker")
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
