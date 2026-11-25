"""Per-tool timeouts and rate limits (call_limits.py), on MCP calls and the panel hub routes.

Rate limits use a fake clock. A timed-out write is never booked as failed: it stays in flight
and is never replayed, like a 'running' result."""
from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult

from helpers import human_approve
from revit_mcp_server import call_limits, mcp_server
from revit_mcp_server.call_limits import Rate, RateConfig, RateLimiter, Timeouts, TokenBucket
from revit_mcp_server.errors import CommandFailed
from revit_mcp_server.security.approval import ApprovalGate

SET = "revit_set_parameter_value"
READ = "revit_list_views"
RID = "7b3c1d9e-0f6a-4c51-9d2a-5e8f1a2b3c4d"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _config(**rates):
    merged = dict(call_limits.DEFAULT_RATES)
    merged.update(rates)
    return RateConfig(merged, {})


# -- token bucket and limiter ------------------------------------------------------------

def test_bucket_allows_burst_then_waits_for_refill():
    clock = Clock()
    bucket = TokenBucket(Rate(60, 3), clock)
    for _ in range(3):
        assert bucket.wait_seconds() == 0
        bucket.take()
    assert bucket.wait_seconds() == pytest.approx(1.0)
    clock.now += 0.5
    assert bucket.wait_seconds() == pytest.approx(0.5)
    clock.now += 0.5
    assert bucket.wait_seconds() == 0
    clock.now += 3600
    bucket.wait_seconds()
    assert bucket._tokens == 3, "refill never goes above the burst"


def test_session_bucket_covers_all_tools_and_a_refusal_takes_nothing():
    clock = Clock()
    limiter = RateLimiter(_config(session=Rate(60, 2), read_tool=Rate(60, 1)), clock)
    assert limiter.check_tool("s1", "a", writes=False) is None
    refused = limiter.check_tool("s1", "a", writes=False)
    assert refused is not None and refused.scope == "tool 'a'"
    # The refused call took no token from the session bucket, so another tool still runs.
    assert limiter.check_tool("s1", "b", writes=False) is None
    session_refused = limiter.check_tool("s1", "c", writes=False)
    assert session_refused.scope == "this client session"
    assert session_refused.retry_after_seconds == 1
    assert "Nothing ran" in session_refused.message() and "Try again in 1 s" in session_refused.message()
    # Another session has its own bucket.
    assert limiter.check_tool("s2", "c", writes=False) is None


def test_write_tools_use_the_write_limit_and_per_tool_overrides_win():
    clock = Clock()
    config = RateConfig({**call_limits.DEFAULT_RATES, "write_tool": Rate(60, 1)}, {"special": Rate(60, 3)})
    limiter = RateLimiter(config, clock)
    assert limiter.check_tool("s", "w", writes=True) is None
    assert limiter.check_tool("s", "w", writes=True).scope == "tool 'w'"
    for _ in range(3):
        assert limiter.check_tool("s", "special", writes=True) is None
    assert limiter.check_tool("s", "special", writes=True) is not None
    clock.now += 1
    assert limiter.check_tool("s", "w", writes=True) is None


def test_disabled_limits_never_refuse():
    limiter = RateLimiter(RateConfig.from_env({"MCP_REVIT_RATE_LIMITS": "off"}), Clock())
    for _ in range(1000):
        assert limiter.check_tool("s", "w", writes=True) is None
    assert limiter.check_route("panel_chat") is None


def test_route_bucket():
    clock = Clock()
    limiter = RateLimiter(_config(panel_chat=Rate(30, 1)), clock)
    assert limiter.check_route("panel_chat") is None
    refused = limiter.check_route("panel_chat")
    assert refused.retry_after_seconds == 2
    clock.now += 2
    assert limiter.check_route("panel_chat") is None


# -- configuration -----------------------------------------------------------------------

def test_defaults_are_generous():
    config = RateConfig.from_env({})
    assert config.enabled
    assert config.rates["session"] == Rate(600, 300)
    assert config.rates["write_tool"] == Rate(120, 60)
    timeouts = Timeouts.from_env({})
    assert timeouts.for_tool("anything") == 300


