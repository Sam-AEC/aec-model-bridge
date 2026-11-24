"""MCP response presentation. Read-only results are compact and size-capped; plans, proofs,
reviews, hashes and every other tool's result stay intact."""
from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

from . import read_cursor
from .read_cursor import STORE, Context, make_cursor

log = logging.getLogger(__name__)


# Measured readers, not write tools. Plans cannot use arbitrary field projection.
READERS = frozenset({
    "module_list_commands", "revit_list_elements", "revit_list_families",
    "revit_get_element_parameters", "revit_list_views",
})
SUPPORTED = READERS | {"plan_actions"}

# Read-only results longer than this many characters get their largest lists trimmed.
# MCP_REVIT_READ_MAX_CHARS overrides it for the server, response_options.max_chars per call.
DEFAULT_MAX_CHARS = 20000
TRIM_HINT = "narrow with limit/offset/count_only/fields or filters"
# Tools that carry plan, proof, approval or job material. They are never compacted or trimmed,
# even where read-only, as is any tool with a 'plan' word in its name and recipe_get
# (see tool_metadata.is_read_only_tool). A result holding any top-level PLAN_KEYS gets the same treatment.
APPROVAL_TOOLS = frozenset({
    "plan_actions", "execute_plan", "list_pending_plans", "get_proof_bundle", "plan_revert", "policy_show",
    "approve_plan", "reject_plan", "rollback_plan",
    "job_status", "job_cancel", "revit_job_status", "revit_job_cancel", "revit_run_job", "revit_get_result",
})
PLAN_KEYS = frozenset({"plan_hash", "plan_id", "plan_type", "plan_arguments"})


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
        properties["cursor"] = {
            "type": "string", "maxLength": 64,
            "description": "From a truncated answer: next part. Repeat the same arguments.",
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
        allowed = {"compact", "cursor", "fields", "max_chars"}
    elif hidden:
        allowed = {"compact", "cursor", "max_chars"}
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
    if "cursor" in options and (not isinstance(options["cursor"], str) or not 0 < len(options["cursor"]) <= 64):
        raise ValueError("response_options.cursor must be the cursor string from a truncated answer")
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
        # The preview echoes the arguments, so a summary leaves it out; blast_radius stays.
        summary.pop("preview", None)
        summary.pop("preview_markdown", None)
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


def _follow(kind: str, value: Any = None) -> dict:
    """Markers that tell the client how to get the rest. 'reserve' is the longest variant;
    sizing uses it so the real markers always fit inside max_chars."""
    if kind == "cursor":
        return {"cursor": value, "next": NEXT_CURSOR}
    if kind == "resource_uri":
        return {"resource_uri": value, "next": NEXT_SAVED}
    return {"cursor": read_cursor.PLACEHOLDER_CURSOR, "resource_uri": read_cursor.PLACEHOLDER_URI,
            "next": max(NEXT_CURSOR, NEXT_SAVED, key=len)}


NEXT_CURSOR = "repeat the call with response_options.cursor for the next part"
NEXT_SAVED = "the full result is saved; read resource_uri"


def _marked(work: dict, trimmed: list, max_chars: int, follow: Optional[dict] = None) -> dict:
    (field, total, returned), *others = trimmed
    meta = {"total": total, "returned": returned, "truncated_field": field}
    if others:
        meta["also_trimmed"] = {n: {"total": t, "returned": r} for n, t, r in others}
    meta["hint"] = f"Trimmed to fit {max_chars} characters; {TRIM_HINT}."
    meta.update(follow or {})
    out = dict(work)
    if meta.keys() & out.keys():  # never overwrite a provider's own total/hint/cursor
        out["truncation"] = meta
    else:
        out.update(meta)
    out["truncated"] = True
    return out


def _trim(result: Any, max_chars: int, compact: bool, reserve: bool = False):
    """Trim the largest lists until the JSON fits max_chars.

    Returns (work, trimmed, first) where first is (path, full items) of the first list cut, or
    None when the result already fits or trimming lists cannot make it fit. reserve=True leaves
    room for a cursor or resource_uri."""
    if max_chars <= 0 or len(_dumps(result, compact)) <= max_chars:
        return None
    work = {"items": result} if isinstance(result, list) else result
    if not isinstance(work, dict):
        return None
    extra = _follow("reserve") if reserve else None
    found: list = []
    _lists(work, (), found)
    found.sort(key=lambda entry: len(_dumps(entry[1], compact)), reverse=True)
    trimmed: list[tuple[str, int, int]] = []
    first = None
    for path, items in found:
        label, total = ".".join(path), len(items)

        def fits(keep: int) -> bool:
            trial = _marked(_replace(work, path, items[:keep]), trimmed + [(label, total, keep)], max_chars, extra)
            return len(_dumps(trial, compact)) <= max_chars

        lo, hi = 0, total - 1  # most items that still fit, markers included
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if fits(mid) else (lo, mid - 1)
        work = _replace(work, path, items[:lo])
        trimmed.append((label, total, lo))
        first = first or (path, items)
        if len(_dumps(_marked(work, trimmed, max_chars, extra), compact)) <= max_chars:
            return work, trimmed, first
    return None


def _cap(result: Any, max_chars: int, compact: bool, ctx: Optional[Context] = None) -> Any:
    """Trimmed copy with markers, or the input itself when it fits or cannot be made to fit.

    With ctx, the full first list cut is kept for a cursor, or, when too large to keep in
    memory, the whole result is saved under the workspace and linked."""
    cut = _trim(result, max_chars, compact, reserve=ctx is not None)
    if cut is None:
        return result
    work, trimmed, (path, items) = cut
    follow = None
    if ctx is not None:
        chars = len(_dumps(items, True))
        if chars <= read_cursor.MAX_ENTRY_CHARS:
            key = STORE.put(ctx, path, items, chars)
            follow = _follow("cursor", make_cursor(key, trimmed[0][2]))
        elif ctx.workspace is not None:
            try:
                ctx.resource_uri = read_cursor.save_result(ctx.workspace, result)
                follow = _follow("resource_uri", ctx.resource_uri)
            except (OSError, ValueError) as exc:
                log.warning("Could not save a large read result: %s", exc)
    return _marked(work, trimmed, max_chars, follow)


def _max_chars(options: dict) -> int:
    return options.get("max_chars", read_cursor.default_max_chars(DEFAULT_MAX_CHARS))


def _nest(path: tuple, value: Any) -> dict:
    return {path[0]: value} if len(path) == 1 else {path[0]: _nest(path[1:], value)}


def next_page(options: dict, ctx: Context) -> str:
    """The next part of a list a cursor points at, from memory; the tool is not run again.

    Raises read_cursor.CursorError for a malformed, unknown, expired or mismatched cursor."""
    entry, offset, key = STORE.get(options.get("cursor"), ctx.tool, ctx.binding)
    compact = bool(options.get("compact", True))
    max_chars = _max_chars(options)
    items, total, label = entry.items, len(entry.items), ".".join(entry.path)

    def build(keep: int) -> dict:
        end = offset + keep
        meta: dict = {"truncated": end < total, "total": total, "offset": offset, "returned": keep,
                      "truncated_field": label}
        if end < total:
            meta.update(_follow("cursor", make_cursor(key, end)))
        body = _nest(entry.path, items[offset:end])
        return {**body, "page": meta} if entry.path[0] in meta else {**body, **meta}

    remaining = total - offset
    keep = remaining
    if max_chars > 0 and remaining > 1 and len(_dumps(build(remaining), compact)) > max_chars:
        lo, hi = 1, remaining - 1  # at least one item per part, so paging always ends
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if len(_dumps(build(mid), compact)) <= max_chars else (lo, mid - 1)
        keep = lo
    return _dumps(build(keep), compact)


def result_json(result: Any, options: dict, *, project: bool = True, read_only: bool = False,
                cursor: Optional[Context] = None) -> str:
    """Call after redaction and outcome bookkeeping; errors/progress bypass projection.

    read_only (a read-only tool that is not an approval tool) makes compact the default and
    caps the size. project=False (errors, progress) and plan material skip both. cursor, when
    given, lets a trimmed answer carry a cursor or a saved-result link."""
    read_only = read_only and project and not (isinstance(result, dict) and PLAN_KEYS & result.keys())
    if project and options.get("omit_action_arguments"):
        result = _omit_plan_arguments(result)
    if project and options.get("fields"):
        result = _project(result, [p.split(".") for p in options["fields"]])
    compact = bool(options.get("compact", read_only))
    if read_only:
        result = _cap(result, _max_chars(options), compact, cursor)
    return _dumps(result, compact)
