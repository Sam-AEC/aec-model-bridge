"""
geometry_screening module: repeatable geometric screening of a saved snapshot.

Command:
  run_checks  - room area against a brief, door width against a minimum, a turning circle
                inside a room outline, and travel distance through doors to exit rooms.

Read-only. Snapshots are read from ``<workspace>/snapshots/{snapshot_id}.json``.
This is a screening aid, not a code compliance check. Missing data is refused, never guessed.

Snapshot data used:
  rooms  - ``geometry_ref.boundary``: one closed outline as [[x, y], ...] in plan (outer loop,
           no holes); ``params.Area`` as a fallback for the area check only.
  doors  - ``params["From Room"]`` and ``params["To Room"]`` (room uids), ``location.xyz``, and
           ``Clear Width`` or ``Width`` on the door or its type.
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MAX_ITEMS = 200
FEET_TO_METRES = 0.3048
UNITS = {"feet": FEET_TO_METRES, "ft": FEET_TO_METRES, "metres": 1.0, "meters": 1.0, "m": 1.0}
CHECKS = ("room_area", "door_width", "turning_circle", "travel_distance")
WIDTH_PARAMS = ("Clear Width", "Width")
NOTICE = (
    "Screening aid, not a code compliance check. Results are measured on snapshot geometry only. "
    "Results on a real model are UNVERIFIED until checked in a live Revit."
)
CIRCLE_PRECISION_M = 0.001

Point = Tuple[float, float]


def _load_snapshot(snapshot_id: str, workspace: Any) -> Dict[str, Any]:
    from revit_mcp_server.security.safe_paths import snapshot_file

    path = snapshot_file(Path(workspace.allowed_directories[0]) / "snapshots", snapshot_id)
    if not path.exists():
        raise ValueError(f"Snapshot '{snapshot_id}' not found. Use model_changes_list_snapshots to see the saved snapshots.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cat(el: Dict[str, Any]) -> str:
    c = str(el.get("category") or "").lower()
    return c[4:] if c.startswith("ost_") else c


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _pv(params: Any, name: str) -> Any:
    p = (params or {}).get(name)
    return p.get("v") if isinstance(p, dict) else p


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


# geometry

def _outline(el: Dict[str, Any]) -> Optional[List[Point]]:
    ref = el.get("geometry_ref")
    pts = ref.get("boundary") if isinstance(ref, dict) else None
    if not isinstance(pts, list):
        return None
    out: List[Point] = []
    for p in pts:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        x, y = _num(p[0]), _num(p[1])
        if x is None or y is None:
            return None
        out.append((x, y))
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out if len(out) >= 3 else None


def _area(poly: List[Point]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _centroid(poly: List[Point]) -> Point:
    a = c_x = c_y = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        c_x += (x1 + x2) * cross
        c_y += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    return (c_x / (3.0 * a), c_y / (3.0 * a))


def _signed_distance(px: float, py: float, poly: List[Point]) -> float:
    """Distance to the nearest edge, positive inside the polygon and negative outside."""
    inside = False
    best = math.inf
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length2))
        best = min(best, math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))
    return best if inside else -best


def _largest_circle(poly: List[Point], precision: float) -> Tuple[float, Point]:
    """Radius and centre of the largest inscribed circle, within ``precision`` (cell search, deterministic)."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)
    size = min(max_x - min_x, max_y - min_y)
    if size <= 0:
        return 0.0, (min_x, min_y)
    half = size / 2.0
    heap: List[Tuple[float, float, float, float, float]] = []
    counter = 0

    def push(cx: float, cy: float, h: float) -> None:
        nonlocal counter
        d = _signed_distance(cx, cy, poly)
        counter += 1
        heapq.heappush(heap, (-(d + h * math.sqrt(2)), counter, cx, cy, h))
        cells.append((d, cx, cy))

    cells: List[Tuple[float, float, float]] = []
    x = min_x
    while x < max_x:
        y = min_y
        while y < max_y:
            push(x + half, y + half, half)
            y += size
        x += size
    cx0, cy0 = _centroid(poly)
    best_d, best_x, best_y = _signed_distance(cx0, cy0, poly), cx0, cy0
    for d, cx, cy in cells:
        if d > best_d:
            best_d, best_x, best_y = d, cx, cy
    while heap:
        neg_max, _, cx, cy, h = heapq.heappop(heap)
        if -neg_max - best_d <= precision:
            break
        h2 = h / 2.0
        for dx in (-h2, h2):
            for dy in (-h2, h2):
                nx, ny = cx + dx, cy + dy
                d = _signed_distance(nx, ny, poly)
                if d > best_d:
                    best_d, best_x, best_y = d, nx, ny
                counter += 1
                heapq.heappush(heap, (-(d + h2 * math.sqrt(2)), counter, nx, ny, h2))
    return max(best_d, 0.0), (best_x, best_y)


