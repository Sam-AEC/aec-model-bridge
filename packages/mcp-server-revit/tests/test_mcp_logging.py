"""MCP logging: logging/setLevel and notifications/message (issue #181)."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from revit_mcp_server import mcp_logging, mcp_server

LOG = logging.getLogger("revit_mcp_server.test_logging")


@pytest.fixture
def server(tmp_path, monkeypatch):
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    monitor = WorkspaceMonitor([tmp_path])
    registry, approval, jobs, _, _ = build_registry(monitor)
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "workspace_monitor", monitor)
    yield SimpleNamespace(root=tmp_path)
    asyncio.run(jobs.shutdown(cancel_running=True))
    logging.getLogger(mcp_logging.PACKAGE_LOGGER).setLevel(logging.NOTSET)
    mcp_logging.handler._base = None


async def _session(script):
    received: list[types.LoggingMessageNotificationParams] = []

    async def on_log(params):
        received.append(params)

    async with create_connected_server_and_client_session(mcp_server.app, logging_callback=on_log) as client:
        await script(client)
        await client.send_ping()  # lets queued notifications arrive
        await asyncio.sleep(0.05)
    return received


def run(script):
    return asyncio.run(_session(script))


def test_server_declares_the_logging_capability(server):
    async def script(client):
        pass

    async def check():
        async with create_connected_server_and_client_session(mcp_server.app) as client:
            return client.get_server_capabilities()

    assert asyncio.run(check()).logging is not None


def test_set_level_warning_sends_warning_and_not_info(server):
    async def script(client):
        await client.set_logging_level("warning")
        LOG.info("info message")
        LOG.warning("refused path")

    received = run(script)
    assert [(p.level, p.data) for p in received] == [("warning", "refused path")]
    assert received[0].logger == "revit_mcp_server.test_logging"


def test_set_level_info_sends_info(server):
    async def script(client):
        await client.set_logging_level("info")
        LOG.info("info message")
        LOG.debug("debug message")

    received = run(script)
    assert [p.data for p in received] == ["info message"]


def test_nothing_is_sent_until_the_client_sets_a_level(server):
    async def script(client):
        await client.call_tool("list_pending_plans", {})
        LOG.warning("warning message")
        LOG.error("error message")

    assert run(script) == []


def test_send_failure_does_not_break_the_logging_call(server, monkeypatch):
    async def script(client):
        await client.set_logging_level("warning")

        async def boom(*a, **k):
            raise RuntimeError("stream closed")

        for session, _ in list(mcp_logging.handler._sessions.items()):
            monkeypatch.setattr(session, "send_log_message", boom)
        LOG.warning("still fine")
        result = await client.call_tool("list_pending_plans", {})
        assert not result.isError

    assert run(script) == []


def test_log_written_while_sending_does_not_re_enter(server, monkeypatch):
    async def script(client):
        await client.set_logging_level("warning")
        real = {}

        async def noisy(*a, **k):
            LOG.warning("emitted while sending")
            return await real["send"](*a, **k)

        for session, _ in list(mcp_logging.handler._sessions.items()):
            real["send"] = session.send_log_message
            monkeypatch.setattr(session, "send_log_message", noisy)
        LOG.warning("outer")

    assert [p.data for p in run(script)] == ["outer"]


def test_level_is_per_session(server):
    async def chatty(client):
        await client.set_logging_level("info")

    async def quiet(client):
        await client.call_tool("list_pending_plans", {})  # never sets a level

    async def both():
        got_a, got_b = [], []

        async def cb_a(params):
            got_a.append(params.data)

        async def cb_b(params):
            got_b.append(params.data)

        async with create_connected_server_and_client_session(mcp_server.app, logging_callback=cb_a) as a, \
                create_connected_server_and_client_session(mcp_server.app, logging_callback=cb_b) as b:
            await chatty(a)
            await quiet(b)
            LOG.info("only for a")
            await a.send_ping()
            await b.send_ping()
            await asyncio.sleep(0.05)
        return got_a, got_b

    got_a, got_b = asyncio.run(both())
    assert got_a == ["only for a"]
    assert got_b == []


def test_messages_are_redacted_like_tool_results(server, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_REDACT_RESPONSES", "basic")

    async def script(client):
        await client.set_logging_level("warning")
        LOG.warning(r"cannot read C:\Users\jane\Secret\plan.rvt for jane@example.com password=hunter2")
        LOG.warning("reading /home/jane/model.rvt")

    sent = "\n".join(p.data for p in run(script))
    for leaked in ("jane", "Secret", "hunter2", "model.rvt", "example.com"):
        assert leaked not in sent
    assert "<redacted" in sent


def test_messages_match_the_tool_result_redaction(server):
    text = r"token=abc123 at C:\Users\bob\file.rvt"
    assert mcp_logging.safe_message(text) == mcp_server.redact_data(text)


def test_long_messages_are_cut(server):
    assert len(mcp_logging.safe_message("x " * 5000)) <= mcp_logging.MAX_MESSAGE_CHARS + 3


def test_traceback_is_not_sent(server):
    async def script(client):
        await client.set_logging_level("error")
        try:
            raise ValueError(r"secret detail in C:\Users\bob\x")
        except ValueError:
            LOG.exception("tool failed")

    received = run(script)
    assert [p.data for p in received] == ["tool failed"]


def test_logging_from_a_worker_thread_reaches_the_client(server):
    async def script(client):
        await client.set_logging_level("warning")
        await asyncio.to_thread(LOG.warning, "from a thread")

    assert [p.data for p in run(script)] == ["from a thread"]


def test_stderr_fallback_kept_when_handler_installed():
    package = logging.getLogger(mcp_logging.PACKAGE_LOGGER)
    assert mcp_logging.handler in package.handlers
    assert logging.getLogger().handlers or logging.lastResort in package.handlers
