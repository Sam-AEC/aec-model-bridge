"""Tests for the naming_checker module (checks names against a user-supplied convention)."""
import importlib.util
import json
from pathlib import Path

import pytest

from revit_mcp_server.semantic.engine import generate_mock_snapshot


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_nc = _load_mod("src/revit_mcp_server/modules/naming_checker/module.py", "_naming_checker_impl")
NamingCheckerModule = _nc.NamingCheckerModule

CONVENTION = {
    "pattern": "{project}-{originator}-{level}-{number}",
    "fields": {
        "project": {"allowed": ["PRJ1"]},
        "originator": {"allowed": ["ABC", "XYZ"]},
        "level": ["00", "01"],
        "number": {"regex": "[0-9]{4}"},
    },
}


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def module():
    return NamingCheckerModule()


def _one(module, name, convention=CONVENTION, kind="file_names"):
    res = module.check_names(convention=convention, names={kind: [name]})
    assert res["summary"]["checked"] == 1
    return res["results"][0]


def test_pass(module):
    res = module.check_names(
        convention=CONVENTION,
        names={"file_names": ["PRJ1-ABC-00-0001", "PRJ1-XYZ-01-1234"]},
    )
    assert res["summary"] == {"checked": 2, "passed": 2, "failed": 0, "not_checked": 0}
    assert res["results"][0]["fields"]["originator"] == "ABC"
    assert res["by_kind"]["file_names"]["passed"] == 2
    assert "ISO 19650" in res["disclaimer"]  # says it does NOT check against it


@pytest.mark.parametrize(
    "name,field",
    [
        ("BAD1-ABC-00-0001", "project"),
        ("PRJ1-QQQ-00-0001", "originator"),
        ("PRJ1-ABC-09-0001", "level"),
        ("PRJ1-ABC-00-12", "number"),
    ],
)
def test_each_field_failure(module, name, field):
    r = _one(module, name)
    assert r["passed"] is False
    assert [f["field"] for f in r["failures"]] == [field]
    assert r["failures"][0]["reason"]


def test_multiple_field_failures_and_counts(module):
    res = module.check_names(
        convention=CONVENTION,
        names={"file_names": ["PRJ1-ABC-00-0001", "NOPE-QQQ-00-0001"]},
    )
    assert res["summary"]["failed"] == 1
    assert res["failures_by_field"] == {"project": 1, "originator": 1}


def test_wrong_structure_gives_part_count_hint(module):
    r = _one(module, "PRJ1-ABC-0001")
    assert r["failures"][0]["field"] == "(whole name)"
    assert "4 parts" in r["failures"][0]["reason"]


def test_spaces_and_empty_name(module):
    assert _one(module, " PRJ1-ABC-00-0001")["failures"][0]["reason"].startswith("has spaces")
    assert _one(module, "")["failures"][0]["reason"] == "is empty"


def test_empty_field_value(module):
    r = _one(module, "PRJ1--00-0001")
    assert [f["field"] for f in r["failures"]] == ["originator"]
    assert r["failures"][0]["reason"] == "is empty"


def test_ignore_case_and_length_rules(module):
    conv = {
        "pattern": "{a}_{b}",
        "fields": {
            "a": {"allowed": ["Wall"], "ignore_case": True},
            "b": {"min_length": 2, "max_length": 3},
        },
    }
    assert _one(module, "WALL_ab", conv)["passed"]
    assert not _one(module, "Wall_a", conv)["passed"]
    assert not _one(module, "Wall_abcd", conv)["passed"]
    assert not _one(module, "Floor_ab", conv)["passed"]


def test_adjacent_fixed_length_fields(module):
    conv = {"pattern": "{a}{b}", "fields": {"a": {"length": 2}, "b": {"regex": "[0-9]+"}}}
    assert _one(module, "AB123", conv)["passed"]
    assert _one(module, "AB12x", conv)["failures"][0]["field"] == "b"


@pytest.mark.parametrize(
    "conv,fragment",
    [
        ({"pattern": "", "fields": {}}, "needs a 'pattern'"),
        ({"fields": {}}, "needs a 'pattern'"),
        ({"pattern": "no fields here", "fields": {}}, "no {field}"),
        ({"pattern": "{a}-{b", "fields": {"a": {}, "b": {}}}, "unmatched"),
        ({"pattern": "{a}-{}", "fields": {"a": {}}}, "invalid field name"),
        ({"pattern": "{a}-{a}", "fields": {"a": {}}}, "same field twice"),
        ({"pattern": "{a}-{b}", "fields": {"a": {}}}, "No rules given"),
        ({"pattern": "{a}", "fields": {"a": {}, "z": {}}}, "not in the pattern"),
        ({"pattern": "{a}{b}", "fields": {"a": {}, "b": {}}}, "next to each other"),
        ({"pattern": "{a}", "fields": {"a": {"regex": "(["}}}, "regex is not valid"),
        ({"pattern": "{a}", "fields": {"a": {"allowed": []}}}, "nothing could ever pass"),
        ({"pattern": "{a}", "fields": {"a": {"colour": "red"}}}, "unknown settings"),
        ({"pattern": "{a b}", "fields": {"a b": {}}}, "invalid field name"),
        ({"by_kind": {"nonsense": {"pattern": "{a}", "fields": {"a": {}}}}}, "Unknown kind"),
    ],
)
def test_bad_pattern_is_rejected_with_plain_message(module, conv, fragment):
    with pytest.raises(ValueError) as exc:
        module.check_names(convention=conv, names={"file_names": ["x"]})
    assert fragment in str(exc.value)


