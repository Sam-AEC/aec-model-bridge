"""Tests for the mark renumber planner (issue 361). Read-only; drafts go through plan_actions."""
import json

import pytest

from revit_mcp_server.modules.mark_renumber_plan.module import MarkRenumberPlanModule as Mod


class WS:
    def __init__(self, p):
        self.allowed_directories = [p]


def level(uid, name):
    return {"uid": uid, "element_id": int(uid[1:]) , "category": "OST_Levels", "type_name": name, "params": {}}


def room(i, number, x=0.0, lv="L1"):
    params = {} if number is None else {"Number": {"v": number}}
    return {"uid": f"r{i}", "element_id": 1000 + i, "category": "OST_Rooms", "type_name": f"Room {i}",
            "level_uid": lv, "location": {"xyz": [x, 0.0, 0.0]}, "params": params}


def window(i, mark, x=0.0, lv="L1"):
    params = {} if mark is None else {"Mark": {"v": mark}}
    return {"uid": f"w{i}", "element_id": 3000 + i, "category": "OST_Windows", "type_name": "Win",
            "level_uid": lv, "location": {"xyz": [x, 0.0, 0.0]}, "params": params}


def door(i, mark, frm=None, to=None):
    params = {"From Room": {"v": frm}, "To Room": {"v": to}}
    if mark is not None:
        params["Mark"] = {"v": mark}
    return {"uid": f"d{i}", "element_id": 2000 + i, "category": "OST_Doors", "type_name": "Door", "params": params}


BASE = [level("L1", "Level 1"), level("L2", "Level 2"), room(1, "101"), room(2, "102")]


def run(tmp_path, elements, cmd="analyze", **kw):
    snaps = tmp_path / "snapshots"
    snaps.mkdir(exist_ok=True)
    (snaps / "s.json").write_text(json.dumps({"elements": elements}), encoding="utf-8")
    return getattr(Mod(), cmd)(snapshot_id="s", workspace=WS(tmp_path), **kw)


def kinds(res):
    return {(f["category"], f["check_id"]) for f in res["findings"]}


def test_duplicates_and_empty_marks(tmp_path):
    els = BASE + [door(1, "101A", None, "r1"), door(2, "101A", None, "r1"), door(3, None, None, "r2")]
    res = run(tmp_path, els, categories=["doors"])
    assert res["read_only"] is True
    assert ("doors", "duplicate_mark") in kinds(res) and ("doors", "empty_mark") in kinds(res)
    mapping = {m["unique_id"]: m["new_mark"] for m in res["proposed_mapping"]}
    assert mapping == {"d2": "101B", "d3": "102A"}


def test_gap_and_out_of_order_rooms(tmp_path):
    els = [level("L1", "Level 1"), room(1, "101", 0), room(2, "104", 10), room(3, "102", 20)]
    res = run(tmp_path, els, categories=["rooms"])
    gap = [f for f in res["findings"] if f["check_id"] == "gap"][0]
    assert gap["missing"] == ["103"]
    assert ("rooms", "out_of_order") in kinds(res)
    mapping = {m["unique_id"]: m["new_mark"] for m in res["proposed_mapping"]}
    assert mapping == {"r2": "102", "r3": "103"}


def test_rooms_per_level_prefix(tmp_path):
    els = [level("L1", "Level 1"), level("L2", "Level 2"), room(1, None, 5, "L2"), room(2, None, 1, "L2"),
           room(3, None, 0, "L1")]
    res = run(tmp_path, els, categories=["rooms"])
    mapping = {m["unique_id"]: m["new_mark"] for m in res["proposed_mapping"]}
    assert mapping == {"r3": "101", "r2": "201", "r1": "202"}


def test_windows_follow_room_scheme(tmp_path):
    els = [level("L1", "Level 1"), window(1, "9", 5), window(2, "9", 1)]
    res = run(tmp_path, els, categories=["windows"])
    assert ("windows", "duplicate_mark") in kinds(res)
    assert {m["unique_id"]: m["new_mark"] for m in res["proposed_mapping"]} == {"w2": "101", "w1": "102"}


def test_exterior_door_uses_from_room(tmp_path):
    res = run(tmp_path, BASE + [door(1, "X", "r1", None)], categories=["doors"])
    assert res["proposed_mapping"][0]["new_mark"] == "101A"


def test_door_with_no_room_reported_not_numbered(tmp_path):
    els = BASE + [door(1, "X", None, None)]
    res = run(tmp_path, els, categories=["doors"])
    assert res["proposed_mapping"] == []
    assert res["not_numbered"][0]["reason"] == "door has no room"
    plan = run(tmp_path, els, "draft_plan", categories=["doors"])
    assert plan["actions"] == [] and plan["skipped"][0]["unique_id"] == "d1"