# snapshot access

class _Ctx:
    def __init__(self, snap: Dict[str, Any], to_m: float):
        self.to_m = to_m
        els = [e for e in snap.get("elements") or [] if isinstance(e, dict)]
        self.rooms = [e for e in els if _cat(e) == "rooms"]
        self.doors = [e for e in els if _cat(e) == "doors"]
        self.types = {t.get("uid"): t for t in snap.get("types") or [] if isinstance(t, dict)}

    def room_label(self, room: Dict[str, Any]) -> str:
        return _room_name(room) or _room_number(room) or str(room.get("element_id"))

    def select(self, selectors: List[str]) -> List[Dict[str, Any]]:
        wanted = {s.strip().casefold() for s in selectors}
        return [r for r in self.rooms if _room_number(r).casefold() in wanted or _room_name(r).casefold() in wanted]


def _room_number(room: Dict[str, Any]) -> str:
    return _text(_pv(room.get("params"), "Number"))


def _room_name(room: Dict[str, Any]) -> str:
    return _text(room.get("name") or _pv(room.get("params"), "Name") or room.get("type_name"))


def _ids(*els: Dict[str, Any]) -> Dict[str, Any]:
    return {"element_ids": [e.get("element_id") for e in els], "uids": [e.get("uid") for e in els]}


def _r(value: float) -> float:
    return round(value, 3)


def _selectors(spec: Dict[str, Any], key: str, check: str) -> List[str]:
    value = spec.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f"{check}: '{key}' must be a non-empty list of room numbers or names.")
    return value


def _threshold(spec: Dict[str, Any], key: str, check: str) -> float:
    value = _num(spec.get(key))
    if value is None or value <= 0:
        raise ValueError(f"{check}: '{key}' must be a number above zero.")
    return value


def _summary(checked: int, findings: List[Dict[str, Any]], skipped: List[Dict[str, Any]], max_items: int, **extra: Any) -> Dict[str, Any]:
    out = {
        "checked": checked,
        "passed": checked - len(findings),
        "failed": len(findings),
        "findings": findings[:max_items],
        "findings_truncated": len(findings) > max_items,
        "skipped": skipped[:max_items],
        "skipped_count": len(skipped),
    }
    out.update(extra)
    return out


# checks

