import pytest

from revit_mcp_server.config import BridgeMode
from revit_mcp_server.providers.powerbi import PowerBIProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

# What each tool should declare. Only powerbi_health is exposed today.
EXPECTED_MUTATING = {
    "powerbi_health": False,
    "powerbi_execute_dax": False,
    "powerbi_invoke_method": True,
    "powerbi_reflect_get": True,
    "powerbi_reflect_set": True,
}
EXPOSED_TOOLS = {"powerbi_health"}

# These tools are not exposed yet, but they keep the default is_mutating=False
# and run no enrich_mutation_metadata. Exposing them as-is would skip the gate.
_UNGATED_WHEN_EXPOSED = pytest.mark.xfail(
    strict=True, reason="hidden tool is not gated; enable it only with enrich_mutation_metadata"
)


class FakeBridge:
    def __init__(self, url, token=None, health=None, health_error=None):
        self.url = url
        self.token = token
        self.sent = []
        self.closed = False
        self._health = health
        self._health_error = health_error

    def send_tool(self, tool, payload):
        self.sent.append((tool, payload))
        return {"ok": True, "tool": tool}

    def _get(self, path):
        if self._health_error:
            raise self._health_error
        return self._health or {"status": "ok", "path": path}

    def close(self):
        self.closed = True


class BareBridge:
    """No _get and no close, like a minimal bridge client."""

    def send_tool(self, tool, payload):
        return {"ok": True}


def _provider(tmp_path, mode=BridgeMode.mock, bridge_url=None, factory=None):
    return PowerBIProvider(
        workspace=WorkspaceMonitor([tmp_path]),
        mode=mode,
        bridge_url=bridge_url,
        bridge_factory=factory or (lambda u, t=None: FakeBridge(u, t)),
    )


def test_identity(tmp_path):
    assert _provider(tmp_path).get_identity() == "powerbi"


def test_expected_table_covers_every_declared_tool(tmp_path):
    declared = {t.name for t in PowerBIProvider._capabilities}
    assert declared == set(EXPECTED_MUTATING)
    assert declared == set(_provider(tmp_path)._tool_mapping)


def test_exposed_tools_are_health_only_and_read_only(tmp_path):
    tools = _provider(tmp_path).get_capabilities()
    assert {t.name for t in tools} == EXPOSED_TOOLS
    for tool in tools:
        assert tool.is_mutating is EXPECTED_MUTATING[tool.name]


@pytest.mark.parametrize(
    "name",
    [
        "powerbi_health",
        "powerbi_execute_dax",
        pytest.param("powerbi_invoke_method", marks=_UNGATED_WHEN_EXPOSED),
        pytest.param("powerbi_reflect_get", marks=_UNGATED_WHEN_EXPOSED),
        pytest.param("powerbi_reflect_set", marks=_UNGATED_WHEN_EXPOSED),
    ],
)
def test_declared_is_mutating_matches_expected_table(name):
    tool = next(t for t in PowerBIProvider._capabilities if t.name == name)
    assert tool.is_mutating is EXPECTED_MUTATING[name]


def test_default_bridge_url_and_no_token(tmp_path):
    seen = {}

    def factory(url, token=None):
        seen["args"] = (url, token)
        return FakeBridge(url, token)

    _provider(tmp_path, factory=factory)
    assert seen["args"] == ("http://127.0.0.1:3006", None)


def test_custom_bridge_url(tmp_path):
    provider = _provider(tmp_path, bridge_url="http://127.0.0.1:9999")
    assert provider._bridge.url == "http://127.0.0.1:9999"


def test_default_factory_builds_a_bridge_client(tmp_path):
    provider = PowerBIProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    assert type(provider._bridge).__name__ == "BridgeClient"


@pytest.mark.anyio
async def test_health_mock_mode(tmp_path):
    result = await _provider(tmp_path).execute_tool("powerbi_health", {})
    assert result == {"mock": True, "tool": "health", "payload": {}}


@pytest.mark.anyio
async def test_mock_mode_never_calls_the_bridge(tmp_path):
    provider = _provider(tmp_path)
    await provider.execute_tool("powerbi_health", {})
    assert provider._bridge.sent == []


@pytest.mark.anyio
async def test_health_bridge_mode_sends_to_bridge(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    result = await provider.execute_tool("powerbi_health", {})
    assert result == {"ok": True, "tool": "health"}
    assert provider._bridge.sent == [("health", {})]


@pytest.mark.anyio
async def test_request_id_is_forwarded(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    await provider.execute_tool("powerbi_health", {"request_id": "r-1"})
    assert provider._bridge.sent == [("health", {"request_id": "r-1"})]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name",
    ["powerbi_execute_dax", "powerbi_invoke_method", "powerbi_reflect_get", "powerbi_reflect_set", "nope"],
)
async def test_every_other_tool_is_refused_in_health_only_mode(tmp_path, name):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    with pytest.raises(ValueError, match="health-only mode"):
        await provider.execute_tool(name, {"query": "EVALUATE x"})
    assert provider._bridge.sent == []


@pytest.mark.parametrize(
    "name, args, bridge_tool, payload",
    [
        ("powerbi_health", {"x": 1}, "health", {}),
        ("powerbi_execute_dax", {"query": "EVALUATE T"}, "execute_dax", {"query": "EVALUATE T"}),
        (
            "powerbi_invoke_method",
            {"class_name": "C", "method_name": "M", "arguments": [1], "target_id": "t"},
            "invoke_method",
            {"class_name": "C", "method_name": "M", "arguments": [1], "target_id": "t"},
        ),
        (
            "powerbi_reflect_get",
            {"target_id": "t", "property_name": "P"},
            "reflect_get",
            {"target_id": "t", "property_name": "P"},
        ),
        (
            "powerbi_reflect_set",
            {"target_id": "t", "property_name": "P", "value": 3},
            "reflect_set",
            {"target_id": "t", "property_name": "P", "value": 3},
        ),
        ("powerbi_execute_dax", {}, "execute_dax", {"query": None}),
    ],
)
def test_payload_builders_map_arguments(tmp_path, name, args, bridge_tool, payload):
    mapped_tool, builder = _provider(tmp_path)._tool_mapping[name]
    assert mapped_tool == bridge_tool
    assert builder(args) == payload


@pytest.mark.anyio
async def test_check_health_mock_mode(tmp_path):
    assert await _provider(tmp_path).check_health() == {"status": "healthy", "mode": "mock"}


@pytest.mark.anyio
async def test_check_health_bridge_mode_uses_bridge_get(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    assert await provider.check_health() == {"status": "ok", "path": "/health"}


@pytest.mark.anyio
async def test_check_health_bridge_mode_without_get(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge, factory=lambda u, t=None: BareBridge())
    assert await provider.check_health() == {"status": "healthy", "mode": "bridge"}


@pytest.mark.anyio
async def test_check_health_bridge_mode_reports_failure(tmp_path):
    provider = _provider(
        tmp_path,
        mode=BridgeMode.bridge,
        factory=lambda u, t=None: FakeBridge(u, t, health_error=RuntimeError("down")),
    )
    assert await provider.check_health() == {"status": "unhealthy", "error": "down"}


@pytest.mark.anyio
async def test_shutdown_closes_bridge(tmp_path):
    provider = _provider(tmp_path)
    await provider.shutdown()
    assert provider._bridge.closed is True


@pytest.mark.anyio
async def test_shutdown_tolerates_bridge_without_close(tmp_path):
    provider = _provider(tmp_path, factory=lambda u, t=None: BareBridge())
    await provider.shutdown()
