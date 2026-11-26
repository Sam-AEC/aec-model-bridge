"""docs/examples/rule_packs/door-fire-rating.yaml: door rating against host wall rating."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from revit_mcp_server.semantic.engine import generate_mock_snapshot
from revit_mcp_server.semantic.models import ElementRecord, ParamVal

PACK = Path(__file__).resolve().parents[3] / "docs" / "examples" / "rule_packs" / "door-fire-rating.yaml"
_spec = importlib.util.spec_from_file_location(
    "_qaqc_fire_impl", Path(__file__).parent.parent / "src/revit_mcp_server/modules/qaqc_checker/module.py")
_qaqc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_qaqc)


class _WS:
    def __init__(self, root: Path):
        self.allowed_directories = [root]


def _wall(uid, element_id, rating=None, param="Fire Rating"):
    params = {param: ParamVal(v=rating, storage="String")} if rating is not None else {}
    return ElementRecord(uid=uid, element_id=element_id, category="OST_Walls", cls="Wall", params=params)


def _door(uid, element_id, host, rating=None, param="Fire Rating"):
    params = {"Mark": ParamVal(v=uid, storage="String")}
    if rating is not None:
        params[param] = ParamVal(v=rating, storage="String")
    return ElementRecord(uid=uid, element_id=element_id, category="OST_Doors", cls="FamilyInstance",
                         type_name="Door", host_uid=host, params=params)


def _run(tmp_path, elements, pack_text=None):
    snap = generate_mock_snapshot()
    snap.elements = [e for e in snap.elements if e.category not in ("OST_Doors", "OST_Walls")] + elements
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        snap.model_dump_json(by_alias=True), encoding="utf-8")
    (tmp_path / "rule_packs").mkdir()
    target = tmp_path / "rule_packs" / "door-fire-rating.yaml"
    if pack_text is None:
        shutil.copy(PACK, target)
    else:
        target.write_text(pack_text, encoding="utf-8")
    result = _qaqc.QaqcCheckerModule().run_check(
        snapshot_id=snap.snapshot_id, rule_pack="door-fire-rating", workspace=_WS(tmp_path))
    return sorted((f["rule_id"], f["element_uid"]) for f in result["findings"])


def _fixture(param="Fire Rating"):
    return [
        _wall("w60", 901, "60", param), _wall("w-none", 902), _wall("w-empty", 903, "", param),
        _door("d-low", 911, "w60", "30", param),
        _door("d-equal", 912, "w60", "60", param),
        _door("d-high", 913, "w60", "90", param),
        _door("d-none", 914, "w60", None, param),
        _door("d-in-unrated", 915, "w-none", "30", param),
        _door("d-in-empty", 916, "w-empty", "30", param),
    ]


def test_pack_validates():
    result = _qaqc._validate_file(PACK)
    assert result["errors"] == [] and result["warnings"] == []


def test_reports_under_rated_and_unrated_doors_and_walls(tmp_path):
    assert _run(tmp_path, _fixture()) == [
        ("door_fire_rating_below_wall", "d-low"),
        ("door_fire_rating_missing", "d-none"),
        ("host_wall_fire_rating_missing", "d-in-empty"),
        ("host_wall_fire_rating_missing", "d-in-unrated"),
    ]


def test_parameter_name_is_set_in_the_pack(tmp_path):
    text = PACK.read_text(encoding="utf-8").replace("Fire Rating", "FireRating_EI")
    assert _run(tmp_path, _fixture("FireRating_EI"), text) == [
        ("door_fire_rating_below_wall", "d-low"),
        ("door_fire_rating_missing", "d-none"),
        ("host_wall_fire_rating_missing", "d-in-empty"),
        ("host_wall_fire_rating_missing", "d-in-unrated"),
    ]


@pytest.mark.parametrize("rating", ["30", "60"])
def test_rating_equal_or_higher_passes(tmp_path, rating):
    found = _run(tmp_path, [_wall("w30", 901, rating), _door("d", 911, "w30", "60")])
    assert found == []
