"""MCP output schemas (structured tool output) for the most-used read tools.

A tool listed here advertises ``outputSchema`` in ``tools/list``, and a successful call returns
``structuredContent`` next to the unchanged text content. The structured value is the same JSON
object the text shows after ``Result:``, so ``response_options`` trimming and field projection
apply to both. Failed calls keep the existing error result and are not checked against a schema.

Every successful reply of a listed tool carries structuredContent, because clients that validate
(the Python SDK client does) reject a reply without it. When a result does not match its schema,
or the reply is not the tool's result (a queued job, a call still running, a cursor page), the
structured value is a fallback object that validates and carries ``structured_fallback``.

Each schema is kept small to limit ``tools/list`` size: the main top-level keys and their JSON
types, with ``required`` only for keys that every successful result carries. Objects allow extra
keys: results carry more fields than a schema lists, and a newer server can add fields without
breaking clients.

Only tools whose result is built by this Python server are listed. Tools that forward a command
to the Revit add-in return the add-in's own shape live and a generic envelope in mock mode, so a
schema for them could not be checked here. ``tests/test_output_schemas.py`` names the core read
tools left out for that reason.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

S, INT, B, A, OBJ = "string", "integer", "boolean", "array", "object"


def _obj(props: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": OBJ,
        "properties": {k: (v if isinstance(v, dict) else {"type": v}) for k, v in props.items()},
        "additionalProperties": True,
    }
    if required:
        schema["required"] = list(required)
    return schema


# The shared result contract of the read-only Revit check tools (check_contract.py).
_CHECK = _obj(
    {"ok": B, "tool": S, "verified": B, "summary": S, "fails": A, "info": A, "limits": OBJ},
    ("ok", "tool", "summary", "fails", "info"),
)

OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "revit_get_context": _obj(
        {"ok": B, "tool": S,
         "server": _obj({"approval_mode": S, "dev_mode": B, "plans_required": B},
                        ("approval_mode", "plans_required")),
         "document": {}, "warnings": A},
        ("ok", "tool", "server"),
    ),
    "snapshot_take": _obj(
        {"status": S, "snapshot_id": S, "elements_count": INT, "truncated": B}, ("status", "snapshot_id"),
    ),
    "snapshot_query": _obj(
        {"snapshot_id": S, "matches_count": INT, "elements": A}, ("snapshot_id", "matches_count", "elements"),
    ),
    "snapshot_compute": _obj(
        {"snapshot_id": S, "row_count": INT, "rows": A, "truncated": B}, ("snapshot_id", "row_count", "rows"),
    ),
    "snapshot_diff": _obj(
        {"added_count": INT, "deleted_count": INT, "modified_count": INT},
        ("added_count", "deleted_count", "modified_count"),
    ),
    "search_tools": _obj({"query": S, "matched": INT, "returned": INT, "tools": A}, ("matched", "tools")),
    "model_inspector_summarize_model": _obj(
        {"doc_title": S, "elements_total": INT, "by_category": OBJ}, ("elements_total", "by_category"),
    ),
    "model_bloat_audit": _obj({"summary": S, "checks": OBJ}, ("summary", "checks")),
    "revit_api_lookup": _obj({"status": S, "found": B, "summary": S, "lines": A}, ("status", "found")),
    "qaqc_checker_list_rules": _obj({"rule_pack": S, "rules": A}, ("rule_pack", "rules")),
    "qaqc_checker_list_issues": _obj({"total": INT, "issues": A}, ("total", "issues")),
    "qaqc_checker_list_rule_packs": _obj({"total": INT, "packs": A}, ("total", "packs")),
    "list_pending_plans": _obj({"plans": A}, ("plans",)),
    "policy_show": _obj({"active": B, "rules": OBJ}, ("active",)),
    # Supports response_options.fields, which can drop any key, so nothing is required.
    "module_list_commands": _obj({"modules": A}),
    "revit_review": _CHECK,
    "revit_check_levels_grids": _CHECK,
    "revit_system_report": _CHECK,
    "revit_list_views_sheets_schedules": _CHECK,
    "revit_cleanup_audit": _CHECK,
    "revit_warnings_delta": _CHECK,
    "revit_get_parameters": _CHECK,
    "naming_checker_check_names": _obj(
        {"summary": OBJ, "complete": B, "results": A, "by_kind": OBJ, "not_enough_data": A, "notes": A},
        ("summary", "complete", "results"),
    ),
    "sheet_view_audit_run_audit": _obj(
        {"status": S, "total_findings": INT, "findings": A, "by_severity": OBJ, "message": S},
        ("status", "total_findings", "findings"),
    ),
    "schedule_consistency_check_doors_and_rooms": _obj(
        {"read_only": B, "complete": B, "snapshot_id": S, "doors_checked": INT, "rooms_checked": INT,
         "total_findings": INT, "summary": S, "counts": OBJ, "skipped": A, "findings": A},
        ("complete", "total_findings", "summary", "findings"),
    ),
    "warnings_triage_review_warnings": _obj(
        {"ok": B, "read_only": B, "total_warnings": INT, "total_groups": INT, "groups": A, "notes": A, "error": S},
        ("ok",),
    ),
    "links_worksets_audit_audit": _obj(
        {"total_findings": INT, "by_severity": OBJ, "links_checked": INT, "worksets_checked": INT,
         "findings": A, "notes": A, "gaps": A, "source": S},
        ("total_findings", "findings"),
    ),
    "model_inspector_inspect_selection": _obj(
        {"inspected_count": INT, "missing_uids": A, "elements": A},
        ("inspected_count", "missing_uids", "elements"),
    ),
    "parameter_manager_filter_params": _obj(
        {"param_name": S, "element_count": INT, "rows_with_param": INT, "rows": A}, ("param_name", "rows"),
    ),
}


def output_schema_for(name: str) -> Optional[dict[str, Any]]:
    return OUTPUT_SCHEMAS.get(name)


FALLBACK_KEY = "structured_fallback"
_EMPTY = {S: "", INT: 0, "number": 0, B: False, A: [], OBJ: {}}


def _valid(value: Any, schema: dict[str, Any]) -> bool:
    import jsonschema

    try:
        jsonschema.validate(instance=value, schema=schema)
    except jsonschema.ValidationError:
        return False
    return True


def _minimal(schema: dict[str, Any], value: Any, filled: list[str], dropped: list[str], prefix: str = "") -> Any:
    """An object that validates against ``schema``: the keys of ``value`` that already validate, and
    each missing or invalid required key taken from ``value`` when possible or set to an empty value
    of its type (named in ``filled``). Keys whose value has the wrong type are left out (``dropped``)."""
    source = value if isinstance(value, dict) else {}
    props = schema.get("properties", {})
    out: dict[str, Any] = {}
    for key, item in source.items():
        sub = props.get(key)
        if sub is None or _valid(item, sub):
            out[key] = item
        elif key not in schema.get("required", []):
            dropped.append(prefix + key)
    for key in schema.get("required", []):
        if key in out:
            continue
        sub = props.get(key, {})
        if sub.get("type") == OBJ:
            out[key] = _minimal(sub, source.get(key), filled, dropped, prefix + key + ".")
            if key not in source:
                filled.append(prefix + key)
            continue
        kind = sub.get("type")
        out[key] = list(_EMPTY[kind]) if kind == A else dict(_EMPTY[kind]) if kind == OBJ else _EMPTY.get(kind)
        filled.append(prefix + key)
    return out


def fallback_structured(name: str, value: Any, reason: str) -> Optional[dict[str, Any]]:
    """structuredContent for a successful reply whose value does not match the tool's schema.

    MCP clients that validate (the Python SDK client does) reject a reply from a tool with an
    outputSchema that has no structuredContent, or whose structuredContent does not validate. This
    returns an object that validates, built from the value, with ``structured_fallback`` saying why
    and which keys were filled with empty values or left out. The text content keeps the full result
    and is the authority; filled values are placeholders, not data."""
    schema = OUTPUT_SCHEMAS.get(name)
    if schema is None:
        return None
    filled: list[str] = []
    dropped: list[str] = []
    out = _minimal(schema, value, filled, dropped)
    if value is not None and not isinstance(value, dict):
        out.setdefault("result", value)
    out[FALLBACK_KEY] = {"reason": reason, "filled": filled, "dropped": dropped,
                         "note": "The text content holds the full result; filled keys are empty placeholders."}
    if not _valid(out, schema):  # pragma: no cover - the schemas here only constrain types
        logger.error("fallback structured output for %s does not validate", name)
    return out


def structured_for(name: str, value: Any) -> Optional[dict[str, Any]]:
    """structuredContent for a successful reply of ``name``, or None when the tool has no schema.

    A value that matches the schema is returned as is. A value that does not match is logged and
    replaced by ``fallback_structured``, so SDK clients that validate still accept the reply."""
    schema = OUTPUT_SCHEMAS.get(name)
    if schema is None:
        return None
    if isinstance(value, dict) and _valid(value, schema):
        return value
    logger.warning("structured output for %s does not match its output schema; sending a fallback", name)
    return fallback_structured(name, value, "The result does not match this tool's output schema.")