def test_missing_convention_is_rejected(module):
    with pytest.raises(ValueError, match="no built-in convention"):
        module.check_names(names={"file_names": ["x"]})


def test_unknown_kind_rejected(module):
    with pytest.raises(ValueError, match="Unknown kind"):
        module.check_names(convention=CONVENTION, names={"room_names": ["x"]})


def test_empty_input(module):
    res = module.check_names(convention=CONVENTION)
    assert res["summary"] == {"checked": 0, "passed": 0, "failed": 0, "not_checked": 0}
    assert res["results"] == []
    assert any("nothing was checked" in n for n in res["notes"])
    res = module.check_names(convention=CONVENTION, names={"file_names": []})
    assert res["summary"]["checked"] == 0


def test_unicode_names(module):
    conv = {
        "pattern": "{zone}-{name}",
        "fields": {"zone": {"allowed": ["Ünïcode", "東京"]}, "name": {"regex": r"\w+"}},
    }
    assert _one(module, "東京-ビル", conv)["passed"]
    # decomposed (NFD) input is normalised, so it still matches the composed value
    assert _one(module, "Ünı̈code-Åäö".replace("nı̈", "nï"), conv)["passed"] is True
    r = _one(module, "Москва-дом", conv)
    assert r["failures"][0]["field"] == "zone"
    assert "Москва" in r["failures"][0]["reason"]


def test_by_kind_and_skipped_kinds(module):
    conv = {"by_kind": {"level_names": {"pattern": "L{n}", "fields": {"n": {"regex": "[0-9]{2}"}}}}}
    res = module.check_names(
        convention=conv,
        names={"level_names": ["L01", "Level 1"], "view_names": ["whatever"]},
    )
    assert res["summary"] == {"checked": 2, "passed": 1, "failed": 1, "not_checked": 1}
    assert any("view names not checked" in n for n in res["notes"])


def test_kinds_filter(module):
    res = module.check_names(
        convention=CONVENTION,
        names={"file_names": ["bad"], "view_names": ["bad"]},
        kinds=["view_names"],
    )
    assert list(res["by_kind"]) == ["view_names"]


def test_example_files_are_labelled_and_valid(module):
    listing = module.list_example_conventions()
    names = {e["name"] for e in listing["examples"]}
    assert names == {"example_file_names", "example_sheets_views_levels"}
    for e in listing["examples"]:
        assert e["label"].startswith("EXAMPLE ONLY")
        assert e["covers"]
    for name in names:
        data = module._load_convention_file(name, None)
        _nc._parse_conventions(data)  # does not raise


def test_example_file_checks(module):
    res = module.check_names(
        convention_file="example_file_names",
        names={"file_names": ["PRJ1-ABC-ZZ-00-M3-A-0001", "PRJ1-ABC-ZZ-00-M3-Q-0001"]},
    )
    assert res["summary"]["passed"] == 1
    assert res["results"][1]["failures"][0]["field"] == "role"

    res = module.check_names(
        convention_file="example_sheets_views_levels",
        names={
            "sheet_numbers": ["A-GA-101", "A-GA-1"],
            "sheet_names": ["Architecture - Ground floor plan"],
            "view_names": ["WORK_L01_Plan"],
            "level_names": ["L01", "Level 1"],
            "grid_names": ["A", "12", "AA"],
        },
    )
    assert res["summary"]["checked"] == 9
    assert res["summary"]["failed"] == 3


def test_convention_file_in_workspace_and_traversal(module, tmp_path):
    ws = MockWorkspace(tmp_path)
    (tmp_path / "mine.json").write_text(json.dumps(CONVENTION), encoding="utf-8")
    res = module.check_names(convention_file="mine.json", names={"file_names": ["PRJ1-ABC-00-0001"]}, workspace=ws)
    assert res["summary"]["passed"] == 1
    with pytest.raises(ValueError, match="inside the workspace"):
        module.check_names(convention_file="../outside.json", names={"file_names": ["x"]}, workspace=ws)


def test_snapshot_names(module, tmp_path):
    ws = MockWorkspace(tmp_path)
    snap = generate_mock_snapshot()
    snap.source.doc_title = "PRJ1-ABC-00-0001"
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        snap.model_dump_json(by_alias=True), encoding="utf-8"
    )
    conv = {
        "by_kind": {
            "file_names": CONVENTION,
            "level_names": {"pattern": "Level {n}", "fields": {"n": {"regex": "[0-9]"}}},
        }
    }
    res = module.check_names(convention=conv, snapshot_id=snap.snapshot_id, workspace=ws)
    assert res["by_kind"]["file_names"]["passed"] == 1
    assert res["by_kind"]["level_names"] == {"checked": 2, "passed": 2, "failed": 0}
    with pytest.raises(ValueError, match="not found"):
        module.check_names(convention=conv, snapshot_id="missing", workspace=ws)
    with pytest.raises(ValueError, match="not found"):
        module.check_names(convention=conv, snapshot_id="../x", workspace=ws)
