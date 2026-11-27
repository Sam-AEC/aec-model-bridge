import asyncio
import json
import os

import pytest
from mcp import types

from revit_mcp_server import mcp_completions, mcp_server
from revit_mcp_server.security.workspace import WorkspaceMonitor


def _write(tmp_path, snapshot_id, elements, mtime=None, raw=None):
    folder = tmp_path / "snapshots"
    folder.mkdir(exist_ok=True)
    path = folder / f"{snapshot_id}.json"
    path.write_text(raw if raw is not None else json.dumps({"elements": elements}), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


ELEMENTS = [
    {"uid": "1", "category": "OST_Doors", "params": {"Mark": {"v": "D1"}, "Fire Rating": {"v": "60"}}},
    {"uid": "2", "category": "OST_Walls", "params": {"Width": {"v": 200}}},
    {"uid": "3", "category": "OST_Windows", "params": {"Mark": {"v": "W1"}}},
    {"uid": "4", "category": "OST_Levels", "name": "Level 1", "params": {}},
    {"uid": "5", "category": "OST_Levels", "params": {"DATUM_TEXT": {"v": "Level 2"}}},
    {"uid": "6", "category": "OST_Levels", "params": {"Name": "Roof"}},
]


def _values(tmp_path, name, typed):
    return mcp_completions.complete(tmp_path, name, typed).values


def test_category_prefix_from_newest_snapshot(tmp_path):
    _write(tmp_path, "old", [{"category": "OST_Doors"}, {"category": "OST_Walls"}], mtime=1_000)
    _write(tmp_path, "new", ELEMENTS, mtime=2_000)
    assert _values(tmp_path, "category", "OST_W") == ["OST_Walls", "OST_Windows"]
    assert _values(tmp_path, "category", "ost_d") == ["OST_Doors"]
    assert _values(tmp_path, "category", "Win") == ["OST_Windows"]
    assert "OST_Walls" in _values(tmp_path, "category", "")


def test_old_snapshot_values_not_offered(tmp_path):
    _write(tmp_path, "old", [{"category": "OST_Furniture"}], mtime=1_000)
    _write(tmp_path, "new", ELEMENTS, mtime=2_000)
    assert _values(tmp_path, "category", "OST_F") == []


def test_level_names(tmp_path):
    _write(tmp_path, "s", ELEMENTS)
    assert _values(tmp_path, "level", "") == ["Level 1", "Level 2", "Roof"]
    assert _values(tmp_path, "level", "level 2") == ["Level 2"]


def test_parameter_names(tmp_path):
    _write(tmp_path, "s", ELEMENTS)
    assert _values(tmp_path, "parameter", "") == ["DATUM_TEXT", "Fire Rating", "Mark", "Name", "Width"]
    assert _values(tmp_path, "parameter", "ma") == ["Mark"]


def test_no_snapshot_gives_empty_list(tmp_path):
    result = mcp_completions.complete(tmp_path, "category", "OST")
    assert result.values == [] and result.hasMore is False
    assert mcp_completions.complete(None, "category", "OST").values == []


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", json.dumps({"elements": "x"}), json.dumps({"elements": [1, None]})])
def test_unreadable_snapshot_gives_empty_list(tmp_path, raw):
    _write(tmp_path, "bad", [], raw=raw)
    assert _values(tmp_path, "category", "") == []


def test_unknown_argument_gives_empty_list(tmp_path):
    _write(tmp_path, "s", ELEMENTS)
    assert _values(tmp_path, "rule_pack", "") == []
    assert _values(tmp_path, "value", "") == []


def test_capped_at_100_with_has_more(tmp_path):
    _write(tmp_path, "s", [{"category": f"OST_Cat{i:03d}"} for i in range(150)])
    result = mcp_completions.complete(tmp_path, "category", "OST_Cat")
    assert len(result.values) == 100 and result.total == 150 and result.hasMore is True
    assert result.values == sorted(result.values)


def test_server_handler_and_capability(tmp_path, monkeypatch):
    from mcp.server.lowlevel.server import NotificationOptions

    _write(tmp_path, "s", ELEMENTS)
    monkeypatch.setattr(mcp_server, "workspace_monitor", WorkspaceMonitor([tmp_path]))
    assert types.CompleteRequest in mcp_server.app.request_handlers
    caps = mcp_server.app.get_capabilities(NotificationOptions(), {})
    assert caps.completions is not None

    def ask(ref, name, value):
        req = types.CompleteRequest(
            method="completion/complete",
            params=types.CompleteRequestParams(ref=ref, argument=types.CompletionArgument(name=name, value=value)),
        )
        return asyncio.run(mcp_server.app.request_handlers[types.CompleteRequest](req)).root.completion

    prompt = types.PromptReference(type="ref/prompt", name="parameter_fix")
    assert ask(prompt, "category", "OST_Do").values == ["OST_Doors"]
    assert ask(prompt, "parameter", "Fi").values == ["Fire Rating"]
    template = types.ResourceTemplateReference(type="ref/resource", uri="aec://snapshot/{id}/summary")
    assert ask(template, "level", "Ro").values == ["Roof"]
    assert ask(template, "id", "").values == []


def test_server_handler_without_workspace(monkeypatch):
    monkeypatch.setattr(mcp_server, "workspace_monitor", None)
    out = asyncio.run(mcp_server.complete(
        types.PromptReference(type="ref/prompt", name="qa_review"),
        types.CompletionArgument(name="category", value="OST"), None))
    assert out.values == []
