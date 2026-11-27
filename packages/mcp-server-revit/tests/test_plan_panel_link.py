"""URL-mode elicitation that points the person at the review panel for a pending plan (issue #193).

The link carries only the plan id. It is sent only to clients that declared URL elicitation.
It never approves, executes or carries a decision, and holds no panel token.
"""
from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from revit_mcp_server import mcp_server
from revit_mcp_server.elicitation import client_supports_url_elicitation, panel_plan_url
from revit_mcp_server.panel_server import build_server
from revit_mcp_server.security.panel_token import load_or_create_token, read_token
from revit_mcp_server.security.workspace import WorkspaceMonitor

PLAN_ARGS = {"actions": [{"tool": "revit_set_parameter_value",
                          "arguments": {"element_id": 1, "parameter": "Comments", "value": "x"}}]}


@pytest.fixture
def server(tmp_path, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry

    monitor = WorkspaceMonitor([tmp_path])
    registry, approval, jobs, _, _ = build_registry(monitor)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "workspace_monitor", monitor)
    yield SimpleNamespace(root=tmp_path, approval=approval)
    asyncio.run(jobs.shutdown(cancel_running=True))


class Asker:
    def __init__(self, action="accept"):
        self.action = action
        self.asked = []

    async def __call__(self, context, params):
        self.asked.append(params)
        return types.ElicitResult(action=self.action)


def call(name, arguments, asker=None):
    async def run():
        kwargs = {"elicitation_callback": asker} if asker is not None else {}
        async with create_connected_server_and_client_session(mcp_server.app, **kwargs) as client:
            answer = await client.call_tool(name, arguments)
            await _link_sent()
            return answer
    return asyncio.run(run())


async def _link_sent():
    """The link goes out in the background after the reply; wait for it before the session closes."""
    if mcp_server._link_tasks:
        await asyncio.wait(set(mcp_server._link_tasks), timeout=5)


def _plan_id(answer) -> str:
    assert not answer.isError, answer.content[0].text
    text = answer.content[0].text
    data = answer.structuredContent or json.loads(text.split("Result:\n", 1)[1])
    return data["plan_id"]


# ------------------------------------------------------------------ capability


def _session(cap):
    caps = types.ClientCapabilities(elicitation=cap)
    return SimpleNamespace(client_params=SimpleNamespace(capabilities=caps))


def test_capability_check_needs_url_mode():
    assert client_supports_url_elicitation(_session(types.ElicitationCapability(url=types.UrlElicitationCapability())))
    assert not client_supports_url_elicitation(_session(types.ElicitationCapability()))
    assert not client_supports_url_elicitation(_session(
        types.ElicitationCapability(form=types.FormElicitationCapability())))
    assert not client_supports_url_elicitation(_session(None))
    assert not client_supports_url_elicitation(None)
    assert not client_supports_url_elicitation(SimpleNamespace())


# ------------------------------------------------------------------------- URL


def test_url_is_loopback_with_the_plan_id_only(monkeypatch):
    monkeypatch.setenv("MCP_PANEL_HTTP_PORT", "8790")
    url = panel_plan_url("plan_0123456789ab")
    parts = urlparse(url)
    assert (parts.scheme, parts.hostname, parts.port, parts.path) == ("http", "127.0.0.1", 8790, "/panel")
    assert parse_qs(parts.query) == {"plan": ["plan_0123456789ab"]}
    assert not parts.fragment and not parts.username and not parts.password


@pytest.mark.parametrize("bad", ["", "plan_x", "../etc", "plan_0123456789ab&approve=1", "plan_0123456789ab\n"])
def test_url_refuses_anything_but_a_plan_id(bad):
    with pytest.raises(ValueError):
        panel_plan_url(bad)


# ---------------------------------------------------------- plan_actions flow


def test_client_with_url_mode_gets_the_panel_link_for_the_new_plan(server):
    asker = Asker()
    plan_id = _plan_id(call("plan_actions", PLAN_ARGS, asker))
    (asked,) = asker.asked
    assert asked.mode == "url"
    assert parse_qs(urlparse(asked.url).query) == {"plan": [plan_id]}
    assert urlparse(asked.url).hostname == "127.0.0.1"
    assert asked.elicitationId
    assert "does not approve" in asked.message
    assert load_or_create_token() not in asked.url + asked.message
    # Nothing was approved or run by asking.
    assert server.approval.gate.load_plan(plan_id)["state"] == "pending"


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_declined_link_leaves_the_plan_pending(server, action):
    asker = Asker(action)
    plan_id = _plan_id(call("plan_actions", PLAN_ARGS, asker))
    assert len(asker.asked) == 1
    assert server.approval.gate.load_plan(plan_id)["state"] == "pending"


