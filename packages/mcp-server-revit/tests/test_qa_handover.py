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
    assert {"rule_id": "door_missing_mark", "before": 2, "after": 1} in v["per_rule"]
    assert rep["changes"]["modified"] == 1 and rep["after_snapshot"]["snapshot_id"] == "s2"
    assert not any("not re-checked" in n for n in rep["not_verified"])


def test_plan_receipts_confirmed_against_after_snapshot(ws):
    _snap(ws, "s1", [_door("a"), _door("b")])
    _snap(ws, "s2", [_door("a", "D-1"), _door("b", "WRONG")], taken_at="2026-11-03T09:00:00+00:00")
    _proof(ws, "p1", [_entry("a"), _entry("b", eid=2), _entry("zz", eid=3)])
    rep = _report(ws, _build(ws, snapshot_id="s1", after_snapshot_id="s2", plan_ids=["p1"]))
    plan = rep["plans"][0]
    assert (plan["outcome"], plan["approved_by"], plan["skipped"]) == ("success", "jan", 1)
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
