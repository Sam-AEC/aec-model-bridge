"""MCP Tasks for long tool calls, backed by the shared JobManager.

A client that sends a ``task`` field with ``tools/call`` for a tool listed in
TASK_TOOLS gets a CreateTaskResult back at once. The call runs as a JobManager
job, and the client follows it with ``tasks/get``, ``tasks/result``,
``tasks/list`` and ``tasks/cancel``. A call without the ``task`` field runs
exactly as before.

The approval gate is unchanged: mcp_server claims the approved action before the
task is created, exactly as for a direct call, and books the outcome when the
call ends. A task that can change the model is cancelled only while it is still
queued. Once it has started, ``tasks/cancel`` refuses, because stopping it part
way could leave a change half-applied.

The installed MCP SDK (1.x, pinned below 2) ships the Tasks types and request
handlers as an experimental, deprecated API; mcp 2.0 is expected to move Tasks
to an extension. If the server object has no experimental handler registry,
register_task_handlers returns False and tools/call runs without Tasks.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
import warnings
import weakref
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from mcp.shared.exceptions import McpError
from mcp.types import (
    INVALID_PARAMS,
    CallToolResult,
    CancelTaskRequest,
    CancelTaskResult,
    CreateTaskResult,
    ErrorData,
    GetTaskPayloadRequest,
    GetTaskRequest,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    Task,
    TaskMetadata,
    TextContent,
)

logger = logging.getLogger(__name__)

# Long-running tools a client may call as a task: exports, snapshots, QA runs and
# revit_run_job. Every other tool refuses a task-augmented call.
TASK_TOOLS = frozenset({
    "revit_run_job",
    "revit_export",
    "revit_export_dwg",
    "revit_export_ifc",
    "revit_export_image",
    "revit_export_navisworks",
    "revit_extract_snapshot",
    "snapshot_take",
    "snapshot_compute",
    "snapshot_diff",
    "model_changes_compare_snapshots",
    "qaqc_checker_run_check",
    "revit_check_clashes",
    "revit_cleanup_audit",
    "model_bloat_audit",
    "sheet_view_audit_run_audit",
    "sheet_set_qa_check",
    "links_worksets_audit_audit",
    "ids_validator_validate_ifc",
    "qa_handover_build_report",
    "report_generator_build_review_pack",
})

RUN_JOB_TOOL = "revit_run_job"
JOB_STATUS_TOOL = "revit_job_status"
RELATED_TASK_KEY = "io.modelcontextprotocol/related-task"
POLL_INTERVAL_MS = 1000
DEFAULT_TTL_MS = 3_600_000  # JobManager keeps finished jobs for an hour by default
MAX_TASKS = 256
_WAIT_STEP_S = 0.1
_FOLLOW_STEP_S = 0.5
_JOB_TERMINAL = frozenset({"completed", "failed", "cancelled"})


def _not_found(task_id: str) -> McpError:
    return McpError(ErrorData(code=INVALID_PARAMS, message=f"Task not found: {task_id}"))


def _refuse(message: str) -> McpError:
    return McpError(ErrorData(code=INVALID_PARAMS, message=message))


def request_task_metadata(server: Any) -> Optional[TaskMetadata]:
    """The ``task`` field of the current request, or None (no request context or no task)."""
    try:
        ctx = server.request_context
    except LookupError:
        return None
    experimental = getattr(ctx, "experimental", None)
    metadata = getattr(experimental, "task_metadata", None)
    return metadata if isinstance(metadata, TaskMetadata) else None


_SCOPES: "weakref.WeakKeyDictionary[Any, str]" = weakref.WeakKeyDictionary()


def session_scope(server: Any) -> Optional[str]:
    """An opaque id for the requesting session, so one session never sees another's tasks."""
    try:
        session = server.request_context.session
    except LookupError:
        return None
    try:
        scope = _SCOPES.get(session)
        if scope is None:
            scope = uuid.uuid4().hex
            _SCOPES[session] = scope
        return scope
    except TypeError:  # not weak-referenceable
        return None


async def follow_revit_job(
    provider: Any, result: Any, on_cancel: Callable[[Any], Any],
) -> Any:
    """For a revit_run_job task: poll revit_job_status until the Revit job has finished.

    revit_run_job returns after wait_s with state queued or running. A task should
    end with the job's real outcome, so the task keeps polling. If the task is
    cancelled or a status call fails, the last answer is kept; on_cancel books it
    as still running, never as failed, because Revit may still be working.
    """
    current = result
    while (
        isinstance(current, dict)
        and current.get("state") in ("queued", "running")
        and current.get("job_id")
    ):
        try:
            await asyncio.sleep(_FOLLOW_STEP_S)
            current = await provider.execute_tool(JOB_STATUS_TOOL, {"job_id": current["job_id"]})
        except asyncio.CancelledError:
            on_cancel(current)
            raise
        except Exception:  # noqa: BLE001 - keep the last known state; the caller reports it as running
            logger.exception("Could not poll revit_job_status for a task")
            return current
    return current


