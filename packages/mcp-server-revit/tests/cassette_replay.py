"""Replay a bridge cassette through the Revit provider as a regression test.

Each entry that names an MCP tool is replayed at tool level: the provider builds the bridge
request from the recorded tool arguments, and the replay bridge must find a recorded match.
A changed payload builder therefore fails with "no recorded response". With ``compare`` the
tool output must also equal the recorded bridge response, which holds for tools that return
the add-in result unchanged. Entries without a tool, or whose arguments were redacted, are
replayed at bridge level only. Every entry must be used.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from revit_mcp_server.bridge.cassette import CassetteError, ReplayBridge
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError, CommandFailed
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor


def replay_cassette(path: Any, workspace: Path, compare: bool = True) -> dict[str, int]:
    """Replay every entry of the cassette at ``path``. MCP_REVIT_CASSETTE must name the same file."""
    provider = RevitProvider(workspace=WorkspaceMonitor([Path(workspace)]), mode=BridgeMode.replay)
    bridge = provider._active_bridge()
    assert isinstance(bridge, ReplayBridge), getattr(bridge, "message", bridge)
    assert Path(path).name == bridge.name
    counts = {"tool_level": 0, "bridge_level": 0}
    for entry in bridge.entries:
        if entry.get("tool") and not entry.get("arguments_redacted"):
            def call(e=entry):
                return asyncio.run(provider.execute_tool(e["tool"], dict(e.get("arguments") or {})))
            counts["tool_level"] += 1
        else:
            def call(e=entry):
                return bridge.send_tool(e["command"], dict(e.get("params") or {}))
            counts["bridge_level"] += 1
        if not entry["ok"]:
            kind = (entry.get("error") or {}).get("type")
            with pytest.raises(CommandFailed if kind == "CommandFailed" else BridgeError) as caught:
                call()
            assert not isinstance(caught.value, CassetteError), str(caught.value)
            continue
        result = call()
        if compare:
            assert result == entry.get("response"), f"seq {entry.get('seq')}: {entry['command']} output changed"
    unused = bridge.unused()
    assert not unused, f"cassette entries never requested: {[e.get('seq') for e in unused]}"
    return counts
