"""Tests for the geometry_screening module (screening checks on snapshot geometry)."""
import json
from pathlib import Path

import pytest

from revit_mcp_server.modules.geometry_screening.module import GeometryScreeningModule


class WS:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _room(uid, eid, number, name, boundary=None, area=None):
    el = {
        "uid": uid, "element_id": eid, "category": "OST_Rooms", "class": "Room", "name": name,
        "params": {"Number": {"v": number, "storage": "String"}},
    }
    if boundary is not None:
        el["geometry_ref"] = {"boundary": boundary}
    if area is not None:
        el["params"]["Area"] = {"v": area, "storage": "Double"}
    return el


def _door(uid, eid, x, y, frm, to, width=None, type_uid=None):
    el = {
        "uid": uid, "element_id": eid, "category": "OST_Doors", "class": "FamilyInstance",
        "location": {"kind": "point", "xyz": [x, y, 0.0], "rotation": 0.0}, "params": {},
    }
    if frm is not None:
        el["params"]["From Room"] = {"v": frm, "storage": "String"}
        el["params"]["To Room"] = {"v": to, "storage": "String"}
    if width is not None:
        el["params"]["Width"] = {"v": width, "storage": "Double"}
    if type_uid:
        el["type_uid"] = type_uid
    return el


def _write(ws, elements, types=None, sid="s1"):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({
        "schema": "amb.snapshot/1", "snapshot_id": sid, "elements": elements, "types": types or [],
    }), encoding="utf-8")


def standard_elements():
    return [
        _room("rA", 1, "101", "Office", _rect(0, 0, 4, 4)),
        _room("rB", 2, "102", "Corridor", _rect(4, 0, 14, 4)),
        _room("rC", 3, "103", "Stair", _rect(14, 0, 18, 4)),
        _room("rD", 4, "104", "WC", _rect(0, 10, 1.4, 12.5)),
        _room("rE", 5, "105", "WC Accessible", _rect(0, 20, 2.5, 22.5)),
        _door("d1", 11, 4, 2, "rA", "rB", width=0.9),
        _door("d2", 12, 14, 2, "rB", "rC", width=0.7),
        _door("d3", 13, 7, 4, "rB", "", width=1.0),
    ]


@pytest.fixture
def ws(tmp_path):
    return WS(tmp_path)


@pytest.fixture
def mod():
    return GeometryScreeningModule()


def run(mod, ws, **kw):
    return mod.run_checks(snapshot_id="s1", snapshot_units="metres", workspace=ws, **kw)


def test_requires_at_least_one_check(mod, ws):
    _write(ws, standard_elements())
    with pytest.raises(ValueError, match="at least one check"):
        run(mod, ws)


def test_missing_snapshot_is_refused(mod, ws):
    with pytest.raises(ValueError, match="not found"):
        run(mod, ws, door_width={"min_clear_width_m": 0.8})


def test_bad_units_are_refused(mod, ws):
    _write(ws, standard_elements())
    with pytest.raises(ValueError, match="snapshot_units"):
        mod.run_checks(snapshot_id="s1", snapshot_units="yards", workspace=ws, door_width={"min_clear_width_m": 0.8})


# room area

def test_room_area_pass_and_fail(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, room_area={"brief": [
        {"match": "101", "min_m2": 12, "max_m2": 20},
        {"match": "office", "min_m2": 18},
        {"match": "Corridor", "max_m2": 30},
        {"match": "Stair", "min_m2": 10},
    ]})
    c = r["checks"]["room_area"]
    assert c["checked"] == 4
    assert c["passed"] == 2
    assert c["failed"] == 2
    assert [(f["element_ids"], f["measured"], f["threshold"], f["threshold_kind"], f["unit"]) for f in c["findings"]] == [
        ([1], 16.0, 18.0, "min", "m2"),
        ([2], 40.0, 30.0, "max", "m2"),
    ]
    assert [f["uids"] for f in c["findings"]] == [["rA"], ["rB"]]


def test_room_area_unmatched_brief_row_is_listed(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, room_area={"brief": [{"match": "Plant room", "min_m2": 5}]})
    c = r["checks"]["room_area"]
    assert c["unmatched_brief"] == ["Plant room"]
    assert c["findings"] == []


