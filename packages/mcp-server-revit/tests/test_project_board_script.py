"""Label to field mapping for scripts/project_board.py."""

import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[3] / "scripts" / "project_board.py"
_spec = importlib.util.spec_from_file_location("project_board", _path)
board = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(board)


def test_labels_map_to_fields():
    values = board.fields_from_labels(
        ["priority: P1", "size: M", "area: security", "area: approval", "status: maintainer-only"]
    )
    assert values == {
        "Priority": "P1",
        "Size": "M",
        "Area": "approval",
        "Owner": "Maintainer",
        "Needs Revit": "No",
    }


@pytest.mark.parametrize(
    ("labels", "owner"),
    [(["good first issue"], "Community"), (["help wanted"], "Community"), ([], "Open")],
)
def test_owner(labels, owner):
    assert board.fields_from_labels(labels)["Owner"] == owner


def test_pull_requests_get_no_owner_and_unknown_labels_are_ignored():
    values = board.fields_from_labels(["priority: P9", "area: nowhere", "type: bug"], is_pr=True)
    assert values == {"Needs Revit": "No"}


def test_needs_revit():
    assert board.fields_from_labels(["status: needs-live-verification"])["Needs Revit"] == "Yes"


def test_field_set_and_area_order():
    assert board.AREAS == sorted(board.AREAS)
    assert set(board.FIELDS) == {"Priority", "Size", "Area", "Owner", "Needs Revit"}


def test_removed_labels_clear_their_fields():
    values = board.fields_from_labels(["size: S"], is_pr=True)
    assert board.fields_to_clear(values) == ["Priority", "Area", "Owner"]
    assert board.fields_to_clear(board.fields_from_labels(
        ["priority: P0", "size: L", "area: ci", "help wanted"])) == []
