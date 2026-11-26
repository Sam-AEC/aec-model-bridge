"""Read-only query pipelines over a saved snapshot (`snapshot_compute`).

A pipeline is a short list of named steps. Each step reads rows from the
snapshot or from an earlier step, then filters, joins, groups, sorts and
projects them. Only the requested step comes back to the model, so a check
that would take dozens of tool calls runs as one call and returns the answer.

The pipeline is data, not code: no expressions are evaluated, no regular
expressions run, every list is bounded, and unknown keys are refused. It never
touches Revit and never writes.

A pipeline can also come from a saved query (`resolve_query`), read elements of
other saved snapshots (`from: "link:<snapshot_id>"`) and match rows by bounding
box against an earlier step (`spatial`).
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

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
STEP_KEYS = {"name", "from", "where", "join", "spatial", "group_by", "aggregate", "select", "sort", "limit"}

LINK_PREFIX = "link:"
MAX_LINKS = 4
SPATIAL_TESTS = ("overlaps", "contains", "within", "within_distance")
SPATIAL_KEYS = {"with", "test", "distance", "as"}
MAX_PAIRS = 250_000
MAX_DISTANCE = 1000.0

QUERY_KEYS = {"steps", "return", "description", "params"}
MAX_PARAMS = 20
MAX_QUERY_DEPTH = 32
# A fixed pattern for parameter names; nothing from the caller is compiled.
PARAM_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class QueryError(ValueError):
    """A pipeline is malformed. The message says what to change."""


def _fail(step: str, message: str) -> None:
    raise QueryError(f"step '{step}': {message}")


# ---------------------------------------------------------------- field paths


def get_path(row: Any, path: str) -> Any:
    """Read a dotted path. A parameter record yields its value (`params.Mark` -> 'D-101')."""
    current = row
    if isinstance(current, dict) and path in current:
        current = current[path]
        return current["v"] if isinstance(current, dict) and "v" in current and "storage" in current else current
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


def _records(source: Any, key: str) -> List[Dict[str, Any]]:
    if isinstance(source, Snapshot):
        return [item.model_dump(by_alias=True, mode="json") for item in getattr(source, key)]
    items = source.get(key) if isinstance(source, Mapping) else None
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _snapshot_attr(source: Any, key: str) -> Any:
    if isinstance(source, Snapshot):
        return getattr(source, key, None)
    return source.get(key) if isinstance(source, Mapping) else None


class _Index:
    """Rows and lookups for one snapshot: a Snapshot or its saved JSON as a dict.

    Rows of a linked snapshot carry `_snapshot_id` (the tag).
    """

    def __init__(self, snapshot: Any, tag: Optional[str] = None) -> None:
        self.elements = _records(snapshot, "elements")
        if tag is not None:
            self.elements = [{**row, "_snapshot_id": tag} for row in self.elements]
        self.types = _records(snapshot, "types")
        self.relations = _records(snapshot, "relations")
        self.by_uid = {row["uid"]: row for row in self.elements if row.get("uid")}
        self.by_element_id = {
            str(row["element_id"]): row for row in self.elements if row.get("element_id") is not None
        }
        self.type_by_uid = {row["uid"]: row for row in self.types if row.get("uid")}
        self.hosted: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.elements:
            if row.get("host_uid"):
                self.hosted.setdefault(row["host_uid"], []).append(row)
        self.rel_out: Dict[str, List[Dict[str, Any]]] = {}
        self.rel_in: Dict[str, List[Dict[str, Any]]] = {}
        for rel in self.relations:
            self.rel_out.setdefault(rel.get("from"), []).append(rel)
            self.rel_in.setdefault(rel.get("to"), []).append(rel)
        counts = _snapshot_attr(snapshot, "counts")
        self.partial = isinstance(counts, Mapping) and bool(counts.get("truncated") or counts.get("params"))


def _join(
    step: str, rows: List[Dict[str, Any]], spec: Any, index_for: Callable[[Dict[str, Any]], _Index],
) -> List[Dict[str, Any]]:
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
        index = index_for(row)
        if rel == "type":
            return index.type_by_uid.get(row.get("type_uid") or "")
        if rel == "host":
            return index.by_uid.get(row.get("host_uid") or "")
        if rel == "level":
            ref = row.get("level_uid") or ""
            return index.by_uid.get(ref) or index.by_element_id.get(str(ref))
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
            index.by_uid.get(r.get(end) or "") for r in source.get(row.get("uid") or "", [])
            if kind is None or r.get("kind") == kind
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


# ------------------------------------------------------------------- spatial


Box = Tuple[Tuple[float, ...], Tuple[float, ...]]


def _coord(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _bbox(row: Any) -> Optional[Box]:
    """The row's bounding box, or None when it is missing or malformed."""
    box = row.get("bbox") if isinstance(row, dict) else None
    if not isinstance(box, dict):
        return None
    lo, hi = box.get("min"), box.get("max")
    if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) == 3 and len(hi) == 3):
        return None
    low = tuple(_coord(v) for v in lo)
    high = tuple(_coord(v) for v in hi)
    if any(v is None for v in low + high) or any(a > b for a, b in zip(low, high)):
        return None
    return low, high  # type: ignore[return-value]


