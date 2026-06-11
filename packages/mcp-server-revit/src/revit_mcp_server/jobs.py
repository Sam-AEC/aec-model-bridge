from __future__ import annotations

import asyncio
import dataclasses
import inspect
import math
import re
import threading
import uuid
from collections import deque
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Deque, Mapping, Sequence


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|session|authorization)\b\s*[:=]\s*([^\s,;]+)"
)
_WINDOWS_PATH_RE = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/](?:[^\s\"'<>|]+[\\/])*[^\s\"'<>|]+)")
_POSIX_PATH_RE = re.compile(r"(?:(?<=^)|(?<=[\s\"'(<\[]))(/(?:[^/\s]+/)*[^/\s]+)")


def _sanitize_text(value: str) -> str:
    sanitized = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    sanitized = _WINDOWS_PATH_RE.sub("<path>", sanitized)
    sanitized = _POSIX_PATH_RE.sub("<path>", sanitized)
    return sanitized


def _is_secret_key(key: str) -> bool:
    return bool(
        re.search(r"(?i)(api[_-]?key|token|secret|password|passwd|session|authorization)", key)
    )


def _sanitize_public_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return _sanitize_text(value) if isinstance(value, str) else value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return _sanitize_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, Path):
        return _sanitize_text(value.name or "<path>")
    if isinstance(value, Enum):
        return _sanitize_public_value(value.value)
    if dataclasses.is_dataclass(value):
        return _sanitize_public_value(dataclasses.asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _sanitize_public_value(model_dump())
    if isinstance(value, BaseException):
        return {
            "type": value.__class__.__name__,
            "message": "Job failed",
        }
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            sanitized[key] = "<redacted>" if _is_secret_key(key) else _sanitize_public_value(raw_value)
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize_public_value(item) for item in value]
    if inspect.isawaitable(value):
        return "<awaitable>"
    return {"type": value.__class__.__name__}


def _normalize_artifacts(
    artifact: Any | None = None,
    artifacts: Sequence[Any] | Mapping[str, Any] | Any | None = None,
) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if artifact is not None:
        candidates.append(artifact)
    if artifacts is not None:
        if isinstance(artifacts, Mapping):
            candidates.append(artifacts)
        elif isinstance(artifacts, (list, tuple, set, frozenset)):
            candidates.extend(artifacts)
        else:
            candidates.append(artifacts)

    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        payload = _sanitize_public_value(candidate)
        if isinstance(payload, dict):
            normalized.append(payload)
        else:
            normalized.append({"value": payload})
    return normalized


@dataclass(slots=True)
class JobReference:
    job_id: str
    status: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    idempotency_key: str | None = None
    progress: float | None = None
    message: str | None = None
    result: Any = None
    error: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "idempotency_key": self.idempotency_key,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "artifacts": self.artifacts,
        }

    model_dump = to_dict


JobResult = JobReference


@dataclass(slots=True)
class _JobRecord:
    job_id: str
    func: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    accepts_context: bool
    idempotency_key: str | None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: JobStatus = JobStatus.queued
    progress: float | None = None
    message: str | None = None
    result: Any = None
    error: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[Any] | None = None
    loop: asyncio.AbstractEventLoop | None = None

    def snapshot(self) -> JobReference:
        return JobReference(
            job_id=self.job_id,
            status=self.status.value,
            created_at=_isoformat(self.created_at) or "",
            updated_at=_isoformat(self.updated_at) or "",
            started_at=_isoformat(self.started_at),
            finished_at=_isoformat(self.finished_at),
            idempotency_key=self.idempotency_key,
            progress=self.progress,
            message=self.message,
            result=self.result,
            error=self.error,
            artifacts=list(self.artifacts),
        )

    @property
    def terminal(self) -> bool:
        return self.status in {
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.cancelled,
        }


@dataclass(slots=True)
class JobContext:
    job_id: str
    _manager: "JobManager"
    _loop: asyncio.AbstractEventLoop
    _cancel_event: threading.Event

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    async def update_progress(
        self,
        *,
        progress: float | None = None,
        message: str | None = None,
        artifact: Any | None = None,
        artifacts: Sequence[Any] | Mapping[str, Any] | Any | None = None,
    ) -> JobReference | None:
        return await self._manager.update_progress(
            self.job_id,
            progress=progress,
            message=message,
            artifact=artifact,
            artifacts=artifacts,
        )

    def update_progress_nowait(
        self,
        *,
        progress: float | None = None,
        message: str | None = None,
        artifact: Any | None = None,
        artifacts: Sequence[Any] | Mapping[str, Any] | Any | None = None,
    ) -> ConcurrentFuture[JobReference | None]:
        return asyncio.run_coroutine_threadsafe(
            self._manager.update_progress(
                self.job_id,
                progress=progress,
                message=message,
                artifact=artifact,
                artifacts=artifacts,
            ),
            self._loop,
        )

    async def add_artifact(self, artifact: Any) -> JobReference | None:
        return await self._manager.update_progress(self.job_id, artifact=artifact)

    def add_artifact_nowait(self, artifact: Any) -> ConcurrentFuture[JobReference | None]:
        return asyncio.run_coroutine_threadsafe(
            self._manager.update_progress(self.job_id, artifact=artifact),
            self._loop,
        )


