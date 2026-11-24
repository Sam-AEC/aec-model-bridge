"""MCP output schemas (structured tool output) for the most-used read tools.

A tool listed here advertises ``outputSchema`` in ``tools/list``, and a successful call returns
``structuredContent`` next to the unchanged text content. The structured value is the same JSON
object the text shows after ``Result:``, so ``response_options`` trimming and field projection
apply to both. Failed calls keep the existing error result and are not checked against a schema.

Each schema is kept small to limit ``tools/list`` size: the main top-level keys and their JSON
types, with ``required`` only for keys that every successful result carries. Objects allow extra
keys: results carry more fields than a schema lists, and a newer server can add fields without
breaking clients.

Only tools whose result is built by this Python server are listed. Tools that forward a command
to the Revit add-in return the add-in's own shape live and a generic envelope in mock mode, so a
schema for them could not be checked here.
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
}


def output_schema_for(name: str) -> Optional[dict[str, Any]]:
    return OUTPUT_SCHEMAS.get(name)


def structured_for(name: str, value: Any) -> Optional[dict[str, Any]]:
    """Return ``value`` as structuredContent when ``name`` has a schema and ``value`` matches it.

    A value that does not match is logged and left out, so the text result still reaches the
    client; the MCP SDK would otherwise turn the whole call into an error."""
    schema = OUTPUT_SCHEMAS.get(name)
    if schema is None or not isinstance(value, dict):
        return None
    try:
        import jsonschema

        jsonschema.validate(instance=value, schema=schema)
    except ImportError:  # pragma: no cover - jsonschema ships with the mcp SDK
        return value
    except Exception as exc:
        logger.warning("structured output for %s does not match its output schema: %s", name, exc)
        return None
    return value