def test_client_without_elicitation_behaves_as_before(server):
    assert _plan_id(call("plan_actions", PLAN_ARGS)).startswith("plan_")


def test_client_declaring_form_only_gets_no_link(server, monkeypatch):
    class FormOnly(Asker):
        pass

    # The SDK client declares form and url together, so narrow the declared capability here.
    monkeypatch.setattr(
        "revit_mcp_server.elicitation.client_supports_url_elicitation", lambda session: False)
    monkeypatch.setattr(mcp_server, "client_supports_url_elicitation", lambda session: False)
    asker = FormOnly()
    assert _plan_id(call("plan_actions", PLAN_ARGS, asker)).startswith("plan_")
    assert asker.asked == []


def test_link_failure_never_fails_the_plan(server):
    class Boom(Asker):
        async def __call__(self, context, params):
            raise RuntimeError("client broke")

    plan_id = _plan_id(call("plan_actions", PLAN_ARGS, Boom()))
    assert server.approval.gate.load_plan(plan_id)["state"] == "pending"


def test_plan_reply_does_not_wait_for_a_slow_link(server, monkeypatch):
    sent = []
    release = asyncio.Event()

    class SlowSession:
        client_params = SimpleNamespace(capabilities=types.ClientCapabilities(
            elicitation=types.ElicitationCapability(url=types.UrlElicitationCapability())))

        async def elicit_url(self, message, url, elicitation_id, related_request_id=None):
            sent.append(url)
            await release.wait()

    monkeypatch.setattr(mcp_server, "_client_session", lambda: SlowSession())

    async def run():
        answer = await asyncio.wait_for(mcp_server._call_tool_rounds("plan_actions", PLAN_ARGS), timeout=3)
        await asyncio.sleep(0)
        assert not release.is_set() and len(mcp_server._link_tasks) == 1  # still asking after the reply
        release.set()
        await _link_sent()
        assert not mcp_server._link_tasks
        return answer

    result = asyncio.run(run())
    text = result[0].text
    plan_id = json.loads(text.split("Result:\n", 1)[1])["plan_id"]
    assert len(sent) == 1 and parse_qs(urlparse(sent[0]).query) == {"plan": [plan_id]}
    assert server.approval.gate.load_plan(plan_id)["state"] == "pending"


def test_link_task_errors_are_swallowed_and_the_task_is_released(server, monkeypatch, caplog):
    async def boom(*a, **k):
        raise RuntimeError("elicitation broke")

    monkeypatch.setattr(mcp_server, "offer_plan_panel_link", boom)
    with caplog.at_level("INFO", logger="revit_mcp_server.mcp_server"):
        plan_id = _plan_id(call("plan_actions", PLAN_ARGS, Asker()))
    assert server.approval.gate.load_plan(plan_id)["state"] == "pending"
    assert not mcp_server._link_tasks
    assert "Panel link skipped" in caplog.text


def test_other_tools_never_send_a_link(server):
    asker = Asker()
    call("list_pending_plans", {}, asker)
    assert asker.asked == []


# ------------------------------------------------------------------ panel route


@pytest.fixture
def hub(tmp_path):
    srv = build_server(port=0, workspace=WorkspaceMonitor([tmp_path]))
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _fetch(port, path, method="GET", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {},
                                 data=b"{}" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


def test_link_opens_a_page_without_a_token_and_with_no_way_to_approve(hub):
    status, headers, body = _fetch(hub, "/panel?plan=plan_0123456789ab")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "plan_0123456789ab" in body
    for forbidden in ("<form", "<button", "<script", "<a ", "<input", read_token()):
        assert forbidden not in body
    assert "default-src 'none'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("path", [
    "/panel", "/panel?plan=", "/panel?plan=x",
    "/panel?plan=plan_0123456789ab&plan=plan_0123456789ac", "/panel?plan=%3Cscript%3E",
])
def test_page_refuses_a_missing_or_malformed_plan_id(hub, path):
    status, _, body = _fetch(hub, path)
    assert status == 400
    assert "<script" not in body


def test_the_panel_route_cannot_act_and_other_routes_still_need_the_token(hub):
    json_headers = {"Content-Type": "application/json"}
    assert _fetch(hub, "/panel?plan=plan_0123456789ab", "POST", json_headers)[0] == 401
    assert _fetch(hub, "/reports")[0] == 401
    assert _fetch(hub, "/execute", "POST", json_headers)[0] == 401
    assert _fetch(hub, "/panel?plan=plan_0123456789ab", headers={"Origin": "http://evil.example"})[0] == 403