def test_rate_limits_from_env_merge_with_defaults():
    raw = json.dumps({"session": {"per_minute": 60, "burst": 5}, "write_tool": {"per_minute": 0},
                      "tools": {"revit_export_ifc": {"per_minute": 2, "burst": 1}}})
    config = RateConfig.from_env({"MCP_REVIT_RATE_LIMITS": raw})
    assert config.rates["session"] == Rate(60, 5)
    assert not config.rates["write_tool"].enabled
    assert config.rates["read_tool"] == call_limits.DEFAULT_RATES["read_tool"]
    assert config.tools["revit_export_ifc"] == Rate(2, 1)


@pytest.mark.parametrize("raw", [
    "not json", "[1, 2]", '{"session": 5}', '{"session": {"per_minute": -1}}',
    '{"session": {"per_minute": "x"}}', '{"session": {"per_minute": 10, "burst": 0}}',
])
def test_invalid_rate_config_keeps_the_defaults(raw):
    config = RateConfig.from_env({"MCP_REVIT_RATE_LIMITS": raw})
    assert config.enabled
    assert config.rates["session"] == call_limits.DEFAULT_RATES["session"]


def test_timeouts_from_env():
    env = {"MCP_REVIT_TOOL_TIMEOUT": "60",
           "MCP_REVIT_TOOL_TIMEOUTS": '{"revit_export_ifc": 1800, "slow_read": 0, "bad": "x"}'}
    timeouts = Timeouts.from_env(env)
    assert timeouts.for_tool("revit_export_ifc") == 1800
    assert timeouts.for_tool("slow_read") is None
    assert timeouts.for_tool("bad") == 60
    assert timeouts.for_tool("other") == 60
    assert Timeouts.from_env({"MCP_REVIT_TOOL_TIMEOUT": "0"}).for_tool("x") is None


@pytest.mark.parametrize("raw", ["-5", "abc", "nan", "inf"])
def test_invalid_default_timeout_falls_back_to_300(raw):
    assert Timeouts.from_env({"MCP_REVIT_TOOL_TIMEOUT": raw}).for_tool("x") == 300


# -- MCP calls ---------------------------------------------------------------------------

def _args(i=1):
    return {"element_id": i, "parameter_name": "FireRating", "value": "60"}


def _approved(tmp_path):
    gate = ApprovalGate(tmp_path, "ask_first")
    plan = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])
    human_approve(gate, plan["plan_id"])
    return gate, plan["plan_id"]


class SlowRevit:
    """Write and read wait for `release`; the write then answers with `write_result`."""

    def __init__(self):
        self.calls = []
        self.release = None
        self.cancelled = []
        self.write_result = {"success": True}

    async def execute_tool(self, name, arguments):
        self.calls.append(name)
        if name == "revit_get_result":
            return {"success": True}
        if self.release is not None:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.append(name)
                raise
        if isinstance(self.write_result, BaseException):
            raise self.write_result
        return self.write_result if name == SET else {"views": []}


def _wire(monkeypatch, gate, revit):
    registry = SimpleNamespace(
        lookup_tool_provider=lambda name: revit,
        lookup_tool=lambda name: SimpleNamespace(is_mutating=name == SET),
    )
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=gate))


def _call(name, arguments):
    return asyncio.run(mcp_server.call_tool(name, arguments))


def _action(gate, pid):
    return gate.load_plan(pid)["actions"][0]


def test_rate_limited_write_does_not_use_the_approved_action(tmp_path, monkeypatch):
    gate, pid = _approved(tmp_path)
    revit = SlowRevit()
    _wire(monkeypatch, gate, revit)
    clock = Clock()
    before = _action(gate, pid)["state"]
    monkeypatch.setattr(mcp_server, "call_limiter", RateLimiter(_config(write_tool=Rate(60, 1)), clock))
    assert _call(SET, {**_args(2)})  # uses the one token (refused by the gate: no plan for it)
    refused = _call(SET, {**_args(), "plan_id": pid})
    assert isinstance(refused, CallToolResult) and refused.isError
    error = refused.structuredContent["error"]
    assert error["kind"] == "rate_limited" and error["retry_after_seconds"] == 1
    assert "Nothing ran" in refused.content[0].text
    assert revit.calls == [], "a refused call never reaches Revit"
    assert _action(gate, pid)["state"] == before != "running"
    clock.now += 1
    done = _call(SET, {**_args(), "plan_id": pid})
    assert "executed successfully" in done[0].text
    assert _action(gate, pid)["state"] == "executed"


