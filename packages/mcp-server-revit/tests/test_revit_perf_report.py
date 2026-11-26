"""revit_perf_report: formats the add-in's /health timings, and says so when they are absent."""

from __future__ import annotations

import asyncio

import pytest

from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers import revit_perf
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import is_read_only_tool

TIMINGS = {
    "revit.fast": {"count": 10, "p50_ms": 5, "p95_ms": 9.5, "max_ms": 12, "avg_bytes": 300},
    "revit.slow": {"count": 3, "p50_ms": 800, "p95_ms": 2500, "max_ms": 3100, "avg_bytes": 52000.4},
    "revit.middle": {"count": 7, "p50_ms": 40, "p95_ms": 210, "max_ms": 260, "avg_bytes": 1200},
}


class HealthBridge:
    def __init__(self, health):
        self.health = health
        self.sent = []

    def initialize(self):
        pass

    def _get(self, path):
        assert path == "/health"
        return self.health

    def send_tool(self, tool, payload):  # must never be used: /health only
        self.sent.append(tool)
        return {}


def _run(tmp_path, health=None, mode=BridgeMode.bridge, **arguments):
    bridge = HealthBridge(health)
    provider = RevitProvider(
        workspace=WorkspaceMonitor([tmp_path]), mode=mode, bridge_url="http://127.0.0.1:3000",
        bridge_factory=lambda url, token=None: bridge,
    )
    result = asyncio.run(provider.execute_tool("revit_perf_report", arguments))
    assert bridge.sent == []
    return result


def test_table_sorted_by_p95_with_queue_depth(tmp_path):
    result = _run(tmp_path, {"status": "healthy", "queue_depth": 2, "timings": TIMINGS})
    assert result["timings_available"] is True
    assert result["queue_depth"] == 2
    assert [c["tool"] for c in result["commands"]] == ["revit.slow", "revit.middle", "revit.fast"]
    lines = result["table"].splitlines()
    assert lines[0] == "tool | count | p50_ms | p95_ms | max_ms | avg_bytes"
    assert lines[2] == "revit.slow | 3 | 800 | 2500 | 3100 | 52000.4"
    assert lines[4] == "revit.fast | 10 | 5 | 9.5 | 12 | 300"
    assert "mock" not in result


def test_top_limits_rows_and_says_so(tmp_path):
    result = _run(tmp_path, {"status": "healthy", "queue_depth": 0, "timings": TIMINGS}, top=1)
    assert [c["tool"] for c in result["commands"]] == ["revit.slow"]
    assert result["commands_recorded"] == 3
    assert "1 slowest of 3" in result["message"]


def test_older_addin_without_timings_is_reported_not_an_error(tmp_path):
    result = _run(tmp_path, {"status": "healthy", "queue_depth": 1, "version": "1.5.0"})
    assert result["ok"] is True
    assert result["timings_available"] is False
    assert result["commands"] == [] and result["table"] == ""
    assert "older than this tool" in result["message"]
    assert result["queue_depth"] == 1


def test_empty_and_malformed_timings(tmp_path):
    empty = _run(tmp_path, {"status": "healthy", "timings": {}})
    assert empty["timings_available"] is True and "no commands yet" in empty["message"]
    odd = _run(tmp_path, {"status": "healthy", "timings": {
        "revit.ok": {"count": 1, "p50_ms": 1, "p95_ms": 2, "max_ms": 3, "avg_bytes": 4},
        "revit.bad": "not an object",
        "revit.partial": {"count": 2, "p95_ms": "fast"},
    }})
    assert [c["tool"] for c in odd["commands"]] == ["revit.ok", "revit.partial"]
    assert odd["commands"][1]["p95_ms"] is None
    assert "revit.partial | 2 | - | - | - | -" in odd["table"]
    assert "1 malformed" in odd["message"]


def test_unreachable_addin_is_an_error_not_an_old_addin(tmp_path):
    with pytest.raises(BridgeError, match="not healthy"):
        _run(tmp_path, {"status": "unhealthy", "error": "No live Revit 2025 bridge found."})


def test_mock_mode_returns_labelled_sample(tmp_path):
    result = _run(tmp_path, mode=BridgeMode.mock)
    assert result["mock"] is True
    assert result["timings_available"] is True
    assert "sample numbers" in result["message"]
    p95 = [c["p95_ms"] for c in result["commands"]]
    assert p95 == sorted(p95, reverse=True)


@pytest.mark.parametrize("top", [0, 101, "5", True, 2.5])
def test_bad_top_is_refused(tmp_path, top):
    with pytest.raises(ValueError, match="top"):
        _run(tmp_path, {"status": "healthy", "timings": TIMINGS}, top=top)


def test_tool_is_listed_and_read_only(tmp_path):
    provider = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    tool = next(t for t in provider.get_capabilities() if t.name == "revit_perf_report")
    assert tool in revit_perf.PERF_TOOLS
    assert tool.is_mutating is False
    assert is_read_only_tool(tool.name, tool)
