"""
qaqc_checker module — P10 QA/QC Validation Workflows (W7, W9).

Commands:
  run_check     — Run a YAML rule pack against a snapshot, store findings in SQLite.
  list_issues   — Query issue store (filtered by status/severity/snapshot). Rows not
                  seen in the latest run for their document and pack are stale and
                  hidden unless include_stale=true.
  resolve_issue — Mark an issue as resolved.
  list_rules    — Enumerate rules in a pack.
  list_rule_packs / validate_rule_pack / import_rule_pack / export_rule_pack
                — Shareable packs: built-ins plus <workspace>/rule_packs/*.yaml.
  test_naming_rule / save_naming_rule / replay_naming_rules
                — Reviewed naming rules: test a proposed regex rule (read-only), save it as
                  <workspace>/naming_rules/<id>.json (mutating, so only through an approved
                  plan), replay saved rules with no model call.

Architecture:
  - Rule packs: YAML files in modules/qaqc_checker/rules/ (P10.2)
  - Issue store: SQLite per workspace, one row per issue with lifecycle (P10.3)
  - Rules run synchronously (P10.4 async via JobManager is wired as a future extension)
"""
from __future__ import annotations
from revit_mcp_server.security.module_permissions import writable_path

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.security.workspace import effective_roots
from revit_mcp_server.security.safe_paths import safe_child, snapshot_file
from revit_mcp_server.semantic.compute import QueryError, pipeline_rows, validate_steps

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).parent / "rules"
DB_FILENAME = "qaqc_issues.db"
UNKNOWN_SNAPSHOT = "unknown"


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
            rule_pack TEXT NOT NULL DEFAULT 'core',
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            element_uid TEXT,
            label TEXT,
            message TEXT NOT NULL,
            fix_template TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            snapshot_id TEXT,
            last_seen_at TEXT
        )
    """)
    # Databases from before shareable packs have no pack identity. Preserve those
    # findings as core, the original default, instead of discarding their history.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(issues)")}
    if "rule_pack" not in columns:
        conn.execute("ALTER TABLE issues ADD COLUMN rule_pack TEXT NOT NULL DEFAULT 'core'")
    # 1.5.0 databases have no snapshot key. Old rows keep NULL: reported as an
    # unknown snapshot and never called stale until a run exists for their document.
    if "snapshot_id" not in columns:
        conn.execute("ALTER TABLE issues ADD COLUMN snapshot_id TEXT")
    if "last_seen_at" not in columns:
        conn.execute("ALTER TABLE issues ADD COLUMN last_seen_at TEXT")
    # One row per run_check: the reference point for "latest run" and stale detection.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS qaqc_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_guid TEXT NOT NULL,
            rule_pack TEXT NOT NULL,
            snapshot_id TEXT NOT NULL DEFAULT '',
            captured_at TEXT,
            run_at TEXT NOT NULL
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
RULE_KEYS = ("id", "severity", "category", "description", "filter", "assertion", "fix_template", "pipeline")
ASSERTION_COUNT = "element_count == 0"
ASSERTION_PREFIX = "all elements have "


def _workspace_root(workspace: Any) -> Path:
    return Path(workspace.allowed_directories[0])


def _assert_writable(workspace: Any, candidate: Path) -> Path:
    """Confine the path, then require files.write (a bare workspace has no write gate)."""
    return writable_path(workspace, _assert_in_workspace(workspace, candidate))


def _assert_in_workspace(workspace: Any, candidate: Path) -> Path:
    """Resolve candidate (following symlinks) and require it inside the workspace."""
    checker = getattr(workspace, "assert_in_workspace", None)
    if callable(checker):
        return checker(candidate)
    resolved = Path(candidate).resolve()
    roots = [d.resolve() for d in effective_roots(workspace)]
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
    import yaml  # loaded on first use, not at server start

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
    if "family_source" in flt and len(flt) > 1:
        errors.append(_err(
            rid, "filter.family_source",
            "family_source filters type records and cannot be combined with element filter operators.",
        ))
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


def _validate_pipeline(label: Any, rule: Dict[str, Any], errors: List[Dict[str, Any]]) -> None:
    """A pipeline rule: snapshot_compute steps whose result rows are the issues."""
    for other in ("filter", "assertion"):
        if other in rule:
            errors.append(_err(label, other, f"A pipeline rule has no {other}: every row the pipeline returns is an issue."))
    try:
        validate_steps(rule["pipeline"])
    except QueryError as e:
        errors.append(_err(label, "pipeline", str(e)))


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
        if "pipeline" in rule:
            _validate_pipeline(label, rule, errors)
            continue
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
    import yaml

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
    relations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate one rule. Returns list of issue dicts (one per offending element).

    A rule with ``pipeline`` runs it with snapshot_compute's engine; each result row
    is an issue (``uid`` gives the element, ``label`` or type_name or category the label).
    ``relations`` feed its relation joins; without them those joins find nothing.
    """
    if "pipeline" in rule:
        data = {"elements": elements, "types": types, "relations": relations or []}
        issues = []
        for row in pipeline_rows(data, rule["pipeline"]):
            uid = row.get("uid")
            if uid is not None and not isinstance(uid, str):
                raise QueryError("pipeline rows give 'uid' as text (an element uid), not a list or object")
            label = row.get("label") or row.get("type_name") or row.get("category") or ""
            issues.append({
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "element_uid": uid,
                "label": label if isinstance(label, str) else str(label),
                "message": rule["description"],
                "fix_template": rule.get("fix_template", ""),
                "doc_guid": doc_guid,
            })
        return issues
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