def _check_room_area(ctx: _Ctx, spec: Dict[str, Any], max_items: int) -> Dict[str, Any]:
    brief = spec.get("brief")
    if not isinstance(brief, list) or not brief:
        raise ValueError("room_area: 'brief' must be a non-empty list of {match, min_m2, max_m2}.")
    rows = []
    for row in brief:
        if not isinstance(row, dict) or not isinstance(row.get("match"), str) or not row["match"].strip():
            raise ValueError("room_area: every brief row needs a 'match' (room number or name).")
        lo, hi = _num(row.get("min_m2")), _num(row.get("max_m2"))
        if lo is None and hi is None:
            raise ValueError(f"room_area: brief row '{row['match']}' needs min_m2, max_m2 or both.")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"room_area: brief row '{row['match']}' has min_m2 above max_m2.")
        rows.append((row["match"], lo, hi))
    if not ctx.rooms:
        raise ValueError("room_area: the snapshot holds no rooms. Take a snapshot that includes the Rooms category.")

    findings: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    unmatched: List[str] = []
    skipped_ids = set()
    checked = 0
    measurable = 0
    matched_any = False
    for match, lo, hi in rows:
        rooms = ctx.select([match])
        if not rooms:
            unmatched.append(match)
            continue
        matched_any = True
        for room in rooms:
            poly = _outline(room)
            if poly is not None:
                area, source = _area(poly) * ctx.to_m ** 2, "boundary"
            else:
                raw = _num(_pv(room.get("params"), "Area"))
                area, source = (raw * ctx.to_m ** 2, "Area parameter") if raw is not None else (None, "")
            if area is None or area <= 0:
                if room.get("uid") not in skipped_ids:
                    skipped_ids.add(room.get("uid"))
                    reason = "room is not placed (area 0)" if area == 0 else "no room boundary or Area parameter in the snapshot"
                    skipped.append({**_ids(room), "reason": reason})
                continue
            measurable += 1
            checked += 1
            for kind, limit, bad in (("min", lo, lo is not None and area < lo), ("max", hi, hi is not None and area > hi)):
                if bad:
                    findings.append({
                        "check": "room_area", **_ids(room), "room": ctx.room_label(room),
                        "measured": _r(area), "threshold": limit, "threshold_kind": kind, "unit": "m2",
                        "area_source": source,
                        "message": f"Room '{ctx.room_label(room)}' is {_r(area)} m2, "
                                   f"{'below the minimum' if kind == 'min' else 'above the maximum'} of {limit} m2.",
                    })
    if matched_any and measurable == 0:
        raise ValueError(
            "room_area: no matched room has a room boundary or Area in the snapshot. "
            "The snapshot must carry room outlines (geometry_ref.boundary) or the Area parameter."
        )
    return _summary(checked, findings, skipped, max_items, unmatched_brief=unmatched)


def _door_width(ctx: _Ctx, door: Dict[str, Any], override: Optional[str]) -> Tuple[Optional[float], str]:
    names = (override,) if override else WIDTH_PARAMS
    holders = (door.get("params"), (ctx.types.get(door.get("type_uid")) or {}).get("params"))
    for holder in holders:
        for name in names:
            value = _num(_pv(holder, name))
            if value is not None:
                return value, name
    return None, ""


def _check_door_width(ctx: _Ctx, spec: Dict[str, Any], max_items: int) -> Dict[str, Any]:
    minimum = _threshold(spec, "min_clear_width_m", "door_width")
    override = spec.get("width_parameter")
    if override is not None and not isinstance(override, str):
        raise ValueError("door_width: 'width_parameter' must be a parameter name.")
    if not ctx.doors:
        raise ValueError("door_width: the snapshot holds no doors. Take a snapshot that includes the Doors category.")
    findings: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    checked = 0
    for door in ctx.doors:
        raw, name = _door_width(ctx, door, override)
        if raw is None:
            skipped.append({**_ids(door), "reason": "no door width in the snapshot"})
            continue
        width = raw * ctx.to_m
        checked += 1
        if width < minimum:
            findings.append({
                "check": "door_width", **_ids(door), "measured": _r(width), "threshold": minimum,
                "threshold_kind": "min", "unit": "m", "width_parameter": name,
                "message": f"Door width is {_r(width)} m, below the minimum of {minimum} m.",
            })
    if checked == 0:
        raise ValueError(
            "door_width: no door has a width in the snapshot. Take it with the Width or Clear Width parameter "
            "(snapshot_take params), or name the parameter with width_parameter."
        )
    return _summary(checked, findings, skipped, max_items)


