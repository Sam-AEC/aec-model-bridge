from __future__ import annotations

import asyncio
import threading
import time

import pytest

from revit_mcp_server.jobs import JobManager


async def wait_for_status(job_manager: JobManager, job_id: str, statuses: set[str], timeout: float = 1.5):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        snapshot = await job_manager.get(job_id)
        assert snapshot is not None
        if snapshot.status in statuses:
            return snapshot
        if loop.time() >= deadline:
            raise AssertionError(f"Timed out waiting for {statuses}, last status was {snapshot.status}")
        await asyncio.sleep(0.01)


def test_submit_returns_immediately_for_sync_jobs_and_completes():
    async def main():
        manager = JobManager()
        started = threading.Event()
        release = threading.Event()

        def job():
            started.set()
            release.wait(1)
            return {"output_path": r"C:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\out.rvt", "count": 3}

        reference = await manager.submit(job)
        assert reference.status in {"queued", "running"}

        await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 0.5)
        current = await manager.get(reference.job_id)
        assert current is not None
        assert current.status in {"queued", "running"}

        release.set()
        finished = await wait_for_status(manager, reference.job_id, {"completed"})
        assert finished.result == {"output_path": "<path>", "count": 3}

    asyncio.run(main())


def test_active_capacity_blocks_new_non_idempotent_jobs_but_allows_retries():
    async def main():
        manager = JobManager(max_active_jobs=1)
        gate = asyncio.Event()

        async def job():
            await gate.wait()
            return {"done": True}

        first = await manager.submit(job, idempotency_key="revit:capacity-1")
        retry = await manager.submit(job, idempotency_key="revit:capacity-1")
        assert retry.job_id == first.job_id

        with pytest.raises(RuntimeError, match="active job capacity"):
            await manager.submit(job)

        gate.set()
        finished = await wait_for_status(manager, first.job_id, {"completed"})
        assert finished.result == {"done": True}

    asyncio.run(main())


def test_async_completion_preserves_json_safe_result():
    async def main():
        manager = JobManager()

        async def job():
            await asyncio.sleep(0.02)
            return {"ok": True, "items": [1, 2, 3]}

        reference = await manager.submit(job)
        finished = await wait_for_status(manager, reference.job_id, {"completed"})
        assert finished.result == {"ok": True, "items": [1, 2, 3]}
        assert finished.error is None

    asyncio.run(main())


def test_artifacts_are_bounded_per_job():
    async def main():
        manager = JobManager(max_artifacts_per_job=2)

        async def job(context):
            await context.update_progress(artifact={"name": "one"})
            await context.update_progress(artifact={"name": "two"})
            await context.update_progress(artifact={"name": "three"})
            return {"ok": True}

        reference = await manager.submit(job)
        finished = await wait_for_status(manager, reference.job_id, {"completed"})
        assert [artifact["name"] for artifact in finished.artifacts] == ["two", "three"]
        assert len(finished.artifacts) == 2

    asyncio.run(main())


def test_failure_redacts_secret_and_path_details():
    async def main():
        manager = JobManager()
        secret = "super-secret-token"
        leaked_path = r"C:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\private\vault.rvt"

        async def job():
            raise RuntimeError(f"failed for {leaked_path} token={secret}")

        reference = await manager.submit(job)
        failed = await wait_for_status(manager, reference.job_id, {"failed"})
        assert failed.result is None
        assert failed.error is not None
        assert failed.error["type"] == "RuntimeError"
        error_text = failed.error["message"]
        assert secret not in error_text
        assert leaked_path not in error_text
        assert "Traceback" not in error_text

    asyncio.run(main())


def test_non_finite_progress_is_rejected():
    async def main():
        manager = JobManager()

        async def job(context):
            with pytest.raises(ValueError, match="progress must be finite"):
                await context.update_progress(progress=float("nan"))
            with pytest.raises(ValueError, match="progress must be finite"):
                await context.update_progress(progress=float("inf"))
            await context.update_progress(progress=42.0, message="recover")
            return {"ok": True}

        reference = await manager.submit(job)
        finished = await wait_for_status(manager, reference.job_id, {"completed"})
        assert finished.progress == 42.0
        assert finished.message == "recover"
        assert finished.result == {"ok": True}

    asyncio.run(main())