def _upsert_issues(
    conn: sqlite3.Connection, findings: List[Dict[str, Any]], doc_guid: str,
    elements_uids: set, rule_pack: str = "core",
    snapshot_id: str = "", captured_at: Optional[str] = None,
) -> None:
    """
    Upsert findings into issue store:
    - New issues → inserted as 'open'
    - Existing issues for same (doc_guid, rule_pack, rule_id, element_uid) already 'open' → refresh details
    - Issues previously open but NOT in current findings → resolved (element still exists) or orphaned (uid gone)
    Every finding seen is stamped with this run's snapshot_id and last_seen_at; the run
    itself is recorded so list_issues can flag rows this run did not see as stale.
    """
    now = _now()
    conn.execute(
        "INSERT INTO qaqc_runs (doc_guid, rule_pack, snapshot_id, captured_at, run_at) VALUES (?, ?, ?, ?, ?)",
        (doc_guid, rule_pack, snapshot_id or "", captured_at, now),
    )
    
    # Reconcile only this pack: other packs own independent issue lifecycles.
    existing = {
        (row["rule_id"], row["element_uid"]): row["id"]
        for row in conn.execute(
            "SELECT id, rule_id, element_uid FROM issues WHERE doc_guid=? AND rule_pack=? AND status='open'",
            (doc_guid, rule_pack)
        )
    }
    
    new_keys = set()
    for f in findings:
        key = (f["rule_id"], f.get("element_uid"))
        new_keys.add(key)
        
        if key in existing:
            # An overwritten pack can change severity or wording without changing
            # its rule IDs. Keep the stable issue ID but refresh its current facts.
            conn.execute(
                "UPDATE issues SET severity=?, label=?, message=?, fix_template=?, updated_at=?, "
                "snapshot_id=?, last_seen_at=? WHERE id=?",
                (f["severity"], f.get("label", ""), f["message"], f.get("fix_template", ""), now,
                 snapshot_id or "", now, existing[key]),
            )
        else:
            # Insert new issue
            conn.execute(
                """
                INSERT INTO issues (id, doc_guid, rule_pack, rule_id, severity, element_uid, label, message, fix_template, status, created_at, updated_at, snapshot_id, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    doc_guid,
                    rule_pack,
                    f["rule_id"],
                    f["severity"],
                    f.get("element_uid"),
                    f.get("label", ""),
                    f["message"],
                    f.get("fix_template", ""),
                    now,
                    now,
                    snapshot_id or "",
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
# Reviewed naming rules
# ---------------------------------------------------------------------------

NAMING_RULES_DIRNAME = "naming_rules"
NAMING_AUDIT_FILENAME = "naming_rules_audit.jsonl"
NAMING_TARGETS = ("type_name", "name", "family", "parameter")
MAX_REGEX_CHARS = 200
MAX_NAME_CHARS = 128
MAX_UNBOUNDED_REPEATS = 3
MAX_RULE_FILE_BYTES = 20_000
DEFAULT_SAMPLE = 10
MAX_SAMPLE = 25
_RESERVED_DEVICE_RE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])$", re.IGNORECASE)


def _check_rule_id(rule_id: Any) -> str:
    if (
        not isinstance(rule_id, str) or not RULE_ID_RE.fullmatch(rule_id) or rule_id.endswith(".")
        or _RESERVED_DEVICE_RE.match(rule_id.split(".", 1)[0])
    ):
        raise ValueError(
            f"Invalid rule id {rule_id!r}: use letters, digits, '_', '-' or '.' only "
            "(max 100 chars, start with a letter or digit, no path separators)."
        )
    return rule_id


def _check_regex(regex: Any) -> "re.Pattern[str]":
    """Compile a naming regex only if it cannot backtrack catastrophically.

    Python's re has no timeout, so the pattern is checked up front: at most 200 characters, no
    backreferences or lookarounds, no repeat inside a repeat, no alternation inside a repeat, and at
    most 3 variable repeats, counting ? and {0,n}. Names longer than 128 characters never reach the regex.
    """
    if not isinstance(regex, str) or not regex:
        raise ValueError("regex is required.")
    if len(regex) > MAX_REGEX_CHARS:
        raise ValueError(f"regex is longer than {MAX_REGEX_CHARS} characters.")
    from re import _constants as const, _parser as parser

    try:
        tree = parser.parse(regex)
        compiled = re.compile(regex)
    except (re.error, RecursionError, OverflowError) as exc:
        raise ValueError(f"The regex is not valid: {exc}") from exc
    repeats = (const.MAX_REPEAT, const.MIN_REPEAT, const.POSSESSIVE_REPEAT)
    banned = (const.GROUPREF, const.GROUPREF_EXISTS, const.ASSERT, const.ASSERT_NOT)
    unbounded = 0

    def scan(sub: Any, in_repeat: bool) -> None:
        nonlocal unbounded
        for op, av in sub:
            if op in banned:
                raise ValueError("The regex uses a backreference or lookaround, which is refused.")
            if op in repeats:
                low, high, inner = av
                variable = low != high
                if in_repeat and variable:
                    raise ValueError("The regex nests a variable repeat inside a repeat (catastrophic backtracking).")
                if variable:
                    unbounded += 1
                    if unbounded > MAX_UNBOUNDED_REPEATS:
                        raise ValueError(f"The regex has more than {MAX_UNBOUNDED_REPEATS} variable repeats.")
                scan(inner, in_repeat or high > 1)
            elif op == const.BRANCH:
                if in_repeat:
                    raise ValueError("The regex puts an alternation inside a repeat (catastrophic backtracking).")
                for branch in av[1]:
                    scan(branch, in_repeat)
            elif op == const.SUBPATTERN:
                scan(av[-1], in_repeat)
            elif op == const.ATOMIC_GROUP:
                scan(av, in_repeat)

    scan(tree, False)
    return compiled


def _naming_rule(category: Any, regex: Any, severity: Any, message: Any, target: Any = "type_name",
                 parameter: Any = None) -> Dict[str, Any]:
    if not isinstance(category, str) or not category.strip() or len(category) > 100:
        raise ValueError("category is required (for example OST_Doors).")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}.")
    if not isinstance(message, str) or not message.strip() or len(message) > 300:
        raise ValueError("message is required (max 300 characters); it becomes the finding text.")
    if target not in NAMING_TARGETS:
        raise ValueError(f"target must be one of {', '.join(NAMING_TARGETS)}.")
    if target == "parameter":
        if not isinstance(parameter, str) or not parameter.strip() or len(parameter) > 100:
            raise ValueError("parameter (a parameter name) is required when target is 'parameter'.")
    elif parameter:
        raise ValueError("parameter is only used when target is 'parameter'.")
    _check_regex(regex)
    return {
        "category": category.strip(), "regex": regex, "severity": severity, "message": message.strip(),
        "target": target, "parameter": parameter if target == "parameter" else None,
    }


def _naming_rule_hash(rule: Dict[str, Any]) -> str:
    canon = json.dumps(rule, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode("ascii")).hexdigest()


def _naming_value(el: Dict[str, Any], rule: Dict[str, Any]) -> str:
    if rule["target"] == "parameter":
        param = (el.get("params") or {}).get(rule["parameter"])
        value = param.get("v") if isinstance(param, dict) else None
    else:
        value = el.get(rule["target"])
    return "" if value is None else str(value)


def _evaluate_naming_rule(rule: Dict[str, Any], elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per element in the category: {uid, value, matched}. Sorted by uid, so it is repeatable."""
    pattern = _check_regex(rule["regex"])
    rows = []
    for el in elements:
        if el.get("category") != rule["category"]:
            continue
        value = _naming_value(el, rule)
        matched = 0 < len(value) <= MAX_NAME_CHARS and pattern.fullmatch(value) is not None
        rows.append({"uid": el.get("uid"), "value": value[:MAX_NAME_CHARS], "matched": matched})
    rows.sort(key=lambda r: (r["uid"] is None, r["uid"] or ""))
    return rows


def _sample(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"uid": row["uid"], "value": row["value"]}


def _naming_rules_dir(workspace: Any) -> Path:
    return _workspace_root(workspace) / NAMING_RULES_DIRNAME


def _naming_rule_path(workspace: Any, rule_id: Any) -> Path:
    def refuse(_reason: str) -> Exception:
        return ValueError(f"Invalid rule id {rule_id!r}: it must be a plain name, not a path.")

    _check_rule_id(rule_id)
    return safe_child(
        _workspace_root(workspace), rule_id, ".json", RULE_ID_RE, refuse, subdir=NAMING_RULES_DIRNAME
    )


def _load_naming_rule(workspace: Any, rule_id: str) -> Dict[str, Any]:
    path = _assert_in_workspace(workspace, _naming_rule_path(workspace, rule_id))
    if not path.is_file():
        raise ValueError(f"Naming rule '{rule_id}' not found in {NAMING_RULES_DIRNAME}/.")
    if path.stat().st_size > MAX_RULE_FILE_BYTES:
        raise ValueError(f"Naming rule '{rule_id}' is larger than {MAX_RULE_FILE_BYTES} bytes.")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        raw = stored["rule"]
        rule = _naming_rule(raw["category"], raw["regex"], raw["severity"], raw["message"],
                            raw.get("target", "type_name"), raw.get("parameter"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Naming rule '{rule_id}' is invalid: {exc}") from exc
    rule_hash = _naming_rule_hash(rule)
    if stored.get("rule_id") != rule_id or stored.get("rule_hash") != rule_hash or rule != raw:
        raise ValueError(f"Naming rule '{rule_id}' does not match its recorded hash; it was edited after it was saved.")
    return {"rule_id": rule_id, "rule": rule, "rule_hash": rule_hash}


def _append_naming_audit(workspace: Any, event: str, **fields: Any) -> None:
    path = _assert_writable(workspace, _workspace_root(workspace) / NAMING_AUDIT_FILENAME)
    entry = {"timestamp": _now(), "event": event, **fields}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


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
        captured_at: Optional[str] = None
        relations: List[Dict[str, Any]] = []
        if snapshot_id:
            snap_path = snapshot_file(workspace.allowed_directories[0] / "snapshots", snapshot_id)
            if snap_path.exists():
                with open(snap_path, encoding="utf-8") as f:
                    data = json.load(f)
                doc_guid = data.get("source", {}).get("doc_guid", snapshot_id)
                taken = data.get("taken_at")
                captured_at = str(taken) if taken else None
                relations = data.get("relations") or []
        elif any("pipeline" in rule for rule in rules):
            from revit_mcp_server.semantic.engine import generate_mock_snapshot
            relations = [r.model_dump(by_alias=True) for r in generate_mock_snapshot().relations]
        
        elements_uids = {el.get("uid") for el in elements + types if el.get("uid")}
        
        all_findings = []
        rules_run = []
        for rule in rules:
            try:
                findings = _run_rule(rule, elements, types, doc_guid, relations)
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
            _upsert_issues(
                conn, all_findings, doc_guid, elements_uids, rule_pack,
                snapshot_id=snapshot_id, captured_at=captured_at,
            )
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
        snapshot_id: Optional[str] = None,
        include_stale: bool = False,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        """
        Stale = the latest run for the row's (doc_guid, rule_pack) did not see it.
        Rows from before snapshot tracking have no last_seen_at and are only called
        stale once a run exists for their document and pack. Stale rows are hidden
        unless include_stale is true or status is an explicit 'resolved'/'orphaned'
        (those lifecycle states are mostly rows a later run no longer saw).
        """
        include_stale = include_stale is True or str(include_stale).lower() == "true"
        stale_sql = "(lr.run_at IS NOT NULL AND (i.last_seen_at IS NULL OR i.last_seen_at <> lr.run_at))"
        conn = _get_conn(workspace)
        query = f"""
            SELECT i.*, CASE WHEN {stale_sql} THEN 1 ELSE 0 END AS stale
            FROM issues i
            LEFT JOIN qaqc_runs lr ON lr.id = (
                SELECT MAX(id) FROM qaqc_runs r
                WHERE r.doc_guid = i.doc_guid AND r.rule_pack = i.rule_pack
            )
            WHERE 1=1"""
        params: List[Any] = []

        if doc_guid:
            query += " AND i.doc_guid=?"
            params.append(doc_guid)
        if status:
            query += " AND i.status=?"
            params.append(status)
        if severity:
            query += " AND i.severity=?"
            params.append(severity)
        if snapshot_id:
            if snapshot_id == UNKNOWN_SNAPSHOT:
                query += " AND COALESCE(i.snapshot_id, '')=''"
            else:
                query += " AND i.snapshot_id=?"
                params.append(snapshot_id)
        if not include_stale and status not in ("resolved", "orphaned"):
            query += f" AND NOT {stale_sql}"
        query += " ORDER BY i.created_at, i.id"

        rows = conn.execute(query, params).fetchall()

        run_query = "SELECT doc_guid, rule_pack, snapshot_id, captured_at, run_at FROM qaqc_runs"
        run_params: List[Any] = []
        if doc_guid:
            run_query += " WHERE doc_guid=?"
            run_params.append(doc_guid)
        run_query += " ORDER BY id DESC"
        runs = [dict(r) for r in conn.execute(run_query, run_params)]
        conn.close()

        for run in runs:
            run["snapshot_id"] = run["snapshot_id"] or UNKNOWN_SNAPSHOT
        # Newest run per (doc_guid, rule_pack); runs are already newest first.
        latest_runs: List[Dict[str, Any]] = []
        seen_keys = set()
        for run in runs:
            key = (run["doc_guid"], run["rule_pack"])
            if key not in seen_keys:
                seen_keys.add(key)
                latest_runs.append(run)

        issues = []
        for row in rows:
            issue = dict(row)
            issue["stale"] = bool(issue["stale"])
            issue["snapshot_id"] = issue["snapshot_id"] or UNKNOWN_SNAPSHOT
            issues.append(issue)
        return {
            "total": len(issues),
            "issues": issues,
            "latest_run": runs[0] if runs else None,
            "latest_runs": latest_runs,
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
        _assert_writable(workspace, udir)
        dest = udir / f"{pack_name}.yaml"
        _assert_writable(workspace, dest)
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
            dest = _assert_writable(workspace, Path(destination))
            if dest.is_dir():
                dest = dest / f"{rule_pack}.yaml"
                _assert_writable(workspace, dest)
        else:
            dest = _workspace_root(workspace) / "exports" / f"{rule_pack}.yaml"
            _assert_writable(workspace, dest)
        if dest.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError("Destination must end in .yaml or .yml.")
        if dest.exists() and not overwrite:
            raise ValueError(f"Destination '{dest}' already exists; pass overwrite=true to replace it.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return {"status": "exported", "name": rule_pack, "path": str(dest), "rules_count": result["rules_count"]}

    # -----------------------------------------------------------------------
    # Reviewed naming rules
    # -----------------------------------------------------------------------

    def test_naming_rule(
        self,
        category: str = "",
        regex: str = "",
        severity: str = "",
        message: str = "",
        target: str = "type_name",
        parameter: str = "",
        snapshot_id: str = "",
        sample_limit: int = DEFAULT_SAMPLE,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        """Read-only: run a proposed rule against a snapshot. Nothing is saved."""
        rule = _naming_rule(category, regex, severity, message, target, parameter or None)
        limit = max(0, min(int(sample_limit), MAX_SAMPLE))
        elements, _doc_guid = self._naming_data(snapshot_id, workspace)
        rows = _evaluate_naming_rule(rule, elements)
        matches = [r for r in rows if r["matched"]]
        misses = [r for r in rows if not r["matched"]]
        return {
            "rule": rule,
            "rule_hash": _naming_rule_hash(rule),
            "snapshot_id": snapshot_id or "mock",
            "elements_in_category": len(rows),
            "matches": {"count": len(matches), "sample": [_sample(r) for r in matches[:limit]]},
            "misses": {"count": len(misses), "sample": [_sample(r) for r in misses[:limit]]},
            "note": "Not saved. Saving is a plan action (qaqc_checker_save_naming_rule) that a person approves.",
        }

    def save_naming_rule(
        self,
        rule_id: str = "",
        category: str = "",
        regex: str = "",
        severity: str = "",
        message: str = "",
        target: str = "type_name",
        parameter: str = "",
        overwrite: bool = False,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        """Mutating: runs only as an approved plan action. Writes <workspace>/naming_rules/<rule_id>.json."""
        path = _naming_rule_path(workspace, rule_id)
        rule = _naming_rule(category, regex, severity, message, target, parameter or None)
        rule_hash = _naming_rule_hash(rule)
        path = _assert_writable(workspace, path)
        if path.exists() and not overwrite:
            raise ValueError(f"Naming rule '{rule_id}' already exists; pass overwrite=true to replace it.")
        body = json.dumps({"rule_id": rule_id, "rule": rule, "rule_hash": rule_hash}, indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(body)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        else:
            with open(path, "x", encoding="utf-8") as fh:
                fh.write(body)
        _append_naming_audit(workspace, "rule_saved", rule_id=rule_id, rule_hash=rule_hash, overwrite=bool(overwrite))
        return {"status": "saved", "rule_id": rule_id, "rule_hash": rule_hash, "path": str(path), "rule": rule}

    def replay_naming_rules(
        self,
        snapshot_id: str = "",
        rule_ids: Optional[List[str]] = None,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        """Replay saved naming rules against a snapshot. No model call; same snapshot, same findings."""
        udir = _naming_rules_dir(workspace)
        if rule_ids:
            ids = sorted({str(i) for i in rule_ids})
        elif udir.is_dir():
            ids = sorted(p.stem for p in udir.glob("*.json") if p.is_file() and RULE_ID_RE.fullmatch(p.stem))
        else:
            ids = []
        saved = [_load_naming_rule(workspace, rid) for rid in ids]
        elements, doc_guid = self._naming_data(snapshot_id, workspace)
        findings: List[Dict[str, Any]] = []
        per_rule = []
        for item in saved:
            rule = item["rule"]
            rows = _evaluate_naming_rule(rule, elements)
            misses = [r for r in rows if not r["matched"]]
            per_rule.append({
                "id": item["rule_id"], "rule_hash": item["rule_hash"], "severity": rule["severity"],
                "elements_checked": len(rows), "findings": len(misses), "passed": not misses,
            })
            findings.extend({
                "rule_id": item["rule_id"], "rule_hash": item["rule_hash"], "severity": rule["severity"],
                "element_uid": r["uid"], "label": r["value"], "message": rule["message"], "doc_guid": doc_guid,
            } for r in misses)
        findings.sort(key=lambda f: (f["rule_id"], f["element_uid"] is None, f["element_uid"] or ""))
        rule_hashes = {i["rule_id"]: i["rule_hash"] for i in saved}
        _append_naming_audit(
            workspace, "rules_run", snapshot_id=snapshot_id or "mock", rule_hashes=rule_hashes,
            total_findings=len(findings),
        )
        return {
            "doc_guid": doc_guid,
            "snapshot_id": snapshot_id or "mock",
            "rules_run": len(saved),
            "rule_hashes": rule_hashes,
            "total_findings": len(findings),
            "by_severity": {sev: sum(1 for f in findings if f["severity"] == sev) for sev in SEVERITIES},
            "rules": per_rule,
            "findings": findings,
        }

    def _naming_data(self, snapshot_id: str, workspace: Any):
        elements, _types = self._get_data(snapshot_id, workspace)
        doc_guid = "mock-doc"
        if snapshot_id:
            snap_dir = workspace.allowed_directories[0] / "snapshots"
            with open(snapshot_file(snap_dir, snapshot_id), encoding="utf-8") as f:
                doc_guid = json.load(f).get("source", {}).get("doc_guid", snapshot_id)
        return elements, doc_guid


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
        snap_path = snapshot_file(workspace.allowed_directories[0] / "snapshots", snapshot_id)
        if not snap_path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(snap_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("elements", []), data.get("types", [])