def _overlaps(a: Box, b: Box) -> bool:
    return all(a[0][i] <= b[1][i] and b[0][i] <= a[1][i] for i in range(3))


def _contains(a: Box, b: Box) -> bool:
    return all(a[0][i] <= b[0][i] and b[1][i] <= a[1][i] for i in range(3))


def _gap(a: Box, b: Box) -> float:
    return math.sqrt(sum(max(0.0, b[0][i] - a[1][i], a[0][i] - b[1][i]) ** 2 for i in range(3)))


def _spatial(
    step: str, rows: List[Dict[str, Any]], spec: Any, results: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Add the rows of an earlier step whose bounding boxes pass the test."""
    if not isinstance(spec, dict) or set(spec) - SPATIAL_KEYS:
        _fail(step, "spatial is {\"with\": \"$step\", \"test\": ..., \"distance\": feet, \"as\": name}")
    other = spec.get("with")
    if not (isinstance(other, str) and other.startswith("$") and other[1:] in results):
        _fail(step, f"spatial 'with' names an earlier step as $name, not {other!r}")
    test = spec.get("test")
    if test not in SPATIAL_TESTS:
        _fail(step, f"unknown spatial test {test!r}; use one of {', '.join(SPATIAL_TESTS)}")
    distance = 0.0
    if test == "within_distance":
        value = _coord(spec.get("distance"))
        if value is None or not 0 <= value <= MAX_DISTANCE:
            _fail(step, f"within_distance needs 'distance', a number of feet from 0 to {MAX_DISTANCE:g}")
        distance = float(value)  # type: ignore[arg-type]
    elif "distance" in spec:
        _fail(step, "'distance' is only used with the within_distance test")
    alias = spec.get("as", other[1:])
    if not isinstance(alias, str) or not alias or "." in alias:
        _fail(step, "spatial 'as' is a plain name without dots")

    candidates = []
    for cand in results[other[1:]]:
        cbox = _bbox(cand)
        if cbox is not None:
            candidates.append((cand, cbox))
    boxed = [(row, _bbox(row)) for row in rows]
    pairs = sum(1 for _, box in boxed if box is not None) * len(candidates)
    if pairs > MAX_PAIRS:
        _fail(step, (
            f"spatial would compare {pairs} pairs, more than {MAX_PAIRS}; "
            "narrow this step's rows or the 'with' step with where in an earlier step"
        ))

    def hit(a: Box, b: Box) -> bool:
        if test == "overlaps":
            return _overlaps(a, b)
        if test == "contains":
            return _contains(a, b)
        if test == "within":
            return _contains(b, a)
        return _gap(a, b) <= distance

    out = []
    for row, box in boxed:
        matches: List[Dict[str, Any]] = []
        if box is not None:
            me = (row.get("_snapshot_id"), row.get("uid"))
            for cand, cbox in candidates:
                if me[1] is not None and (cand.get("_snapshot_id"), cand.get("uid")) == me:
                    continue  # an element never matches itself
                if hit(box, cbox):
                    matches.append(cand)
        out.append({**row, alias: matches[:MAX_LIST_ITEMS], f"{alias}_count": len(matches)})
    return out


# ------------------------------------------------------------- saved queries


def resolve_query(name: str, document: Any, params: Any = None) -> Dict[str, Any]:
    """Turn a saved query document into {"steps", "return"} with params put in.

    A param replaces a whole JSON value written {"$param": "name"}; text is never
    templated. run_pipeline then checks the steps exactly like inline steps.
    """
    where = f"saved query '{name}'"
    if isinstance(document, list):
        document = {"steps": document}
    if not isinstance(document, dict):
        raise QueryError(f"{where}: the file holds a JSON object with 'steps'")
    unknown = set(document) - QUERY_KEYS
    if unknown:
        raise QueryError(f"{where}: unknown keys {sorted(unknown)}; use {', '.join(sorted(QUERY_KEYS))}")
    if "description" in document and not isinstance(document["description"], str):
        raise QueryError(f"{where}: description is text")
    returned = document.get("return")
    if returned is not None and not isinstance(returned, str):
        raise QueryError(f"{where}: return is a step name")
    defaults = document.get("params", {})
    if params is None:
        params = {}
    for label, mapping in (("params in the file", defaults), ("params", params)):
        if not isinstance(mapping, dict):
            raise QueryError(f"{where}: {label} is an object of name -> JSON value")
        if len(mapping) > MAX_PARAMS:
            raise QueryError(f"{where}: at most {MAX_PARAMS} params")
        bad = [k for k in mapping if not (isinstance(k, str) and PARAM_NAME_RE.fullmatch(k))]
        if bad:
            raise QueryError(f"{where}: param names are letters, digits and '_', not {bad[0]!r}")
    values = {**defaults, **params}
    used: set = set()

    def substitute(node: Any, depth: int) -> Any:
        if depth > MAX_QUERY_DEPTH:
            raise QueryError(f"{where}: nests deeper than {MAX_QUERY_DEPTH} levels")
        if isinstance(node, dict):
            if "$param" in node:
                pname = node["$param"]
                if set(node) != {"$param"} or not isinstance(pname, str):
                    raise QueryError(f"{where}: {{\"$param\": name}} takes one name and nothing else")
                if pname not in values:
                    raise QueryError(f"{where} needs param '{pname}'")
                used.add(pname)
                return copy.deepcopy(values[pname])  # the value is not searched for more $param
            return {key: substitute(value, depth + 1) for key, value in node.items()}
        if isinstance(node, list):
            return [substitute(value, depth + 1) for value in node]
        return node

    steps = substitute(document.get("steps"), 0)
    unused = set(params) - used
    if unused:
        raise QueryError(f"{where} does not use params {sorted(unused)}")
    return {"steps": steps, "return": returned}


# ---------------------------------------------------------------------- main


def run_pipeline(
    snapshot: Any,
    steps: List[Dict[str, Any]],
    return_step: Optional[str] = None,
    max_rows: int = DEFAULT_ROWS,
    load_snapshot: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Run steps over a Snapshot (or its saved JSON as a dict).

    `load_snapshot(snapshot_id)` returns another saved snapshot for `from: "link:<id>"`
    or raises QueryError. Without it, link sources are refused.
    """
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_ROWS:
        raise QueryError(f"max_rows is between 1 and {MAX_ROWS}")
    target, rows, counts, partial, linked = _execute(snapshot, steps, return_step, load_snapshot)
    out = {
        "snapshot_id": _snapshot_attr(snapshot, "snapshot_id"),
        "returned_step": target,
        "row_count": len(rows),
        "rows": rows[:max_rows],
        "truncated": len(rows) > max_rows,
        "step_counts": counts,
        "partial_snapshot": partial,
    }
    if linked:
        out["linked_snapshots"] = linked
    return out


def pipeline_rows(snapshot: Any, steps: Any, return_step: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every row of the result step, without the max_rows cap (for the QA/QC checker)."""
    return _execute(snapshot, steps, return_step, None)[1]


def validate_steps(steps: Any) -> None:
    """Check a pipeline's shape without a model: run it over an empty snapshot.

    Raises QueryError like run_pipeline. Link sources are refused, because there is
    no loader here.
    """
    _execute({"snapshot_id": "", "elements": [], "types": [], "relations": []}, steps, None, None)


def _execute(
    snapshot: Any,
    steps: Any,
    return_step: Optional[str],
    load_snapshot: Optional[Callable[[str], Any]],
) -> Tuple[str, List[Dict[str, Any]], Dict[str, int], bool, List[str]]:
    if not isinstance(steps, list) or not steps:
        raise QueryError("steps is a non-empty list")
    if len(steps) > MAX_STEPS:
        raise QueryError(f"at most {MAX_STEPS} steps")

    index = _Index(snapshot)
    links: Dict[str, _Index] = {}
    results: Dict[str, List[Dict[str, Any]]] = {}
    counts: Dict[str, int] = {}
    order: List[str] = []

    def index_for(row: Dict[str, Any]) -> _Index:
        tag = row.get("_snapshot_id")
        return links.get(tag, index) if isinstance(tag, str) else index

    def link_rows(step_name: str, snapshot_id: str) -> List[Dict[str, Any]]:
        if load_snapshot is None:
            _fail(step_name, "link sources are not available here")
        if not snapshot_id:
            _fail(step_name, "'from' link names a snapshot: link:<snapshot_id>")
        if snapshot_id not in links:
            if len(links) >= MAX_LINKS:
                _fail(step_name, f"at most {MAX_LINKS} linked snapshots per call")
            try:
                linked = load_snapshot(snapshot_id)  # type: ignore[misc]
            except QueryError as exc:
                _fail(step_name, str(exc))
            links[snapshot_id] = _Index(linked, tag=snapshot_id)
        return list(links[snapshot_id].elements)

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
        elif isinstance(source, str) and source.startswith(LINK_PREFIX):
            rows = link_rows(name, source[len(LINK_PREFIX):])
        else:
            _fail(name, (
                f"'from' is one of {', '.join(SOURCES)}, $<earlier step> or link:<snapshot_id>, not {source!r}"
            ))

        joins = step.get("join", [])
        if not isinstance(joins, list):
            joins = [joins]
        for spec in joins:
            rows = _join(name, rows, spec, index_for)

        if "spatial" in step:
            rows = _spatial(name, rows, step["spatial"], results)

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
            _aggregate(name, [], spec)  # check every aggregate even when no rows reach it
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
    partial = index.partial or any(link.partial for link in links.values())
    return target, results[target], counts, partial, sorted(links)
