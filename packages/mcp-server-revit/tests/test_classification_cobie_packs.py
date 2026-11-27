"""docs/examples/rule_packs: Uniclass, OmniClass and COBie completeness packs, run on fixture snapshots."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from revit_mcp_server.semantic.engine import generate_mock_snapshot
from revit_mcp_server.semantic.models import ElementRecord, ParamVal, TypeRecord

PACKS = Path(__file__).resolve().parents[3] / "docs" / "examples" / "rule_packs"
_spec = importlib.util.spec_from_file_location(
    "_qaqc_class_impl", Path(__file__).parent.parent / "src/revit_mcp_server/modules/qaqc_checker/module.py")
_qaqc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_qaqc)

CATEGORIES = ("OST_Doors", "OST_Windows", "OST_MechanicalEquipment", "OST_ElectricalEquipment", "OST_PlumbingFixtures")


class _WS:
    def __init__(self, root: Path):
        self.allowed_directories = [root]


def _el(uid, element_id, params=None, category="OST_Doors", type_uid=None):
    return ElementRecord(
        uid=uid, element_id=element_id, category=category, cls="FamilyInstance", type_name="T", type_uid=type_uid,
        params={k: ParamVal(v=v, storage="String") for k, v in (params or {}).items()})


def _run(tmp_path, pack, elements, types=(), text=None):
    snap = generate_mock_snapshot()
    snap.elements = [e for e in snap.elements if e.category not in CATEGORIES] + list(elements)
    snap.types = [t for t in snap.types if t.category not in CATEGORIES] + list(types)
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        snap.model_dump_json(by_alias=True), encoding="utf-8")
    (tmp_path / "rule_packs").mkdir()
    target = tmp_path / "rule_packs" / f"{pack}.yaml"
    if text is None:
        shutil.copy(PACKS / f"{pack}.yaml", target)
    else:
        target.write_text(text, encoding="utf-8")
    result = _qaqc.QaqcCheckerModule().run_check(snapshot_id=snap.snapshot_id, rule_pack=pack, workspace=_WS(tmp_path))
    assert not [r for r in result["rules"] if "error" in r], result["rules"]
    return sorted((f["rule_id"], f["element_uid"]) for f in result["findings"])


@pytest.mark.parametrize("pack, rule_count", [
    ("classification-uniclass", 3), ("classification-omniclass", 3), ("cobie-completeness", 10)])
def test_pack_validates(pack, rule_count):
    result = _qaqc._validate_file(PACKS / f"{pack}.yaml")
    assert result["errors"] == [] and result["warnings"] == []
    assert result["rules_count"] == rule_count


# ------------------------------------------------------------------ Uniclass

def test_uniclass_pass_and_fail(tmp_path):
    key = "Uniclass Code"
    elements = [
        _el("ok-pr", 901, {key: "Pr_20_93_52"}),
        _el("ok-ss", 902, {key: "Ss_25_10_30"}, "OST_Windows"),
        _el("ok-ef", 903, {key: "EF_25_10"}, "OST_MechanicalEquipment"),
        _el("empty", 904, {key: ""}),
        _el("not-captured", 905),
        _el("no-prefix", 906, {key: "20_93_52"}),
        _el("space", 907, {key: "Pr_20 93_52"}),
        _el("dots-prefix", 908, {key: "Pr.20.93.52"}),
        _el("trailing", 909, {key: "Pr_20_93_"}),
        _el("lowercase", 910, {key: "pr_20_93_52"}),
        _el("other-category", 911, {key: "bad"}, "OST_Walls"),
    ]
    assert _run(tmp_path, "classification-uniclass", elements) == [
        ("uniclass_code_format", "dots-prefix"),
        ("uniclass_code_format", "lowercase"),
        ("uniclass_code_format", "no-prefix"),
        ("uniclass_code_format", "space"),
        ("uniclass_code_format", "trailing"),
        ("uniclass_code_missing", "empty"),
        ("uniclass_code_not_captured", "not-captured"),
    ]


def test_uniclass_all_valid_has_no_findings(tmp_path):
    elements = [_el(f"d{i}", 900 + i, {"Uniclass Code": "Pr_20_93_52"}, c) for i, c in enumerate(CATEGORIES)]
    assert _run(tmp_path, "classification-uniclass", elements) == []


def test_uniclass_parameter_name_is_set_in_the_pack(tmp_path):
    text = (PACKS / "classification-uniclass.yaml").read_text(encoding="utf-8").replace("Uniclass Code", "UC")
    elements = [
        _el("ok", 901, {"UC": "Pr_20_93_52"}),
        _el("bad", 902, {"UC": "x"}),
        _el("default-name", 903, {"Uniclass Code": "Pr_1"}),
    ]
    assert _run(tmp_path, "classification-uniclass", elements, text=text) == [
        ("uniclass_code_format", "bad"), ("uniclass_code_not_captured", "default-name")]


# ----------------------------------------------------------------- OmniClass

def test_omniclass_pass_and_fail(tmp_path):
    key = "OmniClass Number"
    elements = [
        _el("ok-23", 901, {key: "23-13 11 11"}),
        _el("ok-21", 902, {key: "21-02 10 10"}, "OST_Windows"),
        _el("ok-22", 903, {key: "22-08 11 00"}, "OST_PlumbingFixtures"),
        _el("empty", 904, {key: ""}),
        _el("not-captured", 905),
        _el("dotted", 906, {key: "23.13.11.11"}),
        _el("underscored", 907, {key: "23_13_11_11"}),
        _el("wrong-table", 908, {key: "41-13 11 11"}),
        _el("double-space", 909, {key: "23-13  11 11"}),
        _el("trailing-space", 910, {key: "23-13 11 "}),
        _el("other-category", 911, {key: "bad"}, "OST_Walls"),
    ]
    assert _run(tmp_path, "classification-omniclass", elements) == [
        ("omniclass_number_format", "dotted"),
        ("omniclass_number_format", "double-space"),
        ("omniclass_number_format", "trailing-space"),
        ("omniclass_number_format", "underscored"),
        ("omniclass_number_format", "wrong-table"),
        ("omniclass_number_missing", "empty"),
        ("omniclass_number_not_captured", "not-captured"),
    ]


def test_omniclass_all_valid_has_no_findings(tmp_path):
    elements = [_el(f"d{i}", 900 + i, {"OmniClass Number": "23-13 11 11"}, c) for i, c in enumerate(CATEGORIES)]
    assert _run(tmp_path, "classification-omniclass", elements) == []


# --------------------------------------------------------------------- COBie

COMPONENT = ("COBie Component Name", "COBie Component Space")
TYPE = ("COBie Type Name", "COBie Type Category", "COBie Type Manufacturer")


def _type(uid, **params):
    return TypeRecord(uid=uid, category="OST_Doors", family="F", type_name=uid,
                      params={k: ParamVal(v=v, storage="String") for k, v in params.items()})


def _full_type(uid="t-full"):
    return _type(uid, **{k: "x" for k in TYPE})


def test_cobie_complete_has_no_findings(tmp_path):
    elements = [_el("full", 901, {k: "x" for k in COMPONENT}, type_uid="t-full")]
    assert _run(tmp_path, "cobie-completeness", elements, [_full_type()]) == []


def test_cobie_reports_empty_and_not_captured_fields(tmp_path):
    types = [
        _full_type(),
        _type("t-partial", **{"COBie Type Name": "x", "COBie Type Category": "", "COBie Type Manufacturer": "x"}),
        _type("t-bare"),
    ]
    elements = [
        _el("complete", 901, {k: "x" for k in COMPONENT}, type_uid="t-full"),
        _el("empty-name", 902, {"COBie Component Name": "", "COBie Component Space": "x"}, type_uid="t-full"),
        _el("no-space", 903, {"COBie Component Name": "x"}, type_uid="t-full"),
        _el("partial-type", 904, {k: "x" for k in COMPONENT}, "OST_Windows", type_uid="t-partial"),
        _el("bare-type", 905, {k: "x" for k in COMPONENT}, "OST_MechanicalEquipment", type_uid="t-bare"),
        _el("untyped", 906, {k: "x" for k in COMPONENT}, "OST_ElectricalEquipment"),
        _el("other-category", 907, {}, "OST_Walls"),
    ]
    expected = [
        ("cobie_component_name_missing", "empty-name"),
        ("cobie_component_space_not_captured", "no-space"),
        ("cobie_type_category_missing", "partial-type"),
    ]
    for rule in ("cobie_type_name", "cobie_type_category", "cobie_type_manufacturer"):
        expected += [(f"{rule}_not_captured", "bare-type"), (f"{rule}_not_captured", "untyped")]
    assert _run(tmp_path, "cobie-completeness", elements, types) == sorted(expected)


def test_cobie_dotted_names_cannot_be_read_by_pipelines(tmp_path):
    text = (PACKS / "cobie-completeness.yaml").read_text(encoding="utf-8").replace(
        "COBie Component Name", "COBie.Component.Name")
    elements = [_el("named", 901, {"COBie.Component.Name": "x", "COBie Component Space": "x"}, type_uid="t-full")]
    found = _run(tmp_path, "cobie-completeness", elements, [_full_type()], text=text)
    assert found == [("cobie_component_name_not_captured", "named")]