def test_swap_goes_through_temporary_value(tmp_path):
    # d1 holds 101B and d2 holds 101A, but element order wants d1 -> 101A, d2 -> 101B.
    els = BASE + [door(1, "101B", None, "r1"), door(2, "101A", None, "r1")]
    plan = run(tmp_path, els, "draft_plan", categories=["doors"])
    vals = [(a["arguments"]["element_id"], a["arguments"]["value"]) for a in plan["actions"]]
    assert vals[:2] == [(2001, "__renum_1"), (2002, "__renum_2")]
    assert vals[2:] == [(2001, "101A"), (2002, "101B")]
    assert plan["requires_approval"] is True and plan["actions"][0]["tool"] == "revit_set_parameter_value"
    assert "UNVERIFIED" in plan["unverified"]


def test_chain_orders_writes_so_no_value_is_shared(tmp_path):
    els = [level("L1", "Level 1"), room(1, None, 0), room(2, "101", 10), room(3, "102", 20)]
    plan = run(tmp_path, els, "draft_plan", categories=["rooms"])
    state = {1001: None, 1002: "101", 1003: "102"}
    for a in plan["actions"]:
        state[a["arguments"]["element_id"]] = a["arguments"]["value"]
        held = [v for v in state.values() if v]
        assert len(held) == len(set(held))
    assert state == {1001: "101", 1002: "102", 1003: "103"}


def test_refuses_when_result_has_duplicate(tmp_path):
    # r3 is outside the change set and already holds 102; r2 would become 102.
    els = [level("L1", "Level 1"), room(1, "101", 0), room(2, "105", 5), room(3, "102", 10)]
    with pytest.raises(ValueError, match="duplicates"):
        run(tmp_path, els, "draft_plan", categories=["rooms"], only_unique_ids=["r2"])


def test_refuses_duplicate_with_unnumbered_element(tmp_path):
    els = BASE + [door(1, None, None, "r1"), door(2, "101A", None, None)]
    with pytest.raises(ValueError, match="101A"):
        run(tmp_path, els, "draft_plan", categories=["doors"])


def test_doors_follow_renumbered_rooms(tmp_path):
    els = [level("L1", "Level 1"), room(1, "5", 0), door(1, None, None, "r1")]
    res = run(tmp_path, els, categories=["rooms", "doors"])
    assert {m["unique_id"]: m["new_mark"] for m in res["proposed_mapping"]} == {"r1": "101", "d1": "101A"}


def test_workspace_rule_override(tmp_path):
    rules = tmp_path / "mark_renumber_rules.json"
    rules.write_text(json.dumps({"rooms": {"digits": 3}}), encoding="utf-8")
    res = run(tmp_path, [level("L1", "Level 1"), room(1, None)], categories=["rooms"])
    assert res["proposed_mapping"][0]["new_mark"] == "1001"
    rules.write_text(json.dumps({"rooms": {"scheme": "nope"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown scheme"):
        run(tmp_path, BASE, categories=["rooms"])


def test_mock_mode_runs(monkeypatch):
    monkeypatch.setenv("MCP_REVIT_MODE", "mock")
    res = Mod().analyze()
    assert res["read_only"] is True
    # The mock model has two rooms numbered 101, one unplaced, so the draft must refuse.
    with pytest.raises(ValueError, match="duplicates"):
        Mod().draft_plan()
    assert Mod().draft_plan(categories=["doors"])["requires_approval"] is True


def test_addin_level_reference_is_the_level_element_id(tmp_path):
    """The add-in writes level_uid as the level's element id, not its UniqueId (Codex review on #368)."""
    lv = {"uid": "a1b2-level-uniqueid", "element_id": 311, "category": "OST_Levels", "type_name": "Level 1", "params": {}}
    rooms = [room(1, "105", x=0.0, lv="311"), room(2, "101", x=5.0, lv="311")]
    res = run(tmp_path, [lv] + rooms, categories=["rooms"])
    assert res["not_numbered"] == []
    assert {m["unique_id"]: m["new_mark"] for m in res["proposed_mapping"]} == {"r1": "101", "r2": "102"}


def test_partial_snapshot_warns_and_refuses_to_draft(tmp_path):
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    els = BASE + [door(1, "X", None, "r1")]
    (snaps / "s.json").write_text(json.dumps({"elements": els, "counts": {"truncated": True}}), encoding="utf-8")
    res = Mod().analyze(snapshot_id="s", workspace=WS(tmp_path), categories=["doors"])
    assert "partial capture" in res["warning"]
    with pytest.raises(ValueError, match="Plan refused: Snapshot 's' is a partial capture"):
        Mod().draft_plan(snapshot_id="s", workspace=WS(tmp_path), categories=["doors"])


def test_far_out_mark_is_reported_not_enumerated(tmp_path):
    els = BASE + [door(1, "101A", None, "r1"), door(2, "101ENTRY", None, "r1")]
    res = run(tmp_path, els, categories=["doors"])
    assert ("doors", "out_of_range") in kinds(res)
    gaps = [f for f in res["findings"] if f["check_id"] == "gap"]
    assert all(len(f["missing"]) <= 50 for f in gaps)
