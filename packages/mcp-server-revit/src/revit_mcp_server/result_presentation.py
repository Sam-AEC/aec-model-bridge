"""Opt-in MCP response presentation; provider results and approval data stay intact."""
from __future__ import annotations

import copy
import json
from typing import Any


# Measured readers, not write tools. Plans may be minified but never projected.
READERS = frozenset({
    "module_list_commands", "revit_list_elements", "revit_list_families",
    "revit_get_element_parameters", "revit_list_views",
})
SUPPORTED = READERS | {"plan_actions"}


def add_response_schema(name: str, schema: dict) -> None:
    if name not in SUPPORTED:
        return
    properties = {
        "compact": {"type": "boolean", "description": "Minify response JSON; default false."},
    }
    if name in READERS:
        properties["fields"] = {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "minLength": 1},
            "description": "Return only these dotted result paths (arrays traversed automatically); omitted returns all fields.",
        }
    schema.setdefault("properties", {})["response_options"] = {
        "type": "object", "additionalProperties": False, "properties": properties,
        "description": "Optional synchronous response formatting; does not change execution or stored data.",
    }


def split_response_options(name: str, arguments: Any) -> tuple[Any, dict]:
    """Strip only our supported presentation argument BEFORE execution or gating."""
    if name not in SUPPORTED or not isinstance(arguments, dict) or "response_options" not in arguments:
        return arguments, {}
    options = arguments["response_options"]
    if not isinstance(options, dict):
        raise ValueError("response_options must be an object")
    allowed = {"compact", "fields"} if name in READERS else {"compact"}
    if options.keys() - allowed:
        raise ValueError(f"response_options supports only {', '.join(sorted(allowed))} for {name}")
    if "compact" in options and not isinstance(options["compact"], bool):
        raise ValueError("response_options.compact must be a boolean")
    if "fields" in options:
        fields = options["fields"]
        if (not isinstance(fields, list) or not fields
                or any(not isinstance(p, str) or not p or any(not part for part in p.split(".")) for p in fields)):
            raise ValueError("response_options.fields must be a nonempty array of dotted paths")
    run_async = arguments.get("run_async", False)
    if isinstance(run_async, str):
        run_async = run_async.lower() in ("true", "1", "yes")
    if run_async:
        raise ValueError("response_options requires a synchronous call (run_async=false)")
    return {k: v for k, v in arguments.items() if k != "response_options"}, copy.deepcopy(options)


def _project(value: Any, paths: list[list[str]]) -> Any:
    if any(not path for path in paths):
        return copy.deepcopy(value)
    if isinstance(value, list):
        return [_project(item, paths) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    branches: dict[str, list[list[str]]] = {}
    for head, *tail in paths:
        branches.setdefault(head, []).append(tail)
    return {key: _project(value[key], tails) for key, tails in branches.items() if key in value}


def result_json(result: Any, options: dict, *, project: bool = True) -> str:
    """Call after redaction and outcome bookkeeping; errors/progress bypass projection."""
    if project and options.get("fields"):
        result = _project(result, [p.split(".") for p in options["fields"]])
    if options.get("compact"):
        return json.dumps(result, separators=(",", ":"))
    return json.dumps(result, indent=2)
