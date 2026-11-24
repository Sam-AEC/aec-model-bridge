"""Record bridge traffic to a cassette and replay it without Revit (MCP_REVIT_RECORD, MCP_REVIT_MODE=replay)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from revit_mcp_server.bridge import cassette
from revit_mcp_server.bridge.cassette import CassetteError, ReplayBridge
from revit_mcp_server.config import BridgeMode, config
from revit_mcp_server.errors import BridgeError, CommandFailed
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

SAMPLE = Path(__file__).parent / "fixtures" / "cassettes" / "sample_session.jsonl"


class _LiveBridge:
    """Stands in for BridgeClient: answers like the add-in after unwrapping."""

    def __init__(self):
        self.calls = []

    def send_tool(self, tool, payload):
        self.calls.append((tool, payload))
        if payload.get("category") == "Bad":
            raise CommandFailed("Bridge error: Unknown category 'Bad'", payload={"hint": "check C:\\Users\\jdoe\\x.rvt"})
        return {
            "title": "Office",
            "path": "C:\\Users\\jdoe\\Projects\\Office.rvt",
            "central": "\\\\server\\share\\Office.rvt",
            "session_token": "abc123secretvalue",
            "last_saved_by": "jdoe",
            "note": "opened by jdoe, mail jdoe@example.com",
            "elements": [1, 2],
        }


@pytest.fixture
def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "workspace_dir", tmp_path)
    monkeypatch.setenv("USER", "jdoe")
    monkeypatch.setenv("MCP_REVIT_RECORD", "case1")
    live = _LiveBridge()
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
                             bridge_url="http://127.0.0.1:1", bridge_factory=lambda url, token=None: live)
    return provider, live, tmp_path / "cassettes" / "case1.jsonl"


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_recorder_writes_scrubbed_jsonl_under_workspace_cassettes(recording):
    provider, live, path = recording
    result = asyncio.run(provider.execute_tool("revit_get_document_info", {}))
    assert result["path"].startswith("C:\\Users")  # the live caller still gets the real answer
    [entry] = _lines(path)
    assert entry["seq"] == 1 and entry["v"] == 1 and entry["ok"] is True
    assert entry["tool"] == "revit_get_document_info" and entry["command"] == "revit.get_document_info"
    text = path.read_text(encoding="utf-8")
    for leaked in ("jdoe", "abc123secretvalue", "C:\\\\Users", "server\\\\share", "example.com"):
        assert leaked not in text, leaked
    response = entry["response"]
    assert response["path"] == "<redacted-path>" and response["central"] == "<redacted-path>"
    assert response["session_token"] == "<redacted>"
    assert response["last_saved_by"] == "<redacted-user>"
    assert response["elements"] == [1, 2]


def test_recorder_keeps_errors_and_drops_volatile_params(recording):
    provider, live, path = recording
    with pytest.raises(CommandFailed):
        asyncio.run(provider.execute_tool("revit_list_elements", {"category": "Bad", "request_id": "r-1"}))
    [entry] = _lines(path)
    assert entry["ok"] is False and entry["error"]["type"] == "CommandFailed"
    assert "request_id" not in entry["params"]
    assert "jdoe" not in json.dumps(entry)


def test_recorded_session_replays_without_revit(recording, monkeypatch, tmp_path):
    provider, live, path = recording
    first = asyncio.run(provider.execute_tool("revit_list_elements", {"category": "Walls"}))
    monkeypatch.delenv("MCP_REVIT_RECORD")
    monkeypatch.setenv("MCP_REVIT_CASSETTE", str(path))
    replay = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.replay)
    again = asyncio.run(replay.execute_tool("revit_list_elements", {"category": "Walls"}))
    assert again["elements"] == first["elements"] and again["path"] == "<redacted-path>"
    assert len(live.calls) == 1
    assert asyncio.run(replay.check_health()) == {"status": "healthy", "mode": "replay"}


@pytest.mark.parametrize("value", ["../escape", "C:\\temp\\x", "a/b", "name.jsonl", "x" * 65])
def test_record_name_that_is_a_path_fails_closed(value, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "workspace_dir", tmp_path)
    monkeypatch.setenv("MCP_REVIT_RECORD", value)
    live = _LiveBridge()
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
                             bridge_url="http://127.0.0.1:1", bridge_factory=lambda url, token=None: live)
    with pytest.raises(BridgeError, match="plain cassette name"):
        asyncio.run(provider.execute_tool("revit_list_levels", {}))
    assert live.calls == []
    assert not (tmp_path / "cassettes").exists()


def test_record_on_value_picks_a_timestamped_name(tmp_path):
    path = cassette.cassette_path(tmp_path, "true")
    assert path.parent == (tmp_path / "cassettes").resolve()
    assert path.name.startswith("session-") and path.suffix == ".jsonl"


def test_mock_mode_never_records(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "workspace_dir", tmp_path)
    monkeypatch.setenv("MCP_REVIT_RECORD", "mock1")
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    asyncio.run(provider.execute_tool("revit_list_levels", {}))
    assert not (tmp_path / "cassettes").exists()


def test_replay_unmatched_request_fails_with_plain_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_CASSETTE", str(SAMPLE))
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.replay)
    with pytest.raises(CassetteError, match="no recorded response for command 'revit.list_elements_by_category'"):
        asyncio.run(provider.execute_tool("revit_list_elements", {"category": "Doors"}))


def test_replay_without_cassette_explains_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_REVIT_CASSETTE", raising=False)
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.replay)
    with pytest.raises(CassetteError, match="MCP_REVIT_CASSETTE"):
        asyncio.run(provider.execute_tool("revit_list_levels", {}))
    monkeypatch.setenv("MCP_REVIT_CASSETTE", str(tmp_path / "missing.jsonl"))
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.replay)
    with pytest.raises(CassetteError, match="Cannot read cassette 'missing.jsonl'"):
        asyncio.run(provider.execute_tool("revit_list_levels", {}))


@pytest.mark.parametrize("line, message", [
    ("not json", "not valid JSON"),
    ('{"ok": true}', "needs at least 'command' and 'ok'"),
    ('{"v": 99, "command": "revit.x", "ok": true}', "version 99"),
])
def test_malformed_cassette_is_refused(tmp_path, line, message):
    path = tmp_path / "bad.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(CassetteError, match=message):
        ReplayBridge.from_file(path)


def test_equal_requests_replay_in_order_then_repeat_the_last():
    entries = [
        {"command": "revit.get_selection", "params": {}, "ok": True, "response": {"n": 1}},
        {"command": "revit.get_selection", "params": {}, "ok": True, "response": {"n": 2}},
    ]
    bridge = ReplayBridge(entries)
    got = [bridge.send_tool("revit.get_selection", {"request_id": str(i), "wait_ms": 5})["n"] for i in range(3)]
    assert got == [1, 2, 2] and bridge.unused() == []


def test_params_match_regardless_of_key_order():
    bridge = ReplayBridge([{"command": "revit.c", "params": {"a": 1, "b": 2}, "ok": True, "response": {"x": 1}}])
    assert bridge.send_tool("revit.c", {"b": 2, "a": 1}) == {"x": 1}


def test_sample_cassette_runs_as_a_regression_test(cassette_replay):
    assert cassette_replay(SAMPLE) == {"tool_level": 4, "bridge_level": 1}
