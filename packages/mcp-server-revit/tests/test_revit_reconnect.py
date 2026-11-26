"""revit_reconnect (#372): re-bind to a live Revit session after a restart. Registry and bridge are simulated;
nothing here observes a real Revit restart."""
from __future__ import annotations

import asyncio

import pytest

from revit_mcp_server.bridge import discovery
from revit_mcp_server.bridge.client import BridgeClient
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers import RevitProvider
from revit_mcp_server.providers.revit import _BRIDGE_OVERRIDE
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import enrich_tool


def switch(pid=2000, version="2024", token="tok-new", started="2026-11-01T08:00:00Z"):
    return discovery.SwitchInfo(
        provider_id="revit", endpoint=f"http://127.0.0.1:{39000 + pid % 1000}", pid=pid, host_version=version,
        connector_version="1.5.1", protocol_version=2, capability_digest="d", session_token=token, started_at=started,
    )


class FakeBridge:
    """Records what is sent. Reports the document of the session it was built for."""

    def __init__(self, url, token, documents, healthy=True, log=None):
        self.url, self.token, self.documents, self.healthy = url, token, documents, healthy
        self.log = log if log is not None else []
        self.bound = None
        self.closed = False

    def bind_registry_session(self, sw):
        self.bound = sw
        self._registry_session = (sw.pid,)

    def initialize(self):
        self.log.append(("initialize", self.url, self.token))
        if not self.healthy:
            raise BridgeError("Bridge unreachable")

    def _get(self, path):
        self.log.append(("get", path, self.token))
        return {"status": "healthy", "active_document": self.documents.get(self.token)}

    def send_tool(self, tool, payload):
        self.log.append(("send", tool, self.token))
        return {"ok": True}

    def close(self):
        self.closed = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    live = []
    monkeypatch.setattr(discovery, "discover_switch_list", lambda *a, **k: list(live))
    state = {"documents": {"tok-new": "Villa", "tok-b": "Office"}, "healthy": True, "log": [], "built": []}

    def factory(url, token=None):
        bridge = FakeBridge(url, token, state["documents"], healthy=state["healthy"], log=state["log"])
        state["built"].append(bridge)
        return bridge

    def make(**kw):
        return RevitProvider(
            WorkspaceMonitor([tmp_path]), kw.pop("mode", BridgeMode.bridge), bridge_url=kw.pop("bridge_url", None),
            bridge_factory=factory, **kw,
        )

    state["live"], state["make"] = live, make
    return state


def run(prov, **args):
    return asyncio.run(prov.execute_tool("revit_reconnect", args))


def test_rebinds_to_the_only_live_session_after_a_restart(env):
    env["live"].append(switch(pid=1000, token="tok-old"))
    prov = env["make"]()
    old = prov._bridge
    assert old.bound.pid == 1000
    env["live"][:] = [switch(pid=2000, token="tok-new")]
    result = run(prov)
    assert result["reconnected"] is True and result["previous_pid"] == 1000
    assert result["session"] == {
        "pid": 2000, "host_version": "2024", "started_at": "2026-11-01T08:00:00Z", "document": "Villa", "bound": True,
    }
    assert prov._bridge is not old and prov._bridge.bound.pid == 2000
    assert old.closed is True
    # The next call goes to the new session with the new token.
    asyncio.run(prov.execute_tool("revit_get_document_info", {}))
    assert ("send", "revit.get_document_info", "tok-new") in env["log"]


def test_reply_warns_to_check_the_model_and_says_plans_are_untouched(env):
    env["live"].append(switch())
    result = run(env["make"]())
    text = " ".join(result["warnings"])
    assert "Check the model before repeating an earlier write" in text
    assert "Pending plans and approvals were not changed" in text


def test_reply_never_exposes_the_session_token_or_endpoint(env):
    env["live"].append(switch(token="tok-new"))
    result = run(env["make"]())
    dump = repr(result)
    assert "tok-new" not in dump and "127.0.0.1" not in dump


def test_two_sessions_without_pid_change_nothing_and_list_both(env):
    env["live"][:] = [switch(pid=2000, token="tok-new"), switch(pid=3000, token="tok-b", started="2026-11-01T07:00:00Z")]
    prov = env["make"]()
    before = prov._bridge
    result = run(prov)
    assert result["reconnected"] is False
    assert [(s["pid"], s["document"]) for s in result["sessions"]] == [(2000, "Villa"), (3000, "Office")]
    assert prov._bridge is before
    assert "pid" in result["message"]


