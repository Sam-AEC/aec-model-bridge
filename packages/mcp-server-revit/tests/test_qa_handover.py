"""Tests for the qa_handover module (QA and change report built from saved data)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.qa_handover import module as qh
from revit_mcp_server.modules.qa_handover.module import QaHandoverModule


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _door(uid, mark="", eid=1):
    return {"uid": uid, "element_id": eid, "category": "OST_Doors", "type_name": "900x2100",
            "level_uid": "L1", "params": {"Mark": {"v": mark, "storage": "String"}}}


def _snap(ws, sid, elements, taken_at="2026-11-01T09:00:00+00:00", guid="g-1", **extra):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({
        "snapshot_id": sid, "taken_at": taken_at, "elements": elements, "types": [],
        "source": {"doc_title": "Tower A", "doc_guid": guid, "app": "revit", "app_version": "2025"},
        **extra,
    }), encoding="utf-8")


def _proof(ws, plan_id, entries, guid="g-1", outcome="success", executed_at="2026-11-02T09:00:00+00:00"):
    d = ws.allowed_directories[0] / "proofs"
    d.mkdir(exist_ok=True)
    (d / f"{plan_id}.json").write_text(json.dumps({
        "plan_id": plan_id, "outcome": outcome, "approved_by": "jan", "approved_at": "2026-11-02T08:00:00+00:00",
        "executed_at": executed_at, "document": {"doc_guid": guid, "doc_title": "Tower A"},
        "elements": entries, "skipped": [{"element_id": 9, "reason": "locked"}],
        "verification": "UNVERIFIED against the live model: values were not re-read after writing.",
    }), encoding="utf-8")


def _entry(uid, before="", new="D-1", eid=1):
    return {"uid": uid, "element_id": eid, "parameter": "Mark", "before": before,
            "before_recorded": True, "new": new, "status": "executed"}


def _build(ws, **kw):
    return QaHandoverModule().build_report(workspace=ws, **kw)


def _report(ws, result):
    return json.loads(Path(result["json_file"]).read_text(encoding="utf-8"))


def test_single_snapshot_report(ws):
    _snap(ws, "s1", [_door(f"u{i}", eid=i) for i in range(5)] + [_door("ok", "D-9", 99)])
    result = _build(ws, snapshot_id="s1", max_ids=3)
    assert "findings" not in result and result["json_file"].endswith("reports\\qa_handover.json") or "reports/" in result["json_file"]
    rep = _report(ws, result)
    assert rep["data_source"] == "real"
    assert rep["document"] == {"doc_title": "Tower A", "doc_guid": "g-1"}
    assert rep["snapshot"]["snapshot_id"] == "s1" and rep["snapshot"]["taken_at"] == "2026-11-01T09:00:00+00:00"
    assert rep["rule_pack"]["name"] == "core" and len(rep["rule_pack"]["sha256"]) == 64
    assert "no version" in rep["rule_pack"]["note"]
    f = next(x for x in rep["findings"] if x["rule_id"] == "door_missing_mark")
    assert f["count"] == 5 and f["element_ids"] == ["u0", "u1", "u2"] and f["more"] == 2
    assert rep["verification"] is None and rep["plans"] == []
    assert any("not re-checked" in n for n in rep["not_verified"])
    md = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert "Tower A" in md and "door_missing_mark" in md and "Not verified" in md
    md.encode("ascii")


def test_before_after_recheck_and_change_totals(ws):
    _snap(ws, "s1", [_door("a"), _door("b"), _door("c", "X")])
    _snap(ws, "s2", [_door("a", "D-1"), _door("b"), _door("c", "X")], taken_at="2026-11-03T09:00:00+00:00")
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2"))
    v = rep["verification"]
    assert v["before_total"] - v["after_total"] == v["resolved"] == 1
    assert {"rule_id": "door_missing_mark", "before": 2, "after": 1, "resolved": 1, "new": 0} in v["per_rule"]
    assert rep["changes"]["modified_in_captured_fields"] == 1 and rep["after_snapshot"]["snapshot_id"] == "s2"
    assert rep["changes"]["modified"] is None
    assert not any("not re-checked" in n for n in rep["not_verified"])


def test_plan_receipts_confirmed_against_after_snapshot(ws):
    _snap(ws, "s1", [_door("a"), _door("b")])
    _snap(ws, "s2", [_door("a", "D-1"), _door("b", "WRONG")], taken_at="2026-11-03T09:00:00+00:00")
    _proof(ws, "p1", [_entry("a"), _entry("b", eid=2), _entry("zz", eid=3)])
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    plan = rep["plans"][0]
    assert (plan["outcome"], plan["approved_by"], plan["skipped"]) == ("success", "jan", 1)
    assert plan["changed_total"] == plan["recorded_parameter_changes"] == 3
    assert plan["other_actions"] == [] and plan["other_actions_total"] == 0
    assert plan["checks"] == {"confirmed": 1, "differs": 1, "unknown": 1}
    first = plan["changes"][0]
    assert (first["uid"], first["parameter"], first["before"], first["new"], first["check"]) == ("a", "Mark", "", "D-1", "confirmed")
    assert any("p1" in n and "differs" in n for n in rep["not_verified"])


def test_plan_without_after_snapshot_is_not_confirmed(ws):
    _snap(ws, "s1", [_door("a")])
    _proof(ws, "p1", [_entry("a")])
    rep = _report(ws, _build(ws, snapshot_id="s1", plan_ids=["p1"]))
    assert rep["plans"][0]["checks"] == {"confirmed": 0, "differs": 0, "unknown": 1}
    assert any("p1" in n and "after snapshot" in n for n in rep["not_verified"])


def test_after_snapshot_older_than_plan_run_cannot_confirm(ws):
    _snap(ws, "s1", [_door("a")])
    _snap(ws, "s2", [_door("a", "D-1")], taken_at="2026-11-01T10:00:00+00:00")
    _proof(ws, "p1", [_entry("a")])
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    assert rep["plans"][0]["checks"]["confirmed"] == 0
    assert any("before the plan ran" in n for n in rep["not_verified"])


def test_missing_wrong_document_and_bad_plan_ids(ws):
    _snap(ws, "s1", [_door("a")])
    _proof(ws, "other", [_entry("a")], guid="g-2")
    rep = _report(ws, _build(ws, snapshot_id="s1", plan_ids=["nope", "other"]))
    assert [p["plan_id"] for p in rep["plans"]] == ["other"]
    assert any("nope" in n and "no proof bundle" in n for n in rep["not_verified"])
    assert any("other" in n and "different document" in n for n in rep["not_verified"])
    with pytest.raises(ValueError, match="Invalid plan_id"):
        _build(ws, snapshot_id="s1", plan_ids=["../x"])


@pytest.mark.parametrize("bad", ["../x", "a/b", "C:/x", "x.json", "s1.json", "..", "x" + chr(0)])
def test_traversal_ids_are_refused(ws, bad):
    _snap(ws, "s1", [_door("a")])
    with pytest.raises(ValueError):
        _build(ws, snapshot_id=bad)
    with pytest.raises(ValueError):
        _build(ws, snapshot_id="s1", after_snapshot_id=bad)
    with pytest.raises(ValueError):
        _build(ws, snapshot_id="s1", plan_ids=[bad])
    assert not (ws.allowed_directories[0] / "reports").exists()


def test_partial_snapshot_and_missing_identity_are_flagged(ws):
    _snap(ws, "s1", [_door("a")], counts={"truncated": True})
    rep = _report(ws, _build(ws, snapshot_id="s1"))
    assert any("partial" in n for n in rep["not_verified"])
    _snap(ws, "s2", [_door("a")], guid="")
    rep = _report(ws, _build(ws, snapshot_id="s2"))
    assert any("document id" in n for n in rep["not_verified"])


def test_after_snapshot_of_another_model_is_refused(ws):
    _snap(ws, "s1", [_door("a")])
    _snap(ws, "s2", [_door("a")], guid="g-2")
    with pytest.raises(ValueError, match="different Revit models"):
        _build(ws, snapshot_id="s1", after_snapshot_id="s2")


def test_failed_rule_is_reported_not_hidden(ws, monkeypatch):
    _snap(ws, "s1", [_door("a")])
    real = qh.rg._qaqc_rules_module()
    monkeypatch.setattr(real, "_run_rule", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(qh.rg, "_qaqc_rules_module", lambda: real)
    rep = _report(ws, _build(ws, snapshot_id="s1"))
    assert any("could not run" in n and "door_missing_mark" in n for n in rep["not_verified"])


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize("partial", [
    {"dirty_only": True}, {"counts": {"truncated": True}},
    {"counts": {"dirty_only": True}}, {"counts": {"categories": ["OST_Walls"]}},
])
def test_partial_captures_cannot_prove_resolution_or_whole_model_changes(ws, side, partial):
    _snap(ws, "s1", [_door("a")], **(partial if side == "before" else {}))
    _snap(ws, "s2", [], taken_at="2026-11-03T09:00:00+00:00", **(partial if side == "after" else {}))
    result = _build(ws, snapshot_id="s1", after_snapshot_id="s2")
    rep = _report(ws, result)
    assert rep["verification"] is None and rep["changes"] is None
    assert "unknown or unavailable" in result["summary"]
    assert any("Whole-model" in n and "partial" in n for n in rep["not_verified"])
    md = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert "resolved 2" not in md and "1 removed" not in md


@pytest.mark.parametrize("side", ["before", "after"])
def test_failed_rule_is_unknown_during_recheck(ws, monkeypatch, side):
    _snap(ws, "s1", [_door("a")])
    _snap(ws, "s2", [_door("a")], taken_at="2026-11-03T09:00:00+00:00")
    real = qh.rg._qaqc_rules_module()
    run_rule = real._run_rule
    calls = 0

    def fail_one_run(rule, *args):
        nonlocal calls
        if rule["id"] == "door_missing_mark":
            calls += 1
            if calls == (1 if side == "before" else 2):
                raise RuntimeError("rule execution unavailable")
        return run_rule(rule, *args)

    monkeypatch.setattr(real, "_run_rule", fail_one_run)
    monkeypatch.setattr(qh.rg, "_qaqc_rules_module", lambda: real)
    result = _build(ws, snapshot_id="s1", after_snapshot_id="s2")
    rep = _report(ws, result)
    v = rep["verification"]
    finding = next(x for x in v["per_rule"] if x["rule_id"] == "door_missing_mark")
    assert finding[side] is None
    assert finding["after" if side == "before" else "before"] == 1
    assert finding["resolved"] is None and finding["new"] is None
    assert v[f"{side}_total"] is None and v["resolved"] is None
    assert rep["changes"]["modified_in_captured_fields"] == 0
    assert rep["changes"]["modified"] is None
    md = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert "resolved unknown" in md and "None" not in md


@pytest.mark.parametrize("proof_guid,before_guid,after_guid", [
    ("g-2", "g-1", "g-1"), ("", "g-1", "g-1"),
    ("g-1", "", "g-1"), ("g-1", "g-1", ""),
])
def test_plan_confirmation_requires_all_document_identities(ws, proof_guid, before_guid, after_guid):
    _snap(ws, "s1", [_door("a")], guid=before_guid)
    _snap(ws, "s2", [_door("a", "D-1")], guid=after_guid, taken_at="2026-11-03T09:00:00+00:00")
    _proof(ws, "p1", [_entry("a")], guid=proof_guid)
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    assert rep["plans"][0]["checks"] == {"confirmed": 0, "differs": 0, "unknown": 1}
    assert any("Plan p1" in n and "document" in n for n in rep["not_verified"])
    if not before_guid or not after_guid:
        assert rep["verification"] is None and rep["changes"] is None


@pytest.mark.parametrize("executed_at,taken_at", [
    ("", "2026-11-03T09:00:00+00:00"), ("invalid", "2026-11-03T09:00:00+00:00"),
    ("2026-11-02T09:00:00+00:00", ""), ("2026-11-02T09:00:00+00:00", "invalid"),
])
def test_plan_confirmation_requires_known_chronology(ws, executed_at, taken_at):
    _snap(ws, "s1", [_door("a")])
    _snap(ws, "s2", [_door("a", "D-1")], taken_at=taken_at)
    _proof(ws, "p1", [_entry("a")], executed_at=executed_at)
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    assert rep["plans"][0]["checks"] == {"confirmed": 0, "differs": 0, "unknown": 1}
    assert any("Plan p1" in n and "time is missing or invalid" in n for n in rep["not_verified"])


def test_partial_after_can_still_confirm_a_captured_plan_value(ws):
    _snap(ws, "s1", [_door("a"), _door("b")])
    _snap(ws, "s2", [_door("a", "D-1")], taken_at="2026-11-03T09:00:00+00:00", dirty_only=True)
    _proof(ws, "p1", [_entry("a"), _entry("b")])
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    assert rep["verification"] is None and rep["changes"] is None
    assert rep["plans"][0]["checks"] == {"confirmed": 1, "differs": 0, "unknown": 1}


def test_missing_element_identity_cannot_confirm_a_plan_value(ws):
    _snap(ws, "s1", [_door(None)])
    _snap(ws, "s2", [_door(None, "D-1")], taken_at="2026-11-03T09:00:00+00:00")
    _proof(ws, "p1", [_entry(None)])
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    assert rep["plans"][0]["checks"] == {"confirmed": 0, "differs": 0, "unknown": 1}


def test_resolved_findings_follow_rule_and_element_identity(ws):
    # One finding resolves while another element develops the same finding: totals stay equal.
    _snap(ws, "s1", [_door("a"), _door("b", "B")])
    _snap(ws, "s2", [_door("a", "A"), _door("b")], taken_at="2026-11-03T09:00:00+00:00")
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2"))
    v = rep["verification"]
    assert v["before_total"] == v["after_total"]
    assert v["resolved"] == v["new"] == 1
    mark = next(x for x in v["per_rule"] if x["rule_id"] == "door_missing_mark")
    assert mark == {"rule_id": "door_missing_mark", "before": 1, "after": 1, "resolved": 1, "new": 1}


def test_unidentified_findings_do_not_get_net_count_resolution(ws):
    # Legacy saved records without UniqueIds can be counted but not matched across captures.
    _snap(ws, "s1", [_door(None)])
    _snap(ws, "s2", [], taken_at="2026-11-03T09:00:00+00:00")
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2"))
    assert rep["verification"]["before_total"] == 2
    assert rep["verification"]["resolved"] is None
    assert any("finding identities are incomplete" in n for n in rep["not_verified"])


@pytest.mark.parametrize("before_time,after_time", [
    ("", "2026-11-03T09:00:00+00:00"),
    ("2026-11-01T09:00:00+00:00", "invalid"),
    ("2026-11-03T09:00:00+00:00", "2026-11-01T09:00:00+00:00"),
])
def test_whole_model_recheck_requires_ordered_snapshot_times(ws, before_time, after_time):
    _snap(ws, "s1", [_door("a")], taken_at=before_time)
    _snap(ws, "s2", [], taken_at=after_time)
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2"))
    assert rep["verification"] is None and rep["changes"] is None
    assert any("chronology" in n for n in rep["not_verified"])


@pytest.mark.parametrize("old_location,new_location", [
    (None, None), ({"xyz": [0, 0, 0], "rotation": 0}, None),
    (None, {"xyz": [0, 0, 0], "rotation": 0}),
    ({"xyz": [0, 0, 0]}, {"xyz": [0, 0, 0]}),
    ({"rotation": 0}, {"rotation": 0}),
])
def test_missing_location_components_make_modification_totals_unknown(ws, old_location, new_location):
    before, after = _door("a", "D-1"), _door("a", "D-1")
    before["location"], after["location"] = old_location, new_location
    _snap(ws, "s1", [before])
    _snap(ws, "s2", [after], taken_at="2026-11-03T09:00:00+00:00")
    result = _build(ws, snapshot_id="s1", after_snapshot_id="s2")
    rep = _report(ws, result)
    c = rep["changes"]
    assert c["modified"] is None and c["unchanged"] is None
    assert c["modified_in_captured_fields"] == 0 and c["unchanged_in_captured_fields"] == 1
    assert c["not_enough_data"] and any("Snapshot comparison" in n for n in rep["not_verified"])
    md = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert "modified count unknown (0 observed" in md and "0 modified elements" not in md


def test_complete_location_data_retains_known_change_totals(ws):
    before, after = _door("a", "D-1"), _door("a", "D-1")
    before["location"] = {"xyz": [0, 0, 0], "rotation": 0}
    after["location"] = {"xyz": [1, 0, 0], "rotation": 0}
    _snap(ws, "s1", [before])
    _snap(ws, "s2", [after], taken_at="2026-11-03T09:00:00+00:00")
    result = _build(ws, snapshot_id="s1", after_snapshot_id="s2")
    c = _report(ws, result)["changes"]
    assert c["modified"] == c["modified_in_captured_fields"] == 1
    assert c["unchanged"] == 0 and c["elements_compared_on_location"] == 1
    assert c["elements_missing_location"] == c["elements_missing_position"] == c["elements_missing_rotation"] == 0
    assert c["not_enough_data"] == []
    assert "1 modified elements" in Path(result["markdown_file"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("tool", ["revit_set_parameters", "revit_execute_python"])
@pytest.mark.parametrize("fails", [False, True])
def test_real_proof_other_action_outcomes_are_reported(ws, tool, fails):
    _snap(ws, "s1", [_door("a")])
    plan = {
        "plan_id": "p1", "snapshot_id": "s1", "executed_at": "2026-11-02T09:00:00+00:00",
        "actions": [{"action_id": "bulk_or_script", "tool": tool, "arguments": {}}],
    }
    result_row = {"action_id": "bulk_or_script", **({"error": "execution failed"} if fails else {})}
    bundle = qh.proof_mod.build_proof(plan, ws.allowed_directories[0], [result_row])
    assert bundle["elements"] == [] and len(bundle["other_actions"]) == 1
    qh.proof_mod.write_proof(ws.allowed_directories[0], bundle)
    result = _build(ws, snapshot_id="s1", plan_ids=["p1"])
    rep = _report(ws, result)
    p = rep["plans"][0]
    assert p["changed_total"] is None and p["recorded_parameter_changes"] == 0
    assert p["unrecorded_parameter_changes"] is True
    assert p["skipped"] == int(fails)
    assert p["other_actions_total"] == 1
    status = "failed" if fails else "executed"
    assert p["other_action_counts"][status] == 1
    assert p["other_actions"][0]["tool"] == tool and p["other_actions"][0]["status"] == status
    assert any("total parameter changes" in n for n in rep["not_verified"])
    md = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert "total parameter changes unknown (0 individually recorded)" in md
    assert f"{tool}: {status}" in md
    assert ("execution failed" in md) == fails


def test_mixed_proof_counts_single_parameter_skips_and_other_failures(ws):
    _snap(ws, "s1", [_door("a")])
    _snap(ws, "s2", [_door("a", "D-1")], taken_at="2026-11-03T09:00:00+00:00")
    plan = {
        "plan_id": "p1", "snapshot_id": "s1", "executed_at": "2026-11-02T09:00:00+00:00",
        "skipped": [{"element_id": 9, "reason": "locked"}],
        "actions": [
            {"action_id": "single", "tool": "revit_set_parameter_value",
             "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "D-1"},
             "diff": {"before": {"1": {"Mark": ""}}}},
            {"action_id": "bulk", "tool": "revit_set_parameters", "arguments": {}},
            {"action_id": "script", "tool": "revit_execute_python", "arguments": {}},
        ],
    }
    bundle = qh.proof_mod.build_proof(plan, ws.allowed_directories[0], [
        {"action_id": "single"}, {"action_id": "bulk"}, {"action_id": "script", "error": "script failed"},
    ])
    qh.proof_mod.write_proof(ws.allowed_directories[0], bundle)
    result = _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"])
    p = _report(ws, result)["plans"][0]
    assert p["outcome"] == "partial" and p["changed_total"] is None
    assert p["recorded_parameter_changes"] == 1 and p["skipped"] == 2
    assert p["checks"] == {"confirmed": 1, "differs": 0, "unknown": 0}
    assert p["other_action_counts"] == {"executed": 1, "failed": 1, "skipped": 0, "unknown": 0}
    assert "2 skipped or failed" in Path(result["markdown_file"]).read_text(encoding="utf-8")


def test_legacy_non_parameter_proof_without_action_records_stays_unknown(ws):
    _snap(ws, "s1", [_door("a")])
    _proof(ws, "p1", [])
    proof_path = ws.allowed_directories[0] / "proofs" / "p1.json"
    bundle = json.loads(proof_path.read_text(encoding="utf-8"))
    bundle["tool"] = "revit_execute_python"
    proof_path.write_text(json.dumps(bundle), encoding="utf-8")
    result = _build(ws, snapshot_id="s1", plan_ids=["p1"])
    p = _report(ws, result)["plans"][0]
    assert p["changed_total"] is None and p["other_actions_total"] is None
    assert p["other_action_counts"] is None and p["skipped"] is None
    assert p["recorded_skipped_or_failed"] == 1
    md = Path(result["markdown_file"]).read_text(encoding="utf-8")
    assert "Other action outcomes unknown" in md and "unknown (1 recorded) skipped or failed" in md


def test_other_action_counts_include_capped_records_and_skipped_status(ws):
    _snap(ws, "s1", [_door("a")])
    _proof(ws, "p1", [])
    proof_path = ws.allowed_directories[0] / "proofs" / "p1.json"
    bundle = json.loads(proof_path.read_text(encoding="utf-8"))
    bundle["other_actions"] = [
        {"action_id": f"a{i}", "tool": "revit_execute_python", "status": "skipped"}
        for i in range(qh.MAX_CHANGES + 1)
    ]
    proof_path.write_text(json.dumps(bundle), encoding="utf-8")
    result = _build(ws, snapshot_id="s1", plan_ids=["p1"])
    p = _report(ws, result)["plans"][0]
    assert len(p["other_actions"]) == qh.MAX_CHANGES
    assert p["other_actions_total"] == p["other_action_counts"]["skipped"] == qh.MAX_CHANGES + 1
    assert p["skipped"] == qh.MAX_CHANGES + 2  # includes the pre-existing locked parameter entry
    assert "1 more actions in the proof bundle" in Path(result["markdown_file"]).read_text(encoding="utf-8")


def test_bridge_mode_never_falls_back_to_mock(ws, monkeypatch):
    from revit_mcp_server.config import BridgeMode, config

    monkeypatch.setattr(config, "mode", BridgeMode.bridge)
    with pytest.raises(ValueError, match="requires a snapshot_id"):
        _build(ws)
    _snap(ws, "s1", [_door("a")])
    with pytest.raises(ValueError, match="needs snapshot_id"):
        _build(ws, after_snapshot_id="s1")


def test_mock_mode_is_labelled(ws):
    result = _build(ws)
    rep = _report(ws, result)
    assert rep["data_source"] == "mock"
    assert "MOCK" in Path(result["markdown_file"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["../escape", "a/b", "a.b", "", "x" * 65])
def test_output_name_is_confined(ws, name):
    _snap(ws, "s1", [_door("a")])
    with pytest.raises(ValueError, match="output_name"):
        _build(ws, snapshot_id="s1", output_name=name)


def test_limits_and_size_cap(ws, monkeypatch):
    _snap(ws, "s1", [_door(f"u{i}", eid=i) for i in range(60)])
    rep = _report(ws, _build(ws, snapshot_id="s1", max_ids=1000))
    assert len(next(x for x in rep["findings"] if x["rule_id"] == "door_missing_mark")["element_ids"]) == 30
    assert qh._s("x" * 500).endswith("...") and len(qh._s("x" * 500)) == qh.FIELD_LIMIT
    monkeypatch.setattr(qh, "MAX_REPORT_BYTES", 500)
    with pytest.raises(ValueError, match="too large"):
        _build(ws, snapshot_id="s1")


def test_read_only_and_metadata(ws):
    from revit_mcp_server.tool_metadata import DESCRIPTIONS

    manifest = json.loads((Path(qh.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert all(not c["is_mutating"] for c in manifest["commands"])
    text = DESCRIPTIONS["qa_handover_build_report"]
    assert text.endswith("Read-only.") and "instead of" in text
    _snap(ws, "s1", [_door("a")])
    before = sorted(p.name for p in ws.allowed_directories[0].iterdir())
    _build(ws, snapshot_id="s1")
    assert sorted(p.name for p in ws.allowed_directories[0].iterdir()) == sorted(before + ["reports"])


@pytest.mark.anyio
async def test_runs_through_the_real_module_loader(tmp_path):
    """The server loads modules as plain modules; a sibling import must still work there."""
    from revit_mcp_server.config import Config
    from revit_mcp_server.module_registry import ModuleRegistry
    from revit_mcp_server.providers.module_provider import ModuleProvider
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    cfg = Config(workspace_dir=tmp_path, allowed_directories=[tmp_path],
                 audit_log=tmp_path / "audit.log", enable_user_modules=False)
    registry = ModuleRegistry(config_obj=cfg)
    registry.discover_and_load()
    provider = ModuleProvider(module_registry=registry, workspace=WorkspaceMonitor([tmp_path]))
    tool = next(c for c in provider.get_capabilities() if c.name == "qa_handover_build_report")
    assert tool.is_mutating is False
    _snap(SimpleNamespace(allowed_directories=[tmp_path]), "s1", [_door("a")])
    res = await provider.execute_tool("qa_handover_build_report", {"snapshot_id": "s1"})
    assert Path(res["markdown_file"]).is_file() and "findings" in res["summary"]
