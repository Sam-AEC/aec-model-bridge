import pytest

from revit_mcp_server.config import BridgeMode
from revit_mcp_server.providers.navisworks import NavisworksProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

EXPECTED_MUTATING = {
    "navisworks_health": False,
    "navisworks_get_document_info": False,
    "navisworks_get_model_tree": False,
    "navisworks_get_selection": False,
    "navisworks_append_file": True,
    "navisworks_refresh": True,
    "navisworks_list_viewpoints": False,
    "navisworks_create_viewpoint": True,
    "navisworks_activate_viewpoint": True,
    "navisworks_list_clash_tests": False,
    "navisworks_run_clash_test": True,
    "navisworks_get_clash_results": False,
    "navisworks_invoke_method": True,
    "navisworks_reflect_get": True,
    "navisworks_reflect_set": True,
}

# tool -> (arguments, bridge tool, payload)
EXPECTED_CALLS = {
    "navisworks_health": ({}, "navisworks.health", {}),
    "navisworks_get_document_info": ({}, "navis.get_document_info", {}),
    "navisworks_get_model_tree": ({}, "navis.get_model_tree", {"max_depth": 2}),
    "navisworks_get_selection": ({}, "navis.get_selection", {}),
    "navisworks_append_file": ({"path": "a.nwd"}, "navis.append_file", {"path": "a.nwd"}),
    "navisworks_refresh": ({}, "navis.refresh", {}),
    "navisworks_list_viewpoints": ({}, "navis.list_viewpoints", {}),
    "navisworks_create_viewpoint": ({}, "navis.create_viewpoint", {"name": "New Viewpoint"}),
    "navisworks_activate_viewpoint": ({"guid": "g"}, "navis.activate_viewpoint", {"guid": "g"}),
    "navisworks_list_clash_tests": ({}, "navis.list_clash_tests", {}),
    "navisworks_run_clash_test": ({"guid": "g"}, "navis.run_clash_test", {"guid": "g"}),
    "navisworks_get_clash_results": (
        {"guid": "g"},
        "navis.get_clash_results",
        {"guid": "g", "skip": 0, "limit": 50},
    ),
    "navisworks_invoke_method": (
        {"class_name": "C", "method_name": "M", "arguments": [1], "target_id": "t"},
        "navis.invoke_method",
        {"class_name": "C", "method_name": "M", "arguments": [1], "target_id": "t"},
    ),
    "navisworks_reflect_get": (
        {"target_id": "t", "property_name": "P"},
        "navis.reflect_get",
        {"target_id": "t", "property_name": "P"},
    ),
    "navisworks_reflect_set": (
        {"target_id": "t", "property_name": "P", "value": 3},
        "navis.reflect_set",
        {"target_id": "t", "property_name": "P", "value": 3},
    ),
}


class FakeBridge:
    def __init__(self, url, token=None, health_error=None):
        self.url = url
        self.token = token
        self.sent = []
        self.closed = False
        self._health_error = health_error

    def send_tool(self, tool, payload):
        self.sent.append((tool, payload))
        return {"ok": True, "tool": tool}

    def _get(self, path):
        if self._health_error:
            raise self._health_error
        return {"status": "ok", "path": path}

    def close(self):
        self.closed = True


class BareBridge:
    def send_tool(self, tool, payload):
        return {"ok": True}


def _provider(tmp_path, mode=BridgeMode.mock, bridge_url=None, factory=None):
    return NavisworksProvider(
        workspace=WorkspaceMonitor([tmp_path]),
        mode=mode,
        bridge_url=bridge_url,
        bridge_factory=factory or (lambda u, t=None: FakeBridge(u, t)),
    )


def test_identity(tmp_path):
    assert _provider(tmp_path).get_identity() == "navisworks"


def test_tables_cover_every_declared_tool(tmp_path):
    provider = _provider(tmp_path)
    declared = {t.name for t in provider.get_capabilities()}
    assert declared == set(EXPECTED_MUTATING)
    assert declared == set(EXPECTED_CALLS)
    assert declared == set(provider._tool_mapping)


@pytest.mark.parametrize("name, expected", sorted(EXPECTED_MUTATING.items()))
def test_is_mutating_matches_expected_table(tmp_path, name, expected):
    tools = {t.name: t for t in _provider(tmp_path).get_capabilities()}
    assert tools[name].is_mutating is expected


def test_default_bridge_url_and_no_token(tmp_path):
    seen = {}

    def factory(url, token=None):
        seen["args"] = (url, token)
        return FakeBridge(url, token)

    _provider(tmp_path, factory=factory)
    assert seen["args"] == ("http://127.0.0.1:3002", None)


def test_custom_bridge_url(tmp_path):
    provider = _provider(tmp_path, bridge_url="http://127.0.0.1:9")
    assert provider._bridge.url == "http://127.0.0.1:9"


def test_default_factory_builds_a_bridge_client(tmp_path):
    provider = NavisworksProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    assert type(provider._bridge).__name__ == "BridgeClient"


@pytest.mark.anyio
@pytest.mark.parametrize("name", sorted(EXPECTED_CALLS))
async def test_mock_mode_returns_mapped_call_without_bridge(tmp_path, name):
    args, bridge_tool, payload = EXPECTED_CALLS[name]
    provider = _provider(tmp_path)
    result = await provider.execute_tool(name, args)
    assert result == {"mock": True, "tool": bridge_tool, "payload": payload}
    assert provider._bridge.sent == []


@pytest.mark.anyio
@pytest.mark.parametrize("name", sorted(EXPECTED_CALLS))
async def test_bridge_mode_sends_mapped_call(tmp_path, name):
    args, bridge_tool, payload = EXPECTED_CALLS[name]
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    result = await provider.execute_tool(name, args)
    assert result == {"ok": True, "tool": bridge_tool}
    assert provider._bridge.sent == [(bridge_tool, payload)]


@pytest.mark.anyio
async def test_overrides_replace_defaults(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    await provider.execute_tool("navisworks_get_model_tree", {"max_depth": 5})
    await provider.execute_tool("navisworks_create_viewpoint", {"name": "Roof"})
    await provider.execute_tool("navisworks_get_clash_results", {"guid": "g", "skip": 10, "limit": 5})
    assert provider._bridge.sent == [
        ("navis.get_model_tree", {"max_depth": 5}),
        ("navis.create_viewpoint", {"name": "Roof"}),
        ("navis.get_clash_results", {"guid": "g", "skip": 10, "limit": 5}),
    ]


@pytest.mark.anyio
async def test_request_id_is_forwarded(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    await provider.execute_tool("navisworks_refresh", {"request_id": "r-1"})
    assert provider._bridge.sent == [("navis.refresh", {"request_id": "r-1"})]


@pytest.mark.anyio
async def test_request_id_does_not_override_payload_key(tmp_path):
    provider = _provider(tmp_path)
    provider._tool_mapping["navisworks_health"] = ("h", lambda a: {"request_id": "own"})
    result = await provider.execute_tool("navisworks_health", {"request_id": "other"})
    assert result["payload"] == {"request_id": "own"}


@pytest.mark.anyio
async def test_unknown_tool_is_refused(tmp_path):
    provider = _provider(tmp_path, mode=BridgeMode.bridge)
    with pytest.raises(ValueError, match="Unknown Navisworks tool 'navisworks_nope'"):
        await provider.execute_tool("navisworks_nope", {})
    assert provider._bridge.sent == []


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