def test_room_area_falls_back_to_area_parameter_and_converts_feet(mod, ws):
    _write(ws, [_room("r1", 1, "1", "Store", None, area=107.6391)])
    r = mod.run_checks(snapshot_id="s1", workspace=ws, room_area={"brief": [{"match": "Store", "min_m2": 11}]})
    f = r["checks"]["room_area"]["findings"][0]
    assert f["measured"] == pytest.approx(10.0, abs=0.01)
    assert f["threshold"] == 11


def test_room_area_refuses_without_boundary_or_area(mod, ws):
    _write(ws, [_room("r1", 1, "1", "Store")])
    with pytest.raises(ValueError, match="boundary"):
        run(mod, ws, room_area={"brief": [{"match": "Store", "min_m2": 5}]})


def test_room_area_refuses_when_no_rooms(mod, ws):
    _write(ws, [_door("d1", 1, 0, 0, "a", "b", width=1)])
    with pytest.raises(ValueError, match="no rooms"):
        run(mod, ws, room_area={"brief": [{"match": "Store", "min_m2": 5}]})


def test_room_area_skips_unplaced_room(mod, ws):
    _write(ws, [_room("r1", 1, "1", "Store", None, area=0.0), _room("r2", 2, "2", "Store", _rect(0, 0, 3, 3))])
    r = run(mod, ws, room_area={"brief": [{"match": "Store", "min_m2": 5}]})
    c = r["checks"]["room_area"]
    assert c["checked"] == 1 and c["passed"] == 1
    assert c["skipped"][0]["element_ids"] == [1]


@pytest.mark.parametrize("brief", [[], [{"match": "x"}], [{"match": "x", "min_m2": 5, "max_m2": 2}], [{"min_m2": 1}], "x"])
def test_room_area_bad_brief_is_refused(mod, ws, brief):
    _write(ws, standard_elements())
    with pytest.raises(ValueError):
        run(mod, ws, room_area={"brief": brief})


# door width

def test_door_width_pass_and_fail(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, door_width={"min_clear_width_m": 0.85})
    c = r["checks"]["door_width"]
    assert c["checked"] == 3 and c["passed"] == 2
    f = c["findings"][0]
    assert f["element_ids"] == [12] and f["uids"] == ["d2"]
    assert (f["measured"], f["threshold"], f["threshold_kind"], f["unit"]) == (0.7, 0.85, "min", "m")
    assert f["width_parameter"] == "Width"


def test_door_width_converts_feet(mod, ws):
    _write(ws, [_door("d1", 1, 0, 0, "a", "b", width=2.5)])
    r = mod.run_checks(snapshot_id="s1", workspace=ws, door_width={"min_clear_width_m": 0.85})
    assert r["checks"]["door_width"]["findings"][0]["measured"] == pytest.approx(0.762, abs=1e-3)


def test_door_width_reads_type_parameter(mod, ws):
    types = [{"uid": "t1", "category": "OST_Doors", "family": "F", "type_name": "T",
              "params": {"Width": {"v": 0.8, "storage": "Double"}}}]
    _write(ws, [_door("d1", 1, 0, 0, "a", "b", type_uid="t1"), _door("d2", 2, 0, 0, "a", "b")], types)
    r = run(mod, ws, door_width={"min_clear_width_m": 0.9})
    c = r["checks"]["door_width"]
    assert [f["element_ids"] for f in c["findings"]] == [[1]]
    assert c["skipped"][0]["element_ids"] == [2]


def test_door_width_prefers_clear_width_parameter(mod, ws):
    door = _door("d1", 1, 0, 0, "a", "b", width=1.0)
    door["params"]["Clear Width"] = {"v": 0.75, "storage": "Double"}
    _write(ws, [door])
    f = run(mod, ws, door_width={"min_clear_width_m": 0.8})["checks"]["door_width"]["findings"][0]
    assert f["measured"] == 0.75 and f["width_parameter"] == "Clear Width"


def test_door_width_refuses_without_doors(mod, ws):
    _write(ws, [_room("r1", 1, "1", "Store", _rect(0, 0, 3, 3))])
    with pytest.raises(ValueError, match="no doors"):
        run(mod, ws, door_width={"min_clear_width_m": 0.9})


def test_door_width_refuses_when_no_door_has_a_width(mod, ws):
    _write(ws, [_door("d1", 1, 0, 0, "a", "b")])
    with pytest.raises(ValueError, match="width"):
        run(mod, ws, door_width={"min_clear_width_m": 0.9})


# turning circle