def test_pid_selects_between_two_sessions(env):
    env["live"][:] = [switch(pid=2000, token="tok-new"), switch(pid=3000, token="tok-b")]
    prov = env["make"]()
    result = run(prov, pid=3000)
    assert result["reconnected"] is True and prov._bridge.bound.pid == 3000
    assert [s["bound"] for s in result["sessions"]] == [False, True]


def test_unknown_pid_is_refused_and_nothing_changes(env):
    env["live"][:] = [switch(pid=2000)]
    prov = env["make"]()
    before = prov._bridge
    with pytest.raises(ValueError, match="No live Revit session has process id 4242"):
        run(prov, pid=4242)
    assert prov._bridge is before


@pytest.mark.parametrize("pid", [0, -5, "2000", 1.5, True])
def test_bad_pid_is_refused(env, pid):
    env["live"][:] = [switch()]
    with pytest.raises(ValueError, match="pid must be a positive integer"):
        run(env["make"](), pid=pid)


def test_no_live_session_is_a_plain_refusal(env):
    prov = env["make"]()
    before = prov._bridge
    with pytest.raises(ValueError, match="No live Revit session was found"):
        run(prov)
    assert prov._bridge is before


def test_failed_handshake_keeps_the_old_bridge_and_closes_the_new_one(env):
    env["live"][:] = [switch(pid=1000, token="tok-old")]
    prov = env["make"]()
    old = prov._bridge
    env["live"][:] = [switch(pid=2000, token="tok-new")]
    env["healthy"] = False
    with pytest.raises(BridgeError, match="Could not connect to Revit 2024 .*process 2000.*not changed"):
        run(prov)
    assert prov._bridge is old
    assert env["built"][-1].closed is True


def test_only_sessions_of_the_configured_revit_version_are_candidates(env):
    env["live"][:] = [switch(pid=2000, version="2025", token="tok-new"), switch(pid=3000, version="2024", token="tok-b")]
    prov = env["make"](host_version="2024")
    result = run(prov)
    assert result["reconnected"] is True and result["session"]["pid"] == 3000
    with pytest.raises(ValueError, match="No live Revit session has process id 2000"):
        run(prov, pid=2000)


def test_an_explicit_bridge_url_is_refused(env):
    env["live"][:] = [switch()]
    prov = env["make"](bridge_url="http://127.0.0.1:3000")
    before = prov._bridge
    with pytest.raises(ValueError, match="explicit bridge URL"):
        run(prov)
    assert prov._bridge is before


def test_mock_mode_is_refused(env):
    with pytest.raises(ValueError, match="live Revit connection"):
        run(env["make"](mode=BridgeMode.mock))


def test_refused_inside_a_panel_routed_call(env):
    env["live"][:] = [switch()]
    prov = env["make"]()
    reset = _BRIDGE_OVERRIDE.set(object())
    try:
        with pytest.raises(ValueError, match="panel-routed"):
            run(prov)
    finally:
        _BRIDGE_OVERRIDE.reset(reset)


def test_reconnect_sends_no_model_request(env):
    env["live"][:] = [switch()]
    run(env["make"]())
    assert {entry[0] for entry in env["log"]} <= {"get", "initialize"}


def _quiet_client(url, token):
    client = BridgeClient(url, token=token)
    client._get = lambda path: {"status": "healthy", "tools": [], "active_document": "Villa"}
    client.initialize = lambda: None
    return client


def test_real_client_pin_moves_to_the_new_session_and_still_refuses_a_later_change(env):
    env["live"][:] = [switch(pid=2000, token="tok-new")]
    prov = RevitProvider(WorkspaceMonitor([]), BridgeMode.bridge, bridge_url=None, bridge_factory=_quiet_client)
    assert prov._bridge._registry_session[0] == 2000
    env["live"][:] = [switch(pid=3000, token="tok-c")]
    with pytest.raises(BridgeError, match="changed or closed"):
        prov._bridge._check_registry_session()
    run(prov)
    assert prov._bridge._registry_session[0] == 3000
    prov._bridge._check_registry_session()
    env["live"][:] = [switch(pid=4000, token="tok-d")]
    with pytest.raises(BridgeError, match="changed or closed"):
        prov._bridge._check_registry_session()


def test_tool_is_not_mutating_and_is_not_marked_read_only(env):
    prov = env["make"]()
    tool = next(t for t in prov.get_capabilities() if t.name == "revit_reconnect")
    assert tool.is_mutating is False
    assert tool.input_schema["additionalProperties"] is False
    annotations = enrich_tool("revit", tool).annotations
    assert annotations.readOnlyHint is False and annotations.destructiveHint is False