def _check_turning_circle(ctx: _Ctx, spec: Dict[str, Any], max_items: int) -> Dict[str, Any]:
    diameter = _threshold(spec, "diameter_m", "turning_circle")
    rooms = ctx.select(_selectors(spec, "rooms", "turning_circle"))
    if not rooms:
        raise ValueError("turning_circle: no room in the snapshot matches the given numbers or names.")
    findings: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    checked = 0
    for room in rooms:
        poly = _outline(room)
        if poly is None:
            skipped.append({**_ids(room), "reason": "no valid room boundary in the snapshot"})
            continue
        radius, (cx, cy) = _largest_circle(poly, CIRCLE_PRECISION_M / ctx.to_m)
        checked += 1
        measured = 2 * radius * ctx.to_m
        if measured < diameter:
            findings.append({
                "check": "turning_circle", **_ids(room), "room": ctx.room_label(room),
                "measured": _r(measured), "threshold": diameter, "threshold_kind": "min", "unit": "m",
                "centre": [_r(cx * ctx.to_m), _r(cy * ctx.to_m)],
                "message": f"Largest circle in room '{ctx.room_label(room)}' is {_r(measured)} m across, "
                           f"below the {diameter} m turning circle.",
            })
    if checked == 0:
        raise ValueError(
            "turning_circle: none of the matched rooms has a room boundary in the snapshot. "
            "The snapshot must carry room outlines (geometry_ref.boundary)."
        )
    return _summary(checked, findings, skipped, max_items, tolerance_m=CIRCLE_PRECISION_M)


def _check_travel_distance(ctx: _Ctx, spec: Dict[str, Any], max_items: int) -> Dict[str, Any]:
    limit = _threshold(spec, "max_m", "travel_distance")
    exit_sel = _selectors(spec, "exit_rooms", "travel_distance")
    start_sel = spec.get("from_rooms")
    if start_sel is not None:
        start_sel = _selectors(spec, "from_rooms", "travel_distance")

    nodes: Dict[str, Tuple[Dict[str, Any], Point]] = {}
    for room in ctx.rooms:
        poly = _outline(room)
        if poly is not None and room.get("uid"):
            nodes[room["uid"]] = (room, _centroid(poly))
    if not nodes:
        raise ValueError(
            "travel_distance: no room has a room boundary in the snapshot. "
            "The snapshot must carry room outlines (geometry_ref.boundary)."
        )
    exits = [r["uid"] for r in ctx.select(exit_sel) if r.get("uid") in nodes]
    if not exits:
        raise ValueError("travel_distance: no exit room with a room boundary matches 'exit_rooms'.")
    if not ctx.doors:
        raise ValueError("travel_distance: the snapshot holds no doors. Take a snapshot that includes the Doors category.")
    if not any("From Room" in (d.get("params") or {}) or "To Room" in (d.get("params") or {}) for d in ctx.doors):
        raise ValueError(
            "travel_distance: no door has From Room or To Room in the snapshot. "
            "Take the snapshot with include [\"rooms\"] so doors carry their room keys."
        )

    graph: Dict[str, List[Tuple[float, str, Dict[str, Any]]]] = {uid: [] for uid in nodes}
    located = 0
    skipped: List[Dict[str, Any]] = []
    for door in ctx.doors:
        loc = door.get("location")
        xyz = loc.get("xyz") if isinstance(loc, dict) else None
        x = _num(xyz[0]) if isinstance(xyz, list) and len(xyz) >= 2 else None
        y = _num(xyz[1]) if x is not None else None
        if x is None or y is None:
            skipped.append({**_ids(door), "reason": "door has no location in the snapshot"})
            continue
        located += 1
        a, b = _text(_pv(door.get("params"), "From Room")), _text(_pv(door.get("params"), "To Room"))
        if a not in nodes or b not in nodes or a == b:
            continue
        length = math.hypot(nodes[a][1][0] - x, nodes[a][1][1] - y) + math.hypot(nodes[b][1][0] - x, nodes[b][1][1] - y)
        graph[a].append((length, b, door))
        graph[b].append((length, a, door))
    if located == 0:
        raise ValueError("travel_distance: no door has a location in the snapshot, so door points cannot be measured.")

    dist: Dict[str, float] = {uid: 0.0 for uid in exits}
    prev: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    heap = [(0.0, uid) for uid in sorted(exits)]
    heapq.heapify(heap)
    while heap:
        d, uid = heapq.heappop(heap)
        if d > dist.get(uid, math.inf):
            continue
        for length, other, door in sorted(graph[uid], key=lambda e: (e[0], e[1])):
            nd = d + length
            if nd < dist.get(other, math.inf):
                dist[other] = nd
                prev[other] = (uid, door)
                heapq.heappush(heap, (nd, other))

    if start_sel is not None:
        starts = [r["uid"] for r in ctx.select(start_sel) if r.get("uid") in nodes]
    else:
        starts = [uid for uid in nodes if uid not in set(exits)]
    findings: List[Dict[str, Any]] = []
    for uid in starts:
        room = nodes[uid][0]
        if uid not in dist:
            findings.append({
                "check": "travel_distance", **_ids(room), "room": ctx.room_label(room),
                "measured": None, "threshold": limit, "threshold_kind": "max", "unit": "m",
                "message": f"Room '{ctx.room_label(room)}' has no route through doors to an exit room.",
            })
            continue
        measured = dist[uid] * ctx.to_m
        if measured > limit:
            path = [room]
            cur = uid
            while cur in prev:
                cur, door = prev[cur]
                path.extend([door, nodes[cur][0]])
            findings.append({
                "check": "travel_distance", **_ids(*path), "room": ctx.room_label(room),
                "measured": _r(measured), "threshold": limit, "threshold_kind": "max", "unit": "m",
                "path_uids": [e.get("uid") for e in path],
                "message": f"Travel distance from room '{ctx.room_label(room)}' is {_r(measured)} m, "
                           f"above the limit of {limit} m.",
            })
    return _summary(
        len(starts), findings, skipped, max_items,
        method="room centroid to door point to room centroid, shortest path over doors",
    )