async def follow_revit_result(
    fetch: Callable[[str], Awaitable[Any]], tool: str, result: Any, on_cancel: Callable[[Any], Any],
) -> Any:
    """For any task: follow a pending Revit request through revit_get_result until it is final.

    A bridge call can outlive its soft wait and answer {"status": "running", "request_id": ...}
    while Revit keeps working (a revit_run_job can end the same way, as a StillRunning failure).
    A task should end with the real outcome, so ``fetch(request_id)`` (revit_get_result) is
    called until the answer is final. A CommandFailed from it is Revit's verdict and is raised
    to the caller. If the task is cancelled, the last answer is booked as still running by
    on_cancel; if any other lookup error occurs, the last answer is kept and returned.
    """
    from .errors import CommandFailed
    from .security.dispatch import GET_RESULT_TOOL, classify_outcome

    current = result
    while True:
        outcome = classify_outcome(tool, current) if isinstance(current, dict) else None
        if (outcome is None or outcome.state != "running" or not outcome.key
                or not (outcome.resume or "").startswith(GET_RESULT_TOOL)):
            return current
        try:
            await asyncio.sleep(_FOLLOW_STEP_S)
            current = await fetch(outcome.key)
        except asyncio.CancelledError:
            on_cancel(current)
            raise
        except CommandFailed:
            raise
        except Exception:  # noqa: BLE001 - keep the last known state; the caller reports it as running
            logger.exception("Could not collect a running Revit request for a task")
            return current
        tool = GET_RESULT_TOOL


@dataclass
class _TaskEntry:
    task_id: str
    job_id: str
    tool: str
    writes: bool
    scope: Optional[str]
    ttl_ms: int
    on_cancel_before_start: Callable[[], Any]
    result: Optional[CallToolResult] = None


