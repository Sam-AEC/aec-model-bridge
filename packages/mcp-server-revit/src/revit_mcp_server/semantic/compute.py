"""Read-only query pipelines over a saved snapshot (`snapshot_compute`).

A pipeline is a short list of named steps. Each step reads rows from the
snapshot or from an earlier step, then filters, joins, groups, sorts and
projects them. Only the requested step comes back to the model, so a check
that would take dozens of tool calls runs as one call and returns the answer.

The pipeline is data, not code: no expressions are evaluated, no regular
expressions run, every list is bounded, and unknown keys are refused. It never
touches Revit and never writes.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Optional

from revit_mcp_server.semantic.models import Snapshot

MAX_STEPS = 12
MAX_CLAUSES = 50
MAX_DEPTH = 6
DEFAULT_ROWS = 100
MAX_ROWS = 1000
MAX_LIST_ITEMS = 50
MAX_TEXT = 500

SOURCES = ("elements", "types", "relations")
JOINS = ("type", "host", "level", "room", "group", "hosted", "relation_out", "relation_in")
OPS = (
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "nin",
    "contains", "startswith", "endswith", "exists", "empty",
)
AGGREGATES = ("count", "sum", "avg", "min", "max", "distinct", "list")
STEP_KEYS = {"name", "from", "where", "join", "group_by", "aggregate", "select", "sort", "limit"}


class QueryError(ValueError):
    """A pipeline is malformed. The message says what to change."""


def _fail(step: str, message: str) -> None:
    raise QueryError(f"step '{step}': {message}")


# ---------------------------------------------------------------- field paths


def get_path(row: Any, path: str) -> Any:
    """Read a dotted path. A parameter record yields its value (`params.Mark` -> 'D-101')."""
    current = row
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    if isinstance(current, dict) and "v" in current and "storage" in current:
        return current["v"]
    return current


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _text(value: Any, ci: bool) -> str:
    text = "" if value is None else str(value)
    return text.lower() if ci else text


def _equal(a: Any, b: Any, ci: bool) -> bool:
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None:
        return na == nb
    if a is None or b is None:
        return a is None and b is None
    return _text(a, ci) == _text(b, ci)


def _compare(op: str, a: Any, b: Any) -> bool:
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None:
        left, right = na, nb
    elif isinstance(a, str) and isinstance(b, str):
        left, right = a, b
    else:
        return False
    return {
        "gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right,
    }[op]


# --------------------------------------------------------------------- where


def _compile_where(step: str, clause: Any, depth: int = 0) -> Callable[[Dict[str, Any]], bool]:
    if depth > MAX_DEPTH:
        _fail(step, f"where nests deeper than {MAX_DEPTH} levels")
    if isinstance(clause, list):
        return _compile_where(step, {"all": clause}, depth)
    if not isinstance(clause, dict):
        _fail(step, "a where clause is an object or a list of objects")
    for key in ("all", "any"):
        if key in clause:
            if set(clause) != {key} or not isinstance(clause[key], list):
                _fail(step, f"'{key}' takes a list of clauses and nothing else")
            if len(clause[key]) > MAX_CLAUSES:
                _fail(step, f"'{key}' has more than {MAX_CLAUSES} clauses")
            parts = [_compile_where(step, c, depth + 1) for c in clause[key]]
            if key == "all":
                return lambda row: all(p(row) for p in parts)
            return lambda row: any(p(row) for p in parts)
    if "not" in clause:
        if set(clause) != {"not"}:
            _fail(step, "'not' takes one clause and nothing else")
        inner = _compile_where(step, clause["not"], depth + 1)
        return lambda row: not inner(row)

    unknown = set(clause) - {"field", "op", "value", "ci"}
    if unknown:
        _fail(step, f"unknown where keys {sorted(unknown)}; use field, op, value, ci")
    field = clause.get("field")
    if not isinstance(field, str) or not field:
        _fail(step, "a where clause needs 'field', a dotted path such as 'params.Fire Rating'")
    op = clause.get("op", "eq")
    if op not in OPS:
        _fail(step, f"unknown op '{op}'; use one of {', '.join(OPS)}")
    ci = bool(clause.get("ci", False))
    raw = clause.get("value")
    if op in ("in", "nin"):
        if not isinstance(raw, list) or len(raw) > MAX_LIST_ITEMS * 4:
            _fail(step, f"'{op}' takes a list of at most {MAX_LIST_ITEMS * 4} values")
    elif op not in ("exists", "empty") and "value" not in clause:
        _fail(step, f"op '{op}' needs a value")
    if isinstance(raw, str) and len(raw) > MAX_TEXT:
        _fail(step, f"values are limited to {MAX_TEXT} characters")

    # {"field": "other.path"} compares two fields of the same row.
    if isinstance(raw, dict):
        if set(raw) != {"field"} or not isinstance(raw["field"], str):
            _fail(step, "an object value must be {\"field\": \"path\"}")
        other = raw["field"]

        def resolve(row: Dict[str, Any]) -> Any:
            return get_path(row, other)
    else:
        def resolve(row: Dict[str, Any]) -> Any:
            return raw

    def test(row: Dict[str, Any]) -> bool:
        actual = get_path(row, field)
        if op == "exists":
            return (actual is not None) == (raw is not False)
        if op == "empty":
            is_empty = actual is None or actual == "" or actual == [] or actual == {}
            return is_empty == (raw is not False)
        expected = resolve(row)
        if op == "eq":
            return _equal(actual, expected, ci)
        if op == "ne":
            return not _equal(actual, expected, ci)
        if op in ("in", "nin"):
            hit = any(_equal(actual, item, ci) for item in expected)
            return hit if op == "in" else not hit
        if op in ("gt", "gte", "lt", "lte"):
            return _compare(op, actual, expected)
        if actual is None:
            return False
        if isinstance(actual, list):
            return op == "contains" and any(_equal(item, expected, ci) for item in actual)
        haystack, needle = _text(actual, ci), _text(expected, ci)
        if op == "contains":
            return needle in haystack
        if op == "startswith":
            return haystack.startswith(needle)
        return haystack.endswith(needle)

    return test


# ---------------------------------------------------------------------- data


class _Index:
    def __init__(self, snapshot: Snapshot) -> None:
        self.elements = [el.model_dump(by_alias=True, mode="json") for el in snapshot.elements]
        self.types = [t.model_dump(by_alias=True, mode="json") for t in snapshot.types]
        self.relations = [r.model_dump(by_alias=True, mode="json") for r in snapshot.relations]
        self.by_uid = {row["uid"]: row for row in self.elements}
        self.type_by_uid = {row["uid"]: row for row in self.types}
        self.hosted: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.elements:
            if row.get("host_uid"):
                self.hosted.setdefault(row["host_uid"], []).append(row)
        self.rel_out: Dict[str, List[Dict[str, Any]]] = {}
        self.rel_in: Dict[str, List[Dict[str, Any]]] = {}
        for rel in self.relations:
            self.rel_out.setdefault(rel["from"], []).append(rel)
            self.rel_in.setdefault(rel["to"], []).append(rel)


def _join(step: str, rows: List[Dict[str, Any]], spec: Any, index: _Index) -> List[Dict[str, Any]]:
    if isinstance(spec, str):
        spec = {"rel": spec}
    if not isinstance(spec, dict) or set(spec) - {"rel", "as", "kind"}:
        _fail(step, "a join is a name such as 'type' or {\"rel\": ..., \"as\": ..., \"kind\": ...}")
    rel = spec.get("rel")
    if rel not in JOINS:
        _fail(step, f"unknown join '{rel}'; use one of {', '.join(JOINS)}")
    alias = spec.get("as", rel)
    if not isinstance(alias, str) or not alias or "." in alias:
        _fail(step, "'as' is a plain name without dots")
    kind = spec.get("kind")

    def related(row: Dict[str, Any]) -> Any:
        if rel == "type":
            return index.type_by_uid.get(row.get("type_uid") or "")
        if rel == "host":
            return index.by_uid.get(row.get("host_uid") or "")
        if rel == "level":
            return index.by_uid.get(row.get("level_uid") or "")
        if rel == "group":
            return index.by_uid.get(row.get("group_uid") or "")
        if rel == "room":
            rooms = row.get("room_uids") or {}
            first = next(iter(rooms.values()), None) if isinstance(rooms, dict) else None
            return index.by_uid.get(first or "")
        if rel == "hosted":
            return index.hosted.get(row.get("uid") or "", [])[:MAX_LIST_ITEMS]
        source = index.rel_out if rel == "relation_out" else index.rel_in
        end = "to" if rel == "relation_out" else "from"
        found = [
            index.by_uid.get(r[end]) for r in source.get(row.get("uid") or "", [])
            if kind is None or r["kind"] == kind
        ]
        return [f for f in found if f is not None][:MAX_LIST_ITEMS]

    return [{**row, alias: related(row)} for row in rows]


def _aggregate(step: str, rows: List[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for alias, agg in spec.items():
        if isinstance(agg, str):
            agg = {"op": agg}
        if not isinstance(agg, dict) or set(agg) - {"op", "field"}:
            _fail(step, f"aggregate '{alias}' is {{\"op\": ..., \"field\": ...}}")
        op, field = agg.get("op"), agg.get("field")
        if op not in AGGREGATES:
            _fail(step, f"unknown aggregate '{op}'; use one of {', '.join(AGGREGATES)}")
        if op == "count" and field is None:
            out[alias] = len(rows)
            continue
        if not isinstance(field, str):
            _fail(step, f"aggregate '{alias}' needs a field")
        values = [get_path(r, field) for r in rows]
        present = [v for v in values if v is not None]
        if op == "count":
            out[alias] = len(present)
        elif op in ("distinct", "list"):
            items = present
            if op == "distinct":
                seen: Dict[str, Any] = {}
                for v in present:
                    seen.setdefault(repr(v), v)
                items = list(seen.values())
            out[alias] = items[:MAX_LIST_ITEMS]
            if len(items) > MAX_LIST_ITEMS:
                out[f"{alias}_truncated"] = len(items)
        else:
            numbers = [n for n in (_number(v) for v in present) if n is not None]
            if not numbers:
                out[alias] = None
            elif op == "sum":
                out[alias] = sum(numbers)
            elif op == "avg":
                out[alias] = sum(numbers) / len(numbers)
            elif op == "min":
                out[alias] = min(numbers)
            else:
                out[alias] = max(numbers)
    return out


def _group(step: str, rows: List[Dict[str, Any]], keys: List[str], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        key = tuple(repr(get_path(row, k)) for k in keys)
        groups.setdefault(key, []).append(row)
    result = []
    for members in groups.values():
        head = {k: get_path(members[0], k) for k in keys}
        result.append({**head, **_aggregate(step, members, spec or {"count": "count"})})
    return result


def _select(step: str, rows: Iterable[Dict[str, Any]], fields: List[Any]) -> List[Dict[str, Any]]:
    plan = []
    for item in fields:
        if isinstance(item, str):
            plan.append((item, item))
        elif isinstance(item, dict) and set(item) == {"field", "as"}:
            plan.append((item["as"], item["field"]))
        else:
            _fail(step, "select items are paths or {\"field\": path, \"as\": name}")
    return [{name: get_path(row, path) for name, path in plan} for row in rows]


def _sort_key(value: Any) -> tuple:
    number = _number(value)
    if value is None:
        return (2, 0, "")
    if number is not None:
        return (0, number, "")
    return (1, 0, str(value))


# ---------------------------------------------------------------------- main


def run_pipeline(
    snapshot: Snapshot,
    steps: List[Dict[str, Any]],
    return_step: Optional[str] = None,
    max_rows: int = DEFAULT_ROWS,
) -> Dict[str, Any]:
    if not isinstance(steps, list) or not steps:
        raise QueryError("steps is a non-empty list")
    if len(steps) > MAX_STEPS:
        raise QueryError(f"at most {MAX_STEPS} steps")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_ROWS:
        raise QueryError(f"max_rows is between 1 and {MAX_ROWS}")

    index = _Index(snapshot)
    results: Dict[str, List[Dict[str, Any]]] = {}
    counts: Dict[str, int] = {}
    order: List[str] = []

    for position, step in enumerate(steps):
        if not isinstance(step, dict):
            raise QueryError(f"step {position + 1} is not an object")
        name = step.get("name") or f"step{position + 1}"
        if not isinstance(name, str) or name in results or name in SOURCES:
            raise QueryError(f"step {position + 1}: name must be a new name, not a source")
        unknown = set(step) - STEP_KEYS
        if unknown:
            _fail(name, f"unknown keys {sorted(unknown)}; use {', '.join(sorted(STEP_KEYS))}")

        source = step.get("from", "elements")
        if source in SOURCES:
            rows = list(getattr(index, source))
        elif isinstance(source, str) and source.startswith("$") and source[1:] in results:
            rows = list(results[source[1:]])
        else:
            _fail(name, f"'from' is one of {', '.join(SOURCES)} or $<earlier step>, not {source!r}")

        joins = step.get("join", [])
        if not isinstance(joins, list):
            joins = [joins]
        for spec in joins:
            rows = _join(name, rows, spec, index)

        if "where" in step:
            predicate = _compile_where(name, step["where"])
            rows = [row for row in rows if predicate(row)]

        if "group_by" in step or "aggregate" in step:
            keys = step.get("group_by", [])
            if isinstance(keys, str):
                keys = [keys]
            spec = step.get("aggregate", {})
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                _fail(name, "group_by is a path or a list of paths")
            if not isinstance(spec, dict):
                _fail(name, "aggregate is an object of name -> {op, field}")
            rows = _group(name, rows, keys, spec) if keys else [_aggregate(name, rows, spec or {"count": "count"})]

        sort = step.get("sort", [])
        if isinstance(sort, (str, dict)):
            sort = [sort]
        for item in reversed(sort):
            if isinstance(item, str):
                path, desc = item, False
            elif isinstance(item, dict) and not set(item) - {"field", "desc"}:
                path, desc = item.get("field"), bool(item.get("desc"))
            else:
                path, desc = None, False
            if not isinstance(path, str):
                _fail(name, "sort items are paths or {\"field\": path, \"desc\": true}")
            rows.sort(key=lambda r, p=path: _sort_key(get_path(r, p)), reverse=desc)

        if "select" in step:
            fields = step["select"]
            if not isinstance(fields, list) or not fields:
                _fail(name, "select is a non-empty list")
            rows = _select(name, rows, fields)

        if "limit" in step:
            limit = step["limit"]
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                _fail(name, "limit is a whole number")
            rows = rows[:limit]

        results[name] = rows
        counts[name] = len(rows)
        order.append(name)

    target = return_step or order[-1]
    if target not in results:
        raise QueryError(f"return names no step; steps are {', '.join(order)}")
    rows = results[target]
    return {
        "snapshot_id": snapshot.snapshot_id,
        "returned_step": target,
        "row_count": len(rows),
        "rows": rows[:max_rows],
        "truncated": len(rows) > max_rows,
        "step_counts": counts,
        "partial_snapshot": bool(snapshot.counts.get("truncated") or snapshot.counts.get("params")),
    }
