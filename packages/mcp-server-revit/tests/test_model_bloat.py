"""Tests for the read-only model bloat audit module (fixture snapshots)."""
import importlib.util
import json
from pathlib import Path

import pytest

_p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/model_bloat/module.py"
_spec = importlib.util.spec_from_file_location("_mb_impl", _p)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ModelBloatModule = _mod.ModelBloatModule


class WS:
    def __init__(self, tmp_path):
        self.allowed_directories = [tmp_path]


def _el(i, family, type_name, type_uid=None, cls="FamilyInstance", params=None):
    return {"uid": f"e{i}", "element_id": i, "category": "OST_Furniture", "class": cls,
            "family": family, "type_name": type_name, "type_uid": type_uid, "params": params or {}}


def _ty(uid, family, name, source="loadable"):
    return {"uid": uid, "category": "OST_Furniture", "family": family, "type_name": name,
            "family_source": source, "params": {}}


def _write(tmp_path, elements, types, sid="snap1"):
    d = tmp_path / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({"elements": elements, "types": types}), encoding="utf-8")
    return sid


@pytest.fixture
def fixture_snapshot(tmp_path):
    types = [
        _ty("t1", "Chair", "Std"), _ty("t2", "Chair", "Spare"),       # Chair used, Spare unused
        _ty("t3", "OldTable", "A"), _ty("t4", "OldTable", "B"),       # whole family unused
        _ty("t5", "Mass Blob", "Blob", "inplace"),                    # in-place, used
        _ty("t6", "Wall", "Generic", "system"),                       # system, unused: type-level only
    ] + [_ty(f"d{i}", "Door Mega", f"D{i}") for i in range(30)]       # large family
    elements = [
        _el(1, "Chair", "Std", "t1"), _el(2, "Chair", "Std", "t1"),
        _el(3, "Mass Blob", "Blob", "t5"),
        _el(4, None, "site-plan.dwg", cls="ImportInstance"),
        _el(5, None, "xref.dwg", cls="ImportInstance", params={"IsLinked": {"v": True}}),
    ] + [_el(10 + i, "Door Mega", f"D{i}", f"d{i}") for i in range(30)]
    return _write(tmp_path, elements, types)


def test_flags_everything_and_sorts_by_impact(tmp_path, fixture_snapshot):
    r = ModelBloatModule().audit(snapshot_id=fixture_snapshot, workspace=WS(tmp_path))
    assert r["read_only"] is True and r["usage_counts_available"] is True
    assert [f["family"] for f in r["unused_families"]["items"]] == ["OldTable"]
    unused_types = {(t["family"], t["type_name"]) for t in r["unused_types"]["items"]}
    assert ("Chair", "Spare") in unused_types and ("Wall", "Generic") in unused_types
    assert ("Chair", "Std") not in unused_types
    assert [f["family"] for f in r["in_place_families"]["items"]] == ["Mass Blob"]
    assert r["in_place_families"]["items"][0]["placed_instances"] == 1
    assert r["families_with_very_many_types"]["items"][0]["type_count"] == 30
    cad = {c["name"]: c["kind"] for c in r["imported_cad"]["items"]}
    assert cad == {"site-plan.dwg": "imported", "xref.dwg": "linked"}
    assert r["imported_cad"]["items"][0]["name"] == "site-plan.dwg"  # worst first
    # headline starts with the heaviest issue (imported CAD)
    assert "imported CAD" in r["headline_findings"][0]
    assert 0 <= r["cleanliness"]["score"] < 100
    assert "Nothing has been deleted" in " ".join(r["notes"])
    assert "approved plan" in " ".join(r["notes"])


def test_threshold_and_max_items(tmp_path, fixture_snapshot):
    r = ModelBloatModule().audit(snapshot_id=fixture_snapshot, workspace=WS(tmp_path),
                                 large_type_threshold=40, max_items=1)
    assert r["families_with_very_many_types"]["total"] == 0
    assert r["unused_types"]["total"] == 2 and r["unused_types"]["shown"] == 1


def test_matches_by_family_and_type_name_without_uid(tmp_path):
    sid = _write(tmp_path, [_el(1, "Chair", "Std")], [_ty("t1", "Chair", "Std"), _ty("t2", "Chair", "Spare")])
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert [t["type_name"] for t in r["unused_types"]["items"]] == ["Spare"]


def test_no_instance_data_is_reported_not_guessed(tmp_path):
    sid = _write(tmp_path, [], [_ty("t1", "Chair", "Std"), _ty("t2", "Blob", "B", "inplace")])
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert r["usage_counts_available"] is False
    assert r["unused_families"]["total"] == 0 and r["unused_types"]["total"] == 0
    assert r["in_place_families"]["total"] == 1
    assert r["in_place_families"]["items"][0]["placed_instances"] is None
    assert "could not be worked out" in " ".join(r["notes"])


def test_clean_model(tmp_path):
    sid = _write(tmp_path, [_el(1, "Chair", "Std", "t1")], [_ty("t1", "Chair", "Std")])
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert r["cleanliness"]["score"] == 100 and r["headline_findings"] == []


def test_missing_snapshot_and_mock_snapshot(tmp_path):
    with pytest.raises(ValueError):
        ModelBloatModule().audit(snapshot_id="nope", workspace=WS(tmp_path))
    r = ModelBloatModule().audit(workspace=WS(tmp_path))
    assert r["read_only"] is True and "summary" in r


def test_module_is_registered_as_read_only_tool(tmp_path):
    from revit_mcp_server.config import Config
    from revit_mcp_server.module_registry import ModuleRegistry
    from revit_mcp_server.providers.module_provider import ModuleProvider
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    cfg = Config(workspace_dir=tmp_path, allowed_directories=[tmp_path],
                 audit_log=tmp_path / "audit.log", enable_user_modules=False)
    registry = ModuleRegistry(config_obj=cfg)
    registry.discover_and_load()
    assert registry.get_module("model_bloat") is not None
    provider = ModuleProvider(module_registry=registry, workspace=WorkspaceMonitor([tmp_path]))
    tools = {c.name: c for c in provider.get_capabilities()}
    assert "model_bloat_audit" in tools
    assert tools["model_bloat_audit"].is_mutating is False