def test_turning_circle_pass_and_fail(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, turning_circle={"diameter_m": 1.5, "rooms": ["104", "WC Accessible"]})
    c = r["checks"]["turning_circle"]
    assert c["checked"] == 2 and c["passed"] == 1
    f = c["findings"][0]
    assert f["element_ids"] == [4]
    assert f["measured"] == pytest.approx(1.4, abs=0.01)
    assert (f["threshold"], f["threshold_kind"], f["unit"]) == (1.5, "min", "m")
    assert f["centre"] == pytest.approx([0.7, 11.25], abs=0.01)


def test_turning_circle_concave_room(mod, ws):
    l_shape = [[0, 0], [6, 0], [6, 1], [1, 1], [1, 6], [0, 6]]
    _write(ws, [_room("r1", 1, "1", "L", l_shape)])
    r = run(mod, ws, turning_circle={"diameter_m": 1.5, "rooms": ["L"]})
    assert r["checks"]["turning_circle"]["findings"][0]["measured"] == pytest.approx(1.172, abs=0.01)


def test_turning_circle_closed_ring_and_feet(mod, ws):
    ring = _rect(0, 0, 10, 10) + [[0, 0]]
    _write(ws, [_room("r1", 1, "1", "Big", ring)])
    r = mod.run_checks(snapshot_id="s1", workspace=ws, turning_circle={"diameter_m": 5, "rooms": ["Big"]})
    assert r["checks"]["turning_circle"]["findings"][0]["measured"] == pytest.approx(3.048, abs=0.01)


def test_turning_circle_is_deterministic(mod, ws):
    _write(ws, standard_elements())
    a = run(mod, ws, turning_circle={"diameter_m": 5, "rooms": ["Office", "WC"]})
    b = run(mod, ws, turning_circle={"diameter_m": 5, "rooms": ["Office", "WC"]})
    assert a == b


def test_turning_circle_refuses_without_boundaries(mod, ws):
    _write(ws, [_room("r1", 1, "1", "WC", None, area=5.0)])
    with pytest.raises(ValueError, match="boundar"):
        run(mod, ws, turning_circle={"diameter_m": 1.5, "rooms": ["WC"]})


def test_turning_circle_refuses_when_no_room_matches(mod, ws):
    _write(ws, standard_elements())
    with pytest.raises(ValueError, match="no room"):
        run(mod, ws, turning_circle={"diameter_m": 1.5, "rooms": ["Nowhere"]})


def test_turning_circle_lists_rooms_without_outline_as_skipped(mod, ws):
    _write(ws, standard_elements() + [_room("rX", 9, "109", "WC", None)])
    r = run(mod, ws, turning_circle={"diameter_m": 1.0, "rooms": ["WC"]})
    c = r["checks"]["turning_circle"]
    assert c["checked"] == 1 and c["skipped"][0]["element_ids"] == [9]


def test_turning_circle_invalid_outline_is_skipped(mod, ws):
    _write(ws, standard_elements() + [_room("rX", 9, "109", "WC", [[0, 0], [1, 1]])])
    r = run(mod, ws, turning_circle={"diameter_m": 1.0, "rooms": ["WC"]})
    assert r["checks"]["turning_circle"]["skipped"][0]["element_ids"] == [9]


# travel distance

def test_travel_distance_pass_and_fail(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 10, "from_rooms": ["Office", "Corridor"]})
    c = r["checks"]["travel_distance"]
    assert c["checked"] == 2 and c["passed"] == 1
    f = c["findings"][0]
    assert f["measured"] == pytest.approx(14.0)
    assert (f["threshold"], f["threshold_kind"], f["unit"]) == (10, "max", "m")
    assert f["path_uids"] == ["rA", "d1", "rB", "d2", "rC"]
    assert f["element_ids"] == [1, 11, 2, 12, 3]


def test_travel_distance_passes_within_limit(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, travel_distance={"exit_rooms": ["103"], "max_m": 14.0, "from_rooms": ["101"]})
    c = r["checks"]["travel_distance"]
    assert c["findings"] == [] and c["passed"] == 1


def test_travel_distance_unreachable_room_is_a_finding(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 100, "from_rooms": ["WC"]})
    f = r["checks"]["travel_distance"]["findings"][0]
    assert f["element_ids"] == [4]
    assert f["measured"] is None and "no route" in f["message"]


