"""Tests for the current bridge-based RhinoProvider (HTTP bridge to the C#
rhino-bridge-addin on 127.0.0.1:3004 — see packages/rhino-bridge-addin).

This file previously tested an entirely different, long-abandoned design
(a Rhino.Compute REST client uploading .gh/.3dm files over HTTPS with API-key
auth) that the provider was rewritten away from; none of that matched the
current constructor or tool set, so every test failed with a TypeError on
`base_url`. Rewritten from scratch against the real provider.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from revit_mcp_server.config import BridgeMode
from revit_mcp_server.providers.rhino import RhinoProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

EXPECTED_TOOL_NAMES = [
    "rhino_health",
    "rhino_get_document_info",
    "rhino_get_lines",
    "rhino_get_scene",
    "rhino_list_layers",
    "rhino_clear_scene",
    "rhino_set_view",
    "rhino_create_box",
    "rhino_create_sphere",
    "rhino_create_cylinder",
    "rhino_boolean_union",
    "rhino_boolean_difference",
    "rhino_set_material",
    "rhino_transform_objects",
    "rhino_run_python",
    "rhino_generate_diagrid_tower",
    "rhino_invoke_method",
    "rhino_reflect_get",
    "rhino_reflect_set",
]


class FakeBridge:
    """Stands in for BridgeClient: records every dispatched tool call instead
    of making a real HTTP request to the C# add-in."""

    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url
        self.token = token
        self.calls: list[tuple[str, Dict[str, Any]]] = []
        self.health_response = {"status": "healthy"}

    def send_tool(self, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((tool_name, payload))
        return {"ok": True, "tool": tool_name, "payload": payload}

    def _get(self, path: str) -> Dict[str, Any]:
        return self.health_response


def _bridge_provider(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    fake = FakeBridge("http://127.0.0.1:3004")
    provider = RhinoProvider(workspace=workspace, mode=BridgeMode.bridge, bridge_factory=lambda u, t=None: fake)
    return provider, fake


def test_rhino_capabilities_match_the_bridge_command_table(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, mode=BridgeMode.mock)
    names = [tool.name for tool in provider.get_capabilities()]
    assert names == EXPECTED_TOOL_NAMES


@pytest.mark.parametrize(
    "tool_name,mutating,destructive",
    [
        ("rhino_health", False, False),
        ("rhino_get_scene", False, False),
        ("rhino_list_layers", False, False),
        ("rhino_reflect_get", False, False),
        ("rhino_clear_scene", True, False),
        ("rhino_create_box", True, False),
        ("rhino_boolean_union", True, False),
        ("rhino_set_material", True, False),
        ("rhino_transform_objects", True, False),
        ("rhino_reflect_set", True, False),
        ("rhino_invoke_method", True, False),
        ("rhino_run_python", True, True),
    ],
)
def test_rhino_mutation_metadata(tmp_path, tool_name, mutating, destructive):
    """rhino_run_python executes arbitrary IronPython with full RhinoCommon
    access — same risk class as revit_execute_python — so it must be both
    mutating and destructive; other write tools are mutating only."""
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, mode=BridgeMode.mock)
    tool = next(t for t in provider.get_capabilities() if t.name == tool_name)
    assert tool.is_mutating is mutating
    assert tool.destructive is destructive


@pytest.mark.anyio
async def test_mock_mode_does_not_touch_a_real_bridge(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, mode=BridgeMode.mock)

    result = await provider.execute_tool("rhino_create_box", {"min_pt": [0, 0, 0], "max_pt": [1, 1, 1]})
    assert result["mock"] is True
    assert result["tool"] == "create_box"
    assert result["payload"] == {"min_pt": [0, 0, 0], "max_pt": [1, 1, 1]}


@pytest.mark.anyio
async def test_bridge_mode_dispatches_to_injected_bridge(tmp_path):
    provider, fake = _bridge_provider(tmp_path)

    result = await provider.execute_tool("rhino_get_scene", {})
    assert result == {"ok": True, "tool": "get_scene", "payload": {}}
    assert fake.calls == [("get_scene", {})]


@pytest.mark.anyio
async def test_create_box_payload_includes_optional_fields_only_when_present(tmp_path):
    provider, fake = _bridge_provider(tmp_path)

    await provider.execute_tool("rhino_create_box", {"min_pt": [0, 0, 0], "max_pt": [2, 2, 2]})
    _, payload = fake.calls[-1]
    assert payload == {"min_pt": [0, 0, 0], "max_pt": [2, 2, 2]}
    assert "layer" not in payload and "color" not in payload

    await provider.execute_tool(
        "rhino_create_box",
        {"min_pt": [0, 0, 0], "max_pt": [2, 2, 2], "layer": "Facade", "color": [255, 0, 0]},
    )
    _, payload = fake.calls[-1]
    assert payload["layer"] == "Facade"
    assert payload["color"] == [255, 0, 0]


@pytest.mark.anyio
async def test_generate_diagrid_tower_fills_in_defaults(tmp_path):
    provider, fake = _bridge_provider(tmp_path)

    await provider.execute_tool("rhino_generate_diagrid_tower", {"height": 200.0})
    tool_name, payload = fake.calls[-1]
    assert tool_name == "generate_diagrid_tower"
    assert payload["height"] == 200.0
    assert payload["base_radius"] == 22.0  # default from the tool mapping
    assert payload["u_divs"] == 16


@pytest.mark.anyio
async def test_run_python_forwards_code_verbatim(tmp_path):
    provider, fake = _bridge_provider(tmp_path)

    code = "print('hello from rhino')"
    await provider.execute_tool("rhino_run_python", {"code": code})
    tool_name, payload = fake.calls[-1]
    assert tool_name == "run_python"
    assert payload == {"code": code}


@pytest.mark.anyio
async def test_unknown_tool_raises_value_error(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, mode=BridgeMode.mock)

    with pytest.raises(ValueError, match="Unknown Rhino tool"):
        await provider.execute_tool("rhino_does_not_exist", {})


@pytest.mark.anyio
async def test_check_health_in_bridge_mode_uses_injected_bridge(tmp_path):
    provider, fake = _bridge_provider(tmp_path)
    fake.health_response = {"status": "healthy", "service": "rhino-bridge"}

    health = await provider.check_health()
    assert health == {"status": "healthy", "service": "rhino-bridge"}


@pytest.mark.anyio
async def test_check_health_in_mock_mode_does_not_require_a_bridge(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, mode=BridgeMode.mock)

    health = await provider.check_health()
    assert health["status"] == "healthy"
    assert health["mode"] == "mock"