class GeometryScreeningModule:
    def run_checks(
        self,
        snapshot_id: str = "",
        snapshot_units: str = "feet",
        max_items: int = DEFAULT_MAX_ITEMS,
        workspace: Any = None,
        **checks: Any,
    ) -> Dict[str, Any]:
        if snapshot_units not in UNITS:
            raise ValueError("snapshot_units must be 'feet' or 'metres'.")
        requested = {k: v for k, v in checks.items() if k in CHECKS and v is not None}
        if not requested:
            raise ValueError(f"Run at least one check: {', '.join(CHECKS)}.")
        for name, spec in requested.items():
            if not isinstance(spec, dict):
                raise ValueError(f"{name}: settings must be an object.")
        try:
            max_items = max(1, int(max_items))
        except (TypeError, ValueError):
            max_items = DEFAULT_MAX_ITEMS
        snap = _load_snapshot(snapshot_id, workspace)
        counts = snap.get("counts") or {}
        ctx = _Ctx(snap, UNITS[snapshot_units])
        runners = {
            "room_area": _check_room_area,
            "door_width": _check_door_width,
            "turning_circle": _check_turning_circle,
            "travel_distance": _check_travel_distance,
        }
        results = {name: runners[name](ctx, requested[name], max_items) for name in CHECKS if name in requested}
        out: Dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "snapshot_units": snapshot_units,
            "checks": results,
            "finding_count": sum(r["failed"] for r in results.values()),
            "notice": NOTICE,
        }
        if counts.get("truncated"):
            out["partial_snapshot"] = True
            out["partial_note"] = "The snapshot is a partial capture, so rooms or doors may be missing from these checks."
        return out