def test_cancellation_marks_job_cancelled():
    async def main():
        manager = JobManager()
        started = asyncio.Event()
        release = asyncio.Event()

        async def job(context):
            await context.update_progress(progress=10, message="running")
            started.set()
            await release.wait()
            return {"should_not": "complete"}

        reference = await manager.submit(job)
        await asyncio.wait_for(started.wait(), 0.5)
        cancelled = await manager.cancel(reference.job_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        release.set()
        snapshot = await wait_for_status(manager, reference.job_id, {"cancelled"})
        assert snapshot.result is None
        assert snapshot.error is None

    asyncio.run(main())


def test_shutdown_can_cancel_running_jobs():
    async def main():
        manager = JobManager()
        started = asyncio.Event()

        async def job():
            started.set()
            await asyncio.sleep(10)
            return {"ok": True}

        reference = await manager.submit(job)
        await asyncio.wait_for(started.wait(), 0.5)
        await manager.shutdown(cancel_running=True)

        snapshot = await manager.get(reference.job_id)
        assert snapshot is not None
        assert snapshot.status == "cancelled"
        assert snapshot.result is None
        assert snapshot.error is None

        with pytest.raises(RuntimeError):
            await manager.submit(job)

    asyncio.run(main())


def test_idempotency_reuses_active_and_completed_jobs():
    async def main():
        manager = JobManager()
        gate = asyncio.Event()

        async def job():
            await gate.wait()
            return {"done": True}

        first = await manager.submit(job, idempotency_key="revit:op-1")
        second = await manager.submit(job, idempotency_key="revit:op-1")
        assert second.job_id == first.job_id

        gate.set()
        finished = await wait_for_status(manager, first.job_id, {"completed"})
        third = await manager.submit(job, idempotency_key="revit:op-1")
        assert third.job_id == first.job_id
        assert third.status == "completed"
        assert third.result == {"done": True}
        assert finished.result == {"done": True}

    asyncio.run(main())


def test_manager_is_bound_to_first_event_loop():
    manager = JobManager()
    job_id_holder: dict[str, str] = {}

    async def first_loop():
        async def job():
            return {"ok": True}

        reference = await manager.submit(job)
        job_id_holder["job_id"] = reference.job_id
        await wait_for_status(manager, reference.job_id, {"completed"})

    asyncio.run(first_loop())

    async def second_loop():
        with pytest.raises(RuntimeError, match="different event loop"):
            await manager.get(job_id_holder["job_id"])

    asyncio.run(second_loop())


def test_progress_updates_are_visible_while_running():
    async def main():
        manager = JobManager()
        first_update = asyncio.Event()
        finish = asyncio.Event()

        async def job(context):
            await context.update_progress(progress=15, message="phase 1")
            first_update.set()
            await finish.wait()
            await context.update_progress(
                progress=100,
                message="phase 2",
                artifact={"name": "model", "path": r"C:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\exports\model.ifc"},
            )
            return {"ok": True}

        reference = await manager.submit(job)
        await asyncio.wait_for(first_update.wait(), 0.5)
        snapshot = await manager.get(reference.job_id)
        assert snapshot is not None
        assert snapshot.status == "running"
        assert snapshot.progress == 15
        assert snapshot.message == "phase 1"

        finish.set()
        done = await wait_for_status(manager, reference.job_id, {"completed"})
        assert done.progress == 100
        assert done.message == "phase 2"
        assert done.artifacts
        assert done.artifacts[0]["name"] == "model"
        assert "<path>" in done.artifacts[0]["path"]

    asyncio.run(main())


def test_retention_prunes_old_terminal_jobs():
    async def main():
        manager = JobManager(max_retained_jobs=1, retention_ttl_seconds=60.0)

        async def job(value: int):
            return {"value": value}

        first = await manager.submit(job, 1)
        await wait_for_status(manager, first.job_id, {"completed"})
        second = await manager.submit(job, 2)
        await wait_for_status(manager, second.job_id, {"completed"})

        assert await manager.get(first.job_id) is None
        retained = await manager.get(second.job_id)
        assert retained is not None
        assert retained.result == {"value": 2}

    asyncio.run(main())


def test_shutdown_waits_for_running_jobs_and_rejects_new_submissions():
    async def main():
        manager = JobManager()
        finished = asyncio.Event()

        async def job():
            await asyncio.sleep(0.02)
            finished.set()
            return {"ok": True}

        reference = await manager.submit(job)
        await manager.shutdown()
        assert finished.is_set()

        snapshot = await manager.get(reference.job_id)
        assert snapshot is not None
        assert snapshot.status == "completed"
        assert snapshot.result == {"ok": True}

        with pytest.raises(RuntimeError):
            await manager.submit(job)

    asyncio.run(main())