class JobManager:
    def __init__(
        self,
        *,
        max_active_jobs: int = 64,
        max_retained_jobs: int = 128,
        max_artifacts_per_job: int = 16,
        retention_ttl_seconds: float = 3600.0,
    ) -> None:
        if max_active_jobs < 0:
            raise ValueError("max_active_jobs must be non-negative")
        if max_retained_jobs < 0:
            raise ValueError("max_retained_jobs must be non-negative")
        if max_artifacts_per_job < 0:
            raise ValueError("max_artifacts_per_job must be non-negative")
        if retention_ttl_seconds < 0:
            raise ValueError("retention_ttl_seconds must be non-negative")
        self._bound_loop: asyncio.AbstractEventLoop | None = None
        self._max_active_jobs = max_active_jobs
        self._max_retained_jobs = max_retained_jobs
        self._max_artifacts_per_job = max_artifacts_per_job
        self._retention_ttl_seconds = retention_ttl_seconds
        self._jobs: dict[str, _JobRecord] = {}
        self._idempotency_index: dict[str, str] = {}
        self._terminal_order: Deque[str] = deque()
        self._lock = asyncio.Lock()
        self._shutdown = False
        self._shutdown_event = asyncio.Event()

    async def submit(
        self,
        func: Callable[..., Any],
        /,
        *args: Any,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> JobReference:
        self._ensure_loop()
        async with self._lock:
            if self._shutdown:
                raise RuntimeError("JobManager is shut down")
            self._prune_locked()
            if idempotency_key:
                existing_id = self._idempotency_index.get(idempotency_key)
                if existing_id:
                    existing = self._jobs.get(existing_id)
                    if existing is not None:
                        return existing.snapshot()
                    self._idempotency_index.pop(idempotency_key, None)
            if self._active_count_locked() >= self._max_active_jobs:
                raise RuntimeError("JobManager active job capacity reached")

            job_id = uuid.uuid4().hex
            record = _JobRecord(
                job_id=job_id,
                func=func,
                args=args,
                kwargs=dict(kwargs),
                accepts_context=_accepts_context(func),
                idempotency_key=idempotency_key,
            )
            loop = asyncio.get_running_loop()
            record.loop = loop
            task = loop.create_task(self._run_job(job_id))
            record.task = task
            self._jobs[job_id] = record
            if idempotency_key:
                self._idempotency_index[idempotency_key] = job_id
            return record.snapshot()

    async def get(self, job_id: str) -> JobReference | None:
        self._ensure_loop()
        async with self._lock:
            self._prune_locked()
            record = self._jobs.get(job_id)
            return None if record is None else record.snapshot()

    async def cancel(self, job_id: str) -> JobReference | None:
        self._ensure_loop()
        async with self._lock:
            self._prune_locked()
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if record.terminal:
                return record.snapshot()
            record.cancel_event.set()
            record.status = JobStatus.cancelled
            record.finished_at = _utc_now()
            record.updated_at = record.finished_at
            task = record.task
            if task is not None and not task.done():
                task.cancel()
            self._mark_terminal_locked(record)
            return record.snapshot()

    async def update_progress(
        self,
        job_id: str,
        *,
        progress: float | None = None,
        message: str | None = None,
        artifact: Any | None = None,
        artifacts: Sequence[Any] | Mapping[str, Any] | Any | None = None,
    ) -> JobReference | None:
        self._ensure_loop()
        async with self._lock:
            self._prune_locked()
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if record.terminal:
                return record.snapshot()
            if progress is not None:
                value = float(progress)
                if not math.isfinite(value):
                    raise ValueError("progress must be finite")
                record.progress = max(0.0, min(100.0, value))
            if message is not None:
                record.message = _sanitize_text(message)
            new_artifacts = _normalize_artifacts(artifact=artifact, artifacts=artifacts)
            if new_artifacts:
                record.artifacts.extend(new_artifacts)
                if len(record.artifacts) > self._max_artifacts_per_job:
                    if self._max_artifacts_per_job == 0:
                        record.artifacts.clear()
                    else:
                        record.artifacts[:] = record.artifacts[-self._max_artifacts_per_job :]
            record.updated_at = _utc_now()
            return record.snapshot()

    async def shutdown(self, *, cancel_running: bool = False) -> None:
        self._ensure_loop()
        async with self._lock:
            self._shutdown = True
            active_tasks = [
                record.task
                for record in self._jobs.values()
                if record.task is not None and not record.task.done()
            ]
            active_records = [
                record
                for record in self._jobs.values()
                if record.task is not None and not record.task.done()
            ]
            if cancel_running:
                for record in active_records:
                    record.cancel_event.set()
                    record.status = JobStatus.cancelled
                    record.finished_at = _utc_now()
                    record.updated_at = record.finished_at
                    record.task.cancel()
                    self._mark_terminal_locked(record)
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        async with self._lock:
            self._prune_locked()
            self._shutdown_event.set()

    async def __aenter__(self) -> "JobManager":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.shutdown()

    async def _run_job(self, job_id: str) -> None:
        try:
            async with self._lock:
                record = self._jobs.get(job_id)
                if record is None:
                    return
                if record.status == JobStatus.cancelled:
                    return
                record.status = JobStatus.running
                record.started_at = record.started_at or _utc_now()
                record.updated_at = _utc_now()
                context = JobContext(
                    job_id=record.job_id,
                    _manager=self,
                    _loop=record.loop or asyncio.get_running_loop(),
                    _cancel_event=record.cancel_event,
                )
                func = record.func
                args = record.args
                kwargs = dict(record.kwargs)
                if record.accepts_context and "context" not in kwargs:
                    kwargs["context"] = context
            result = await self._invoke(func, args, kwargs)
            sanitized_result = _sanitize_public_value(result)
        except asyncio.CancelledError:
            async with self._lock:
                record = self._jobs.get(job_id)
                if record is not None:
                    record.cancel_event.set()
                    record.status = JobStatus.cancelled
                    if record.finished_at is None:
                        record.finished_at = _utc_now()
                    record.updated_at = _utc_now()
                    self._mark_terminal_locked(record)
            return
        except Exception as exc:  # noqa: BLE001
            async with self._lock:
                record = self._jobs.get(job_id)
                if record is None or record.status == JobStatus.cancelled:
                    return
                record.status = JobStatus.failed
                record.error = {
                    "type": exc.__class__.__name__,
                    "message": "Job failed",
                }
                record.finished_at = _utc_now()
                record.updated_at = record.finished_at
                self._mark_terminal_locked(record)
            return

        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            if record.status == JobStatus.cancelled:
                return
            record.status = JobStatus.completed
            record.result = sanitized_result
            record.finished_at = _utc_now()
            record.updated_at = record.finished_at
            self._mark_terminal_locked(record)

    async def _invoke(self, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        if inspect.isawaitable(result):
            return await result
        return result

    def _mark_terminal_locked(self, record: _JobRecord) -> None:
        if record.job_id not in self._terminal_order:
            self._terminal_order.append(record.job_id)
        self._prune_locked()

    def _ensure_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._bound_loop is None:
            self._bound_loop = loop
            return
        if self._bound_loop is not loop:
            raise RuntimeError(
                "JobManager is bound to a different event loop; keep one persistent loop for this manager"
            )

    def _active_count_locked(self) -> int:
        return sum(1 for record in self._jobs.values() if not record.terminal)

    def _prune_locked(self) -> None:
        now = _utc_now()
        if self._max_retained_jobs == 0:
            while self._terminal_order:
                job_id = self._terminal_order.popleft()
                record = self._jobs.get(job_id)
                if record is None or not record.terminal:
                    continue
                self._jobs.pop(job_id, None)
                if record.idempotency_key:
                    current = self._idempotency_index.get(record.idempotency_key)
                    if current == job_id:
                        self._idempotency_index.pop(record.idempotency_key, None)
            return

        while self._terminal_order:
            job_id = self._terminal_order[0]
            record = self._jobs.get(job_id)
            if record is None:
                self._terminal_order.popleft()
                continue
            if not record.terminal:
                self._terminal_order.popleft()
                continue
            age_seconds = (
                (now - record.finished_at).total_seconds()
                if record.finished_at is not None
                else 0.0
            )
            over_age = age_seconds > self._retention_ttl_seconds
            over_count = len(self._terminal_order) > self._max_retained_jobs
            if not over_age and not over_count:
                break
            self._terminal_order.popleft()
            self._jobs.pop(job_id, None)
            if record.idempotency_key:
                current = self._idempotency_index.get(record.idempotency_key)
                if current == job_id:
                    self._idempotency_index.pop(record.idempotency_key, None)


def _accepts_context(func: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == "context":
            return True
    return False