class TaskBridge:
    """Maps MCP task ids to JobManager jobs."""

    def __init__(self, job_manager: Callable[[], Any]) -> None:
        self._job_manager = job_manager
        self._entries: dict[str, _TaskEntry] = {}

    @property
    def manager(self) -> Any:
        manager = self._job_manager()
        if manager is None:
            raise _refuse("Tasks are not available: the job manager is not running.")
        return manager

    async def start(
        self,
        *,
        tool: str,
        writes: bool,
        metadata: TaskMetadata,
        scope: Optional[str],
        work: Callable[[], Awaitable[CallToolResult]],
        on_cancel_before_start: Callable[[], Any],
    ) -> CreateTaskResult:
        """Queue `work` as a job and return the new task at once."""
        await self._prune()
        if len(self._entries) >= MAX_TASKS:
            raise RuntimeError("Too many tasks are being kept. Wait for running tasks to finish and try again.")
        task_id = uuid.uuid4().hex
        ttl_ms = DEFAULT_TTL_MS if metadata.ttl is None else max(0, min(int(metadata.ttl), DEFAULT_TTL_MS))
        entry = _TaskEntry(
            task_id=task_id, job_id="", tool=tool, writes=writes, scope=scope,
            ttl_ms=ttl_ms, on_cancel_before_start=on_cancel_before_start,
        )

        async def job() -> dict[str, Any]:
            entry.result = await work()
            return {"task_id": task_id, "tool": tool, "is_error": bool(entry.result.isError)}

        ref = await self.manager.submit(job)
        entry.job_id = ref.job_id
        self._entries[task_id] = entry
        return CreateTaskResult(task=self._task(entry, ref))

    async def get(self, task_id: str, scope: Optional[str]) -> GetTaskResult:
        entry, ref = await self._lookup(task_id, scope)
        return GetTaskResult(**self._task(entry, ref).model_dump())

    async def list(self, scope: Optional[str]) -> ListTasksResult:
        await self._prune()
        tasks: list[Task] = []
        for entry in list(self._entries.values()):
            if entry.scope != scope:
                continue
            ref = await self.manager.get(entry.job_id)
            if ref is not None:
                tasks.append(self._task(entry, ref))
        return ListTasksResult(tasks=tasks)

    async def result(self, task_id: str, scope: Optional[str]) -> CallToolResult:
        """Wait until the task has finished, then return the tool's CallToolResult."""
        entry, ref = await self._lookup(task_id, scope)
        while ref.status not in _JOB_TERMINAL:
            await asyncio.sleep(_WAIT_STEP_S)
            ref = await self.manager.get(entry.job_id)
            if ref is None:
                raise _not_found(task_id)
        meta = {RELATED_TASK_KEY: {"taskId": task_id}}
        if ref.status == "completed" and entry.result is not None:
            return entry.result.model_copy(update={"meta": meta})
        task = self._task(entry, ref)
        kind = "task_cancelled" if ref.status == "cancelled" else "task_failed"
        message = task.statusMessage or "The task did not return a result."
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text=message)],
            structuredContent={"ok": False, "error": {"kind": kind, "message": message}},
            _meta=meta,
        )

    async def cancel(self, task_id: str, scope: Optional[str]) -> CancelTaskResult:
        entry, ref = await self._lookup(task_id, scope)
        if ref.status in _JOB_TERMINAL:
            raise _refuse(f"Task {task_id} has already finished ({self._status(entry, ref)}); it cannot be cancelled.")
        if entry.writes:
            cancelled_ref, cancelled = await self.manager.cancel_if_queued(entry.job_id)
            if cancelled_ref is None:
                raise _not_found(task_id)
            if not cancelled:
                raise _refuse(
                    f"Task {task_id} runs {entry.tool}, which can change the model, and it has already started. "
                    "It cannot be cancelled, because stopping it part way could leave the change half-applied. "
                    "It keeps running; poll tasks/get for the outcome."
                )
            try:
                entry.on_cancel_before_start()
            except Exception:  # noqa: BLE001 - the cancel itself succeeded
                logger.exception("Could not record the cancelled task %s", task_id)
            ref = cancelled_ref
        else:
            ref = await self.manager.cancel(entry.job_id)
            if ref is None:
                raise _not_found(task_id)
        return CancelTaskResult(**self._task(entry, ref).model_dump())

    # -- helpers -----------------------------------------------------------

    async def _lookup(self, task_id: str, scope: Optional[str]) -> tuple[_TaskEntry, Any]:
        entry = self._entries.get(task_id)
        if entry is None or entry.scope != scope:
            raise _not_found(task_id)
        ref = await self.manager.get(entry.job_id)
        if ref is None:
            self._entries.pop(task_id, None)
            raise _not_found(task_id)
        return entry, ref

    async def _prune(self) -> None:
        """Forget tasks whose job the JobManager no longer keeps."""
        manager = self._job_manager()
        if manager is None:
            return
        for task_id, entry in list(self._entries.items()):
            if await manager.get(entry.job_id) is None:
                self._entries.pop(task_id, None)

    @staticmethod
    def _status(entry: _TaskEntry, ref: Any) -> str:
        if ref.status in ("queued", "running"):
            return "working"
        if ref.status == "completed":
            return "failed" if entry.result is None or entry.result.isError else "completed"
        return "cancelled" if ref.status == "cancelled" else "failed"

    def _task(self, entry: _TaskEntry, ref: Any) -> Task:
        status = self._status(entry, ref)
        if status == "working":
            message = "Queued." if ref.status == "queued" else "Running."
            if entry.writes:
                message += " This task can change the model; it can be cancelled only before it starts."
        elif status == "completed":
            message = f"{entry.tool} finished."
        elif status == "cancelled":
            if entry.writes and ref.started_at:
                message = (
                    f"{entry.tool} was stopped after it started (for example, the server shut down). "
                    "Check the model before you retry."
                )
            elif entry.writes:
                message = (
                    "Cancelled before it started. The model was not changed. "
                    "The approved action is used up; plan again to retry."
                )
            else:
                message = "Cancelled."
        elif entry.result is not None:
            message = f"{entry.tool} returned a failure. Call tasks/result for the details."
        else:
            message = f"{entry.tool} failed before it returned a result."
        return Task(
            taskId=entry.task_id,
            status=status,
            statusMessage=message,
            createdAt=ref.created_at,
            lastUpdatedAt=ref.updated_at,
            ttl=entry.ttl_ms,
            pollInterval=POLL_INTERVAL_MS,
        )


def register_task_handlers(server: Any, bridge: TaskBridge) -> bool:
    """Register tasks/get, tasks/result, tasks/list and tasks/cancel on a low-level Server.

    Registering them also makes the SDK advertise the ``tasks`` server capability
    (list, cancel, requests.tools.call). Returns False, and registers nothing, when
    the installed SDK has no experimental Tasks API.
    """
    try:
        with warnings.catch_warnings():
            # mcp 1.x marks the experimental Tasks API deprecated (it moves to an extension in 2.0).
            warnings.simplefilter("ignore", DeprecationWarning)
            experimental = server.experimental
        get_task = experimental.get_task
        get_task_result = experimental.get_task_result
        list_tasks = experimental.list_tasks
        cancel_task = experimental.cancel_task
    except AttributeError:
        logger.info("The installed MCP SDK has no Tasks API; tools/call runs without tasks.")
        return False

    # The SDK passes the request only to a parameter annotated with its request type.
    @get_task()
    async def _get_task(req: GetTaskRequest, /):
        return await bridge.get(req.params.taskId, session_scope(server))

    @get_task_result()
    async def _get_task_result(req: GetTaskPayloadRequest, /):
        return await bridge.result(req.params.taskId, session_scope(server))

    @list_tasks()
    async def _list_tasks(req: ListTasksRequest, /):
        return await bridge.list(session_scope(server))

    @cancel_task()
    async def _cancel_task(req: CancelTaskRequest, /):
        return await bridge.cancel(req.params.taskId, session_scope(server))

    return True