def test_travel_distance_picks_shortest_of_two_routes(mod, ws):
    els = standard_elements() + [
        _room("rX", 6, "106", "Exit B", _rect(0, -4, 4, 0)),
        _door("d4", 14, 2, 0, "rA", "rX", width=1.0),
    ]
    _write(ws, els)
    r = run(mod, ws, travel_distance={"exit_rooms": ["Stair", "Exit B"], "max_m": 1, "from_rooms": ["Office"]})
    f = r["checks"]["travel_distance"]["findings"][0]
    assert f["measured"] == pytest.approx(4.0)
    assert f["path_uids"] == ["rA", "d4", "rX"]


def test_travel_distance_start_in_exit_room_is_zero(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 1, "from_rooms": ["Stair"]})
    assert r["checks"]["travel_distance"]["findings"] == []


def test_travel_distance_defaults_to_every_other_room(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 10})
    c = r["checks"]["travel_distance"]
    assert c["checked"] == 4
    assert sorted(f["element_ids"][0] for f in c["findings"]) == [1, 4, 5]


def test_travel_distance_refuses_without_room_boundaries(mod, ws):
    els = [_room("rA", 1, "1", "A", None, area=10.0), _room("rB", 2, "2", "B", None, area=10.0),
           _door("d1", 3, 0, 0, "rA", "rB", width=1)]
    _write(ws, els)
    with pytest.raises(ValueError, match="boundar"):
        run(mod, ws, travel_distance={"exit_rooms": ["B"], "max_m": 10})


def test_travel_distance_refuses_without_door_room_keys(mod, ws):
    els = [e for e in standard_elements() if e["category"] != "OST_Doors"] + [_door("d1", 3, 0, 0, None, None, width=1)]
    _write(ws, els)
    with pytest.raises(ValueError, match="From Room"):
        run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 10})


def test_travel_distance_refuses_without_doors(mod, ws):
    _write(ws, [e for e in standard_elements() if e["category"] != "OST_Doors"])
    with pytest.raises(ValueError, match="no doors"):
        run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 10})


def test_travel_distance_refuses_when_doors_have_no_location(mod, ws):
    els = standard_elements()
    for e in els:
        e.pop("location", None)
    _write(ws, els)
    with pytest.raises(ValueError, match="location"):
        run(mod, ws, travel_distance={"exit_rooms": ["Stair"], "max_m": 10})


def test_travel_distance_refuses_when_exit_room_not_found(mod, ws):
    _write(ws, standard_elements())
    with pytest.raises(ValueError, match="exit"):
        run(mod, ws, travel_distance={"exit_rooms": ["Nowhere"], "max_m": 10})


def test_travel_distance_converts_feet(mod, ws):
    els = [
        _room("rA", 1, "1", "A", _rect(0, 0, 10, 10)),
        _room("rB", 2, "2", "B", _rect(10, 0, 20, 10)),
        _door("d1", 3, 10, 5, "rA", "rB", width=3),
    ]
    _write(ws, els)
    r = mod.run_checks(snapshot_id="s1", workspace=ws, travel_distance={"exit_rooms": ["B"], "max_m": 1})
    assert r["checks"]["travel_distance"]["findings"][0]["measured"] == pytest.approx(10 * 0.3048, abs=1e-3)


# combined and notice

def test_combined_run_reports_notice_and_counts(mod, ws):
    _write(ws, standard_elements())
    r = run(mod, ws, door_width={"min_clear_width_m": 0.85}, room_area={"brief": [{"match": "Stair", "min_m2": 100}]})
    assert set(r["checks"]) == {"door_width", "room_area"}
    assert r["finding_count"] == 2
    assert "not a code compliance" in r["notice"]
    assert "UNVERIFIED" in r["notice"]


def test_max_items_caps_listing_but_not_counts(mod, ws):
    _write(ws, [_door(f"d{i}", i, 0, 0, "a", "b", width=0.5) for i in range(5)])
    r = run(mod, ws, door_width={"min_clear_width_m": 0.8}, max_items=2)
    c = r["checks"]["door_width"]
    assert c["failed"] == 5 and len(c["findings"]) == 2 and c["findings_truncated"] is True


def test_reads_category_names_without_prefix(mod, ws):
    els = standard_elements()
    for e in els:
        e["category"] = e["category"].replace("OST_", "")
    _write(ws, els)
    r = run(mod, ws, door_width={"min_clear_width_m": 0.85})
    assert r["checks"]["door_width"]["checked"] == 3