def test_approval_tools_are_not_counted(tmp_path, monkeypatch):
    gate, _pid = _approved(tmp_path)
    _wire(monkeypatch, gate, SlowRevit())
    monkeypatch.setattr(mcp_server, "call_limiter", RateLimiter(_config(session=Rate(60, 1)), Clock()))
    for tool in ("approve_plan", "reject_plan", "rollback_plan") * 3:
        result = _call(tool, {"plan_id": "x"})
        assert result.structuredContent["error"]["kind"] == "human_only"
    assert "executed successfully" in _call(READ, {})[0].text


def test_read_timeout_is_refused_and_cancelled(tmp_path, monkeypatch):
    gate = ApprovalGate(tmp_path, "ask_first")
    revit = SlowRevit()
    _wire(monkeypatch, gate, revit)
    monkeypatch.setattr(mcp_server, "tool_timeouts", Timeouts(0.05, {}))

    async def scenario():
        revit.release = asyncio.Event()
        result = await mcp_server.call_tool(READ, {})
        await asyncio.sleep(0)
        return result

    result = asyncio.run(scenario())
    assert isinstance(result, CallToolResult) and result.isError
    error = result.structuredContent["error"]
    assert error["kind"] == "tool_timeout" and error["timeout_seconds"] == 0.05
    assert "nothing in the model changed" in result.content[0].text
    assert "MCP_REVIT_TOOL_TIMEOUTS" in result.content[0].text
    assert revit.cancelled == [READ]


def test_per_tool_override_of_zero_means_no_timeout(tmp_path, monkeypatch):
    gate = ApprovalGate(tmp_path, "ask_first")
    revit = SlowRevit()
    _wire(monkeypatch, gate, revit)
    monkeypatch.setattr(mcp_server, "tool_timeouts", Timeouts(0.01, {READ: 0}))

    async def scenario():
        revit.release = asyncio.Event()
        call = asyncio.ensure_future(mcp_server.call_tool(READ, {}))
        await asyncio.sleep(0.05)
        assert not call.done()
        revit.release.set()
        return await call

    assert "executed successfully" in asyncio.run(scenario())[0].text


def _timed_out_write(tmp_path, monkeypatch, late_result):
    """Run an approved write that outlives its timeout, then let it finish with ``late_result``."""
    gate, pid = _approved(tmp_path)
    revit = SlowRevit()
    revit.write_result = late_result
    _wire(monkeypatch, gate, revit)
    monkeypatch.setattr(mcp_server, "tool_timeouts", Timeouts(0.05, {}))
    seen = {}

    async def scenario():
        revit.release = asyncio.Event()
        first = await mcp_server.call_tool(SET, {**_args(), "plan_id": pid})
        seen["reply"] = first
        seen["action"] = dict(_action(gate, pid))
        seen["replay"] = await mcp_server.call_tool(SET, {**_args(), "plan_id": pid})
        revit.release.set()
        for _ in range(20):
            await asyncio.sleep(0.01)

    asyncio.run(scenario())
    return gate, pid, revit, seen


def test_timed_out_write_stays_in_flight_and_is_never_replayed(tmp_path, monkeypatch):
    gate, pid, revit, seen = _timed_out_write(tmp_path, monkeypatch, {"success": True})
    reply = seen["reply"]
    assert not isinstance(reply, CallToolResult), "a timed-out write is not reported as an error"
    text = reply[0].text
    assert "may still be running in Revit" in text and "not been reported as failed" in text
    assert "cannot be run again" in text and "Do not repeat the call" in text
    assert f"aec-model-bridge-approve recover {pid}" in text
    action = seen["action"]
    assert action["state"] == "running" and action["in_flight_key"].startswith("timeout_")
    assert seen["replay"].structuredContent["error"]["kind"] == "approval_blocked"
    assert revit.calls == [SET], "the write reached Revit once"
    assert revit.cancelled == [], "a write is never cancelled on timeout"
    # It finished in the background: the action is closed with the real result.
    assert _action(gate, pid)["state"] == "executed"
    assert gate.in_flight(action["in_flight_key"]) is None
    assert gate.load_plan(pid)["state"] == "executed"


