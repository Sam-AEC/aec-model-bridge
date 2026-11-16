"""MCP response presentation. Read-only results are compact and size-capped; plans, proofs,
reviews, hashes and every other tool's result stay intact."""
from __future__ import annotations

import copy
import json
from typing import Any


# Measured readers, not write tools. Plans cannot use arbitrary field projection.
READERS = frozenset({
    "module_list_commands", "revit_list_elements", "revit_list_families",
    "revit_get_element_parameters", "revit_list_views",
})
SUPPORTED = READERS | {"plan_actions"}

# Read-only results longer than this many characters get their largest lists trimmed.
DEFAULT_MAX_CHARS = 20000
TRIM_HINT = "narrow with limit/offset/count_only/fields or filters"
# Tools that carry plan, proof, approval or job material. They are never compacted or trimmed,
# even where read-only. A result holding any of PLAN_KEYS gets the same treatment.
APPROVAL_TOOLS = frozenset({
    "plan_actions", "execute_plan", "list_pending_plans", "get_proof_bundle", "plan_revert",
    "approve_plan", "reject_plan", "rollback_plan",
    "job_status", "job_cancel", "revit_job_status", "revit_job_cancel", "revit_run_job", "revit_get_result",
})
PLAN_KEYS = frozenset({"plan_hash", "plan_id"})


def add_response_schema(name: str, schema: dict) -> None:
    if name not in SUPPORTED:
        return
    reader = name in READERS
    properties = {
        "compact": {"type": "boolean", "description": (
            "Minified; default true for reads, false = indented." if reader
            else "Minify response JSON; default false.")},
    }
    if reader:
        properties["max_chars"] = {
            "type": "integer", "minimum": 0,
            "description": f"Trim lists above this many chars (default {DEFAULT_MAX_CHARS}); 0 = off.",
        }
        properties["fields"] = {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "minLength": 1},
            "description": "Return only these dotted result paths (arrays traversed automatically); omitted returns all fields.",
        }
    else:
        properties["omit_action_arguments"] = {
            "type": "boolean",
            "description": "Omit echoed action arguments and identical diff.after copies from this response only. Full stored plan requires human review; default false.",
        }
    schema.setdefault("properties", {})["response_options"] = {
        "type": "object", "additionalProperties": False, "properties": properties,
        "description": "Optional synchronous response formatting; does not change execution or stored data.",
    }


def split_response_options(name: str, arguments: Any, read_only: bool = False) -> tuple[Any, dict]:
    """Strip only our supported presentation argument BEFORE execution or gating.

    Other read-only tools accept compact and max_chars without advertising them (that would
    cost tokens in every schema); any other tool's arguments pass through untouched."""
    hidden = read_only and name not in SUPPORTED and name not in APPROVAL_TOOLS
    if not (name in SUPPORTED or hidden) or not isinstance(arguments, dict) or "response_options" not in arguments:
        return arguments, {}
    options = arguments["response_options"]
    if not isinstance(options, dict):
        raise ValueError("response_options must be an object")
    if name in READERS:
        allowed = {"compact", "fields", "max_chars"}
    elif hidden:
        allowed = {"compact", "max_chars"}
    else:
        allowed = {"compact", "omit_action_arguments"}
    if options.keys() - allowed:
        raise ValueError(f"response_options supports only {', '.join(sorted(allowed))} for {name}")
    if "compact" in options and not isinstance(options["compact"], bool):
        raise ValueError("response_options.compact must be a boolean")
    if "max_chars" in options and (
            isinstance(options["max_chars"], bool) or not isinstance(options["max_chars"], int)
            or options["max_chars"] < 0):
        raise ValueError("response_options.max_chars must be an integer of 0 or more")
    if "omit_action_arguments" in options and not isinstance(options["omit_action_arguments"], bool):
        raise ValueError("response_options.omit_action_arguments must be a boolean")
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


