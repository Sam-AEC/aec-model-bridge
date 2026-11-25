"""MCP Tasks: task-augmented tools/call backed by the JobManager (issue #279).

The protocol tests drive the real `mcp_server.app` through the MCP SDK's
in-memory client, with a fake registry, provider and approval gate.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, CreateTaskResult, TaskMetadata

from revit_mcp_server import mcp_server, mcp_tasks
from revit_mcp_server.jobs import JobManager
from revit_mcp_server.providers.base import ProviderTool

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

EXPORT = "revit_export_ifc"          # in TASK_TOOLS, mutating in this fake
SNAPSHOT = "snapshot_take"           # in TASK_TOOLS, read-only in this fake
PLAIN = "revit_list_levels"          # not in TASK_TOOLS


class Gate:
    def __init__(self):
        self.claims = []
        self.finished = []

    def claim_action(self, name, arguments):
        claim = {"plan_id": "plan-1", "action_id": f"action-{len(self.claims)}"}
        self.claims.append((name, arguments))
        return claim

    def finish_action(self, claim, ok, error=None):
        self.finished.append((claim["action_id"], ok, error))

    def audit_dev_call(self, name, arguments, mutating):
        pass

    def mark_in_flight(self, claim, key, tool):
        self.finished.append((claim["action_id"], "in_flight", key))


class Provider:
    def __init__(self):
        self.release = asyncio.Event()
        self.block = False
        self.calls = []
        self.fail = False

    def get_identity(self):
        return "fake"

    async def execute_tool(self, name, arguments):
        self.calls.append(name)
        if self.block:
            await self.release.wait()
        if self.fail:
            return {"success": False, "error": "export failed"}
        if name == SNAPSHOT:
            # snapshot_take declares an outputSchema; the SDK client rejects a reply without it.
            return {"success": True, "tool": name, "status": "ok", "snapshot_id": "snap-1"}
        return {"success": True, "tool": name, "path": "model.ifc"}


def _install(monkeypatch):
    gate = Gate()
    provider = Provider()
    tools = {
        EXPORT: ProviderTool(name=EXPORT, description="Export IFC.", inputSchema={"type": "object"}, is_mutating=True),
        SNAPSHOT: ProviderTool(name=SNAPSHOT, description="Take a snapshot.", inputSchema={"type": "object"}),
        PLAIN: ProviderTool(name=PLAIN, description="List levels.", inputSchema={"type": "object"}),
    }
    registry = SimpleNamespace(
        lookup_tool_provider=lambda name: provider if name in tools else None,
        lookup_tool=lambda name: tools.get(name),
        get_tools_with_providers=lambda: [(provider, t) for t in tools.values()],
    )
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=gate))
    # The registered handlers hold mcp_server.task_bridge; start each test with no tasks.
    monkeypatch.setattr(mcp_server.task_bridge, "_entries", {})
    return gate, provider


def _run(monkeypatch, scenario):
    async def main():
        manager = JobManager()
        monkeypatch.setattr(mcp_server, "job_manager", manager)
        try:
            async with create_connected_server_and_client_session(mcp_server.app) as client:
                return await scenario(client)
        finally:
            await manager.shutdown(cancel_running=True)

    return asyncio.run(main())


async def _wait_status(client, task_id, wanted, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        status = await client.experimental.get_task(task_id)
        if status.status in wanted:
            return status
        assert asyncio.get_running_loop().time() < deadline, status
        await asyncio.sleep(0.02)


def test_tasks_enabled_with_installed_sdk():
    assert mcp_server.TASKS_ENABLED is True


def test_server_advertises_tasks_and_lists_task_support(monkeypatch):
    _install(monkeypatch)

    async def scenario(client):
        caps = client.get_server_capabilities()
        listed = await client.list_tools()
        return caps, {t.name: t for t in listed.tools}

    caps, tools = _run(monkeypatch, scenario)
    assert caps.tasks is not None
    assert caps.tasks.requests.tools.call is not None
    assert caps.tasks.cancel is not None and caps.tasks.list is not None
    assert tools[EXPORT].execution.taskSupport == "optional"
    assert tools[SNAPSHOT].execution.taskSupport == "optional"
    assert tools[PLAIN].execution is None


def test_call_without_task_field_is_unchanged(monkeypatch):
    gate, provider = _install(monkeypatch)

    async def scenario(client):
        return await client.call_tool(SNAPSHOT, {})

    result = _run(monkeypatch, scenario)
    assert isinstance(result, CallToolResult)
    assert not result.isError
    assert f"{SNAPSHOT} executed successfully" in result.content[0].text
    assert provider.calls == [SNAPSHOT]


def test_read_task_returns_task_then_result(monkeypatch):
    gate, provider = _install(monkeypatch)

    async def scenario(client):
        created = await client.experimental.call_tool_as_task(SNAPSHOT, {"name": "a"})
        task_id = created.task.taskId
        done = await _wait_status(client, task_id, {"completed", "failed"})
        listed = await client.experimental.list_tasks()
        final = await client.experimental.get_task_result(task_id, CallToolResult)
        return created, done, listed, final

    created, done, listed, final = _run(monkeypatch, scenario)
    assert isinstance(created, CreateTaskResult)
    assert created.task.status == "working"
    assert created.task.pollInterval == mcp_tasks.POLL_INTERVAL_MS
    assert created.task.ttl == 60000  # the client asked for 60 s; below the server's limit
    assert done.status == "completed"
    assert [t.taskId for t in listed.tasks] == [created.task.taskId]
    assert not final.isError
    assert f"{SNAPSHOT} executed successfully" in final.content[0].text
    assert final.meta[mcp_tasks.RELATED_TASK_KEY] == {"taskId": created.task.taskId}
    assert gate.claims == []  # read-only: no approval needed, as for a direct call


def test_task_on_tool_without_task_support_is_refused_before_claim(monkeypatch):
    gate, provider = _install(monkeypatch)

    async def scenario(client):
        from mcp import types

        return await client.send_request(
            types.ClientRequest(types.CallToolRequest(params=types.CallToolRequestParams(
                name=PLAIN, arguments={}, task=TaskMetadata(ttl=1000),
            ))),
            CallToolResult,
        )

    result = _run(monkeypatch, scenario)
    assert result.isError
    assert result.structuredContent["error"]["kind"] == "task_not_supported"
    assert provider.calls == []
    assert gate.claims == []


def test_write_task_claims_approval_once_and_books_outcome(monkeypatch):
    gate, provider = _install(monkeypatch)

    async def scenario(client):
        created = await client.experimental.call_tool_as_task(EXPORT, {"plan_id": "plan-1"})
        await _wait_status(client, created.task.taskId, {"completed", "failed"})
        return await client.experimental.get_task_result(created.task.taskId, CallToolResult)

    final = _run(monkeypatch, scenario)
    assert not final.isError
    assert gate.claims == [(EXPORT, {"plan_id": "plan-1"})]
    assert gate.finished == [("action-0", True, None)]


def test_started_write_task_cannot_be_cancelled(monkeypatch):
    gate, provider = _install(monkeypatch)
    provider.block = True

    async def scenario(client):
        created = await client.experimental.call_tool_as_task(EXPORT, {"plan_id": "plan-1"})
        task_id = created.task.taskId
        while not provider.calls:
            await asyncio.sleep(0.01)
        status = await client.experimental.get_task(task_id)
        with pytest.raises(McpError) as refused:
            await client.experimental.cancel_task(task_id)
        provider.release.set()
        done = await _wait_status(client, task_id, {"completed", "failed", "cancelled"})
        return status, refused.value, done

    status, refused, done = _run(monkeypatch, scenario)
    assert status.status == "working"
    assert "only before it starts" in status.statusMessage
    assert "half-applied" in str(refused)
    assert done.status == "completed"
    assert gate.finished == [("action-0", True, None)]


def test_running_read_task_can_be_cancelled(monkeypatch):
    gate, provider = _install(monkeypatch)
    provider.block = True

    async def scenario(client):
        created = await client.experimental.call_tool_as_task(SNAPSHOT, {})
        task_id = created.task.taskId
        while not provider.calls:
            await asyncio.sleep(0.01)
        cancelled = await client.experimental.cancel_task(task_id)
        final = await client.experimental.get_task_result(task_id, CallToolResult)
        with pytest.raises(McpError):
            await client.experimental.cancel_task(task_id)  # already finished
        return cancelled, final

    cancelled, final = _run(monkeypatch, scenario)
    assert cancelled.status == "cancelled"
    assert final.isError
    assert final.structuredContent["error"]["kind"] == "task_cancelled"


def test_job_cancelled_outside_tasks_shows_as_cancelled(monkeypatch):
    gate, provider = _install(monkeypatch)
    provider.block = True

    async def scenario(client):
        created = await client.experimental.call_tool_as_task(SNAPSHOT, {})
        task_id = created.task.taskId
        while not provider.calls:
            await asyncio.sleep(0.01)
        entry = mcp_server.task_bridge._entries[task_id]
        await mcp_server.job_manager.cancel(entry.job_id)  # e.g. the job_cancel tool
        return await client.experimental.get_task(task_id)

    status = _run(monkeypatch, scenario)
    assert status.status == "cancelled"


def test_failed_tool_marks_task_failed(monkeypatch):
    gate, provider = _install(monkeypatch)
    provider.fail = True

    async def scenario(client):
        created = await client.experimental.call_tool_as_task(EXPORT, {"plan_id": "plan-1"})
        done = await _wait_status(client, created.task.taskId, {"completed", "failed"})
        final = await client.experimental.get_task_result(created.task.taskId, CallToolResult)
        return done, final

    done, final = _run(monkeypatch, scenario)
    assert done.status == "failed"
    assert final.isError
    assert "returned a failure" in final.content[0].text
    assert gate.finished == [("action-0", False, "export failed")]


def test_unknown_task_id_is_refused(monkeypatch):
    _install(monkeypatch)

    async def scenario(client):
        with pytest.raises(McpError) as missing:
            await client.experimental.get_task("no-such-task")
        return missing.value

    assert "Task not found" in str(_run(monkeypatch, scenario))


# -- TaskBridge and JobManager units -------------------------------------------


def test_write_task_cancelled_before_start_never_runs():
    async def main():
        manager = JobManager()
        bridge = mcp_tasks.TaskBridge(lambda: manager)
        ran, booked = [], []

        async def work():
            ran.append(True)
            return CallToolResult(content=[], isError=False)

        created = await bridge.start(
            tool=EXPORT, writes=True, metadata=TaskMetadata(), scope="s1",
            work=work, on_cancel_before_start=lambda: booked.append(True),
        )
        cancelled = await bridge.cancel(created.task.taskId, "s1")
        await asyncio.sleep(0.05)
        await manager.shutdown()
        return cancelled, ran, booked

    cancelled, ran, booked = asyncio.run(main())
    assert cancelled.status == "cancelled"
    assert "The model was not changed" in cancelled.statusMessage
    assert ran == []
    assert booked == [True]


def test_cancel_if_queued_refuses_started_job():
    async def main():
        manager = JobManager()
        started = asyncio.Event()
        release = asyncio.Event()

        async def job():
            started.set()
            await release.wait()
            return "done"

        ref = await manager.submit(job)
        await started.wait()
        snapshot, cancelled = await manager.cancel_if_queued(ref.job_id)
        release.set()
        await manager.shutdown()
        final = await manager.get(ref.job_id)
        missing = await manager.cancel_if_queued("missing")
        return snapshot, cancelled, final, missing

    snapshot, cancelled, final, missing = asyncio.run(main())
    assert cancelled is False and snapshot.status == "running"
    assert final.status == "completed"
    assert missing == (None, False)


def test_tasks_are_scoped_to_their_session():
    async def main():
        manager = JobManager()
        bridge = mcp_tasks.TaskBridge(lambda: manager)

        async def work():
            return CallToolResult(content=[], isError=False)

        created = await bridge.start(
            tool=SNAPSHOT, writes=False, metadata=TaskMetadata(ttl=10**9), scope="a",
            work=work, on_cancel_before_start=lambda: None,
        )
        with pytest.raises(McpError):
            await bridge.get(created.task.taskId, "b")
        other = await bridge.list("b")
        own = await bridge.list("a")
        await manager.shutdown()
        return created, other, own

    created, other, own = asyncio.run(main())
    assert created.task.ttl == mcp_tasks.DEFAULT_TTL_MS  # capped at the job retention time
    assert other.tasks == []
    assert len(own.tasks) == 1


def test_follow_revit_job_polls_until_finished(monkeypatch):
    monkeypatch.setattr(mcp_tasks, "_FOLLOW_STEP_S", 0)

    class JobProvider:
        def __init__(self):
            self.states = ["running", "completed"]

        async def execute_tool(self, name, arguments):
            assert name == "revit_job_status" and arguments == {"job_id": "j1"}
            return {"job_id": "j1", "state": self.states.pop(0)}

    first = {"job_id": "j1", "state": "queued"}
    final = asyncio.run(mcp_tasks.follow_revit_job(JobProvider(), first, lambda last: None))
    assert final == {"job_id": "j1", "state": "completed"}


def test_follow_revit_job_books_running_when_cancelled():
    booked = []

    class SlowProvider:
        async def execute_tool(self, name, arguments):
            await asyncio.sleep(10)

    async def main():
        first = {"job_id": "j1", "state": "running"}
        task = asyncio.ensure_future(mcp_tasks.follow_revit_job(SlowProvider(), first, booked.append))
        await asyncio.sleep(0.6)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert booked == [{"job_id": "j1", "state": "running"}]


def test_register_returns_false_without_sdk_tasks_api():
    assert mcp_tasks.register_task_handlers(SimpleNamespace(), mcp_tasks.TaskBridge(lambda: None)) is False


def test_every_task_tool_exists_in_mock_registry():
    from revit_mcp_server.registry_factory import build_registry

    registry = build_registry()[0]
    names = {t.name for _p, t in registry.get_tools_with_providers()}
    assert mcp_tasks.TASK_TOOLS <= names, sorted(mcp_tasks.TASK_TOOLS - names)