def test_timed_out_write_that_fails_in_revit_is_booked_failed(tmp_path, monkeypatch):
    gate, pid, _revit, seen = _timed_out_write(tmp_path, monkeypatch, CommandFailed("wall is pinned"))
    assert seen["action"]["state"] == "running"
    action = _action(gate, pid)
    assert action["state"] == "failed" and "pinned" in action["error"]


def test_timed_out_write_with_unknown_outcome_stays_running(tmp_path, monkeypatch):
    gate, pid, _revit, seen = _timed_out_write(tmp_path, monkeypatch, ConnectionError("lost"))
    key = seen["action"]["in_flight_key"]
    assert _action(gate, pid)["state"] == "running"
    assert gate.in_flight(key) is not None, "a lost connection leaves it for a person to recover"


def test_timed_out_write_answered_running_moves_to_the_request_id(tmp_path, monkeypatch):
    gate, pid, _revit, seen = _timed_out_write(
        tmp_path, monkeypatch, {"status": "running", "request_id": RID})
    assert gate.in_flight(seen["action"]["in_flight_key"]) is None
    assert gate.in_flight(RID)["action_id"] == seen["action"]["action_id"]
    assert _action(gate, pid)["in_flight_key"] == RID
    assert "executed successfully" in _call("revit_get_result", {"request_id": RID})[0].text
    assert _action(gate, pid)["state"] == "executed"


def test_unplanned_write_timeout_in_auto_mode_is_not_an_error(tmp_path, monkeypatch):
    gate = ApprovalGate(tmp_path, "auto")
    revit = SlowRevit()
    _wire(monkeypatch, gate, revit)
    monkeypatch.setattr(mcp_server, "tool_timeouts", Timeouts(0.05, {}))

    async def scenario():
        revit.release = asyncio.Event()
        reply = await mcp_server.call_tool(SET, _args())
        revit.release.set()
        await asyncio.sleep(0.02)
        return reply

    reply = asyncio.run(scenario())
    assert not isinstance(reply, CallToolResult)
    assert "may still be running in Revit" in reply[0].text
    assert revit.cancelled == []


# -- panel hub routes --------------------------------------------------------------------

@pytest.fixture
def limited_hub(tmp_path, monkeypatch):
    from revit_mcp_server.panel_server import build_server
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    monkeypatch.setenv("MCP_REVIT_RATE_LIMITS", json.dumps({
        "panel_execute": {"per_minute": 1, "burst": 2}, "panel_chat": {"per_minute": 1, "burst": 1}}))
    server = build_server(port=0, workspace=WorkspaceMonitor([tmp_path]))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _post(port, path, body):
    from revit_mcp_server.security.panel_token import read_token

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-AMB-Token": read_token()}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read())


def test_hub_execute_route_is_rate_limited_but_approvals_are_not(limited_hub):
    read = {"tool": "list_pending_plans", "arguments": {}}
    assert _post(limited_hub, "/execute", read)[0] == 200
    assert _post(limited_hub, "/execute", read)[0] == 200
    status, headers, body = _post(limited_hub, "/execute", read)
    assert status == 429
    assert body["kind"] == "rate_limited" and body["retry_after_seconds"] >= 1
    assert headers["Retry-After"] == str(body["retry_after_seconds"])
    # The person's approval click still reaches the gate (it refuses the unknown plan itself).
    status, _headers, body = _post(limited_hub, "/execute", {"tool": "approve_plan", "arguments": {
        "plan_id": "plan_00000000000000000000000000000000", "expected_hash": "x"}})
    assert status != 429 and body.get("kind") != "rate_limited"


def test_hub_chat_route_is_rate_limited(limited_hub, monkeypatch):
    from revit_mcp_server import panel_server

    monkeypatch.setattr(panel_server.config, "anthropic_api_key", "test-key")
    monkeypatch.setattr(panel_server.agent_native, "run_native_turn",
                        lambda message, session_id, registry, approval_provider: {"ok": True, "response": "r"})
    assert _post(limited_hub, "/agent/chat", {"message": "hi"})[0] == 200
    status, headers, body = _post(limited_hub, "/agent/chat", {"message": "hi"})
    assert status == 429 and body["kind"] == "rate_limited" and "Retry-After" in headers


def test_hub_handler_has_a_socket_timeout():
    from revit_mcp_server import panel_server

    assert panel_server.PanelRequestHandler.timeout == panel_server.SOCKET_TIMEOUT_SECONDS == 30