def _omit_plan_arguments(result: Any) -> Any:
    """Summarize only a response copy; its hash still identifies the full stored plan."""
    if not isinstance(result, dict) or not isinstance(result.get("actions"), list):
        return result
    summary = copy.deepcopy(result)
    omitted = False
    for action in summary["actions"]:
        if not isinstance(action, dict) or "arguments" not in action:
            continue
        arguments = action.pop("arguments")
        action["arguments_omitted"] = True
        diff = action.get("diff")
        # Preserve actual differences if a future provider returns a distinct after-state.
        if isinstance(diff, dict) and "after" in diff and diff["after"] == arguments:
            del diff["after"]
            diff["after_omitted"] = True
        omitted = True
    if omitted:
        summary["response_note"] = (
            "Summary only: action arguments are omitted. A person must review the full stored plan "
            "in the Revit panel or approval CLI before approval. plan_hash identifies that stored plan."
        )
    return summary


def _dumps(value: Any, compact: bool) -> str:
    return json.dumps(value, separators=(",", ":")) if compact else json.dumps(value, indent=2)


def _lists(value: Any, path: tuple, found: list) -> None:
    """Collect every list reachable through dict keys (a list is a leaf)."""
    if isinstance(value, dict):
        for key, item in value.items():
            _lists(item, path + (key,), found)
    elif isinstance(value, list) and path:
        found.append((path, value))


def _replace(node: dict, path: tuple, value: Any) -> dict:
    """Copy of node with the value at path replaced; the input is not touched."""
    if len(path) == 1:
        return {**node, path[0]: value}
    return {**node, path[0]: _replace(node[path[0]], path[1:], value)}


def _marked(work: dict, trimmed: list, max_chars: int) -> dict:
    (field, total, returned), *others = trimmed
    meta = {"total": total, "returned": returned, "truncated_field": field}
    if others:
        meta["also_trimmed"] = {n: {"total": t, "returned": r} for n, t, r in others}
    meta["hint"] = f"Trimmed to fit {max_chars} characters; {TRIM_HINT}."
    out = dict(work)
    if meta.keys() & out.keys():  # never overwrite a provider's own total/hint
        out["truncation"] = meta
    else:
        out.update(meta)
    out["truncated"] = True
    return out


def _cap(result: Any, max_chars: int, compact: bool) -> Any:
    """Trim the largest lists until the JSON fits max_chars. Returns the input itself when it
    already fits, or when trimming lists cannot make it fit."""
    if max_chars <= 0 or len(_dumps(result, compact)) <= max_chars:
        return result
    work = {"items": result} if isinstance(result, list) else result
    if not isinstance(work, dict):
        return result
    found: list = []
    _lists(work, (), found)
    found.sort(key=lambda entry: len(_dumps(entry[1], compact)), reverse=True)
    trimmed: list[tuple[str, int, int]] = []
    for path, items in found:
        label, total = ".".join(path), len(items)

        def fits(keep: int) -> bool:
            trial = _marked(_replace(work, path, items[:keep]), trimmed + [(label, total, keep)], max_chars)
            return len(_dumps(trial, compact)) <= max_chars

        lo, hi = 0, total - 1  # most items that still fit, markers included
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if fits(mid) else (lo, mid - 1)
        work = _replace(work, path, items[:lo])
        trimmed.append((label, total, lo))
        out = _marked(work, trimmed, max_chars)
        if len(_dumps(out, compact)) <= max_chars:
            return out
    return result


def result_json(result: Any, options: dict, *, project: bool = True, read_only: bool = False) -> str:
    """Call after redaction and outcome bookkeeping; errors/progress bypass projection.

    read_only (a read-only tool that is not an approval tool) makes compact the default and
    caps the size. project=False (errors, progress) and plan material skip both."""
    read_only = read_only and project and not (isinstance(result, dict) and PLAN_KEYS & result.keys())
    if project and options.get("omit_action_arguments"):
        result = _omit_plan_arguments(result)
    if project and options.get("fields"):
        result = _project(result, [p.split(".") for p in options["fields"]])
    compact = bool(options.get("compact", read_only))
    if read_only:
        result = _cap(result, options.get("max_chars", DEFAULT_MAX_CHARS), compact)
    return _dumps(result, compact)
