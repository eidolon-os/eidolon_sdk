"""BackgroundTaskRunner behavior."""

from __future__ import annotations

import asyncio

from eidolon_sdk.core.runtime import BackgroundTaskRunner


async def test_drain_waits_for_scheduled_task() -> None:
    runner = BackgroundTaskRunner(component="test")
    finished = asyncio.Event()

    async def _work() -> None:
        await asyncio.sleep(0)
        finished.set()

    task = runner.create(_work(), name="work")

    await runner.drain(timeout_s=1)

    assert finished.is_set()
    assert task.get_name() == "test:work"
    assert runner.pending_count == 0


async def test_task_exception_is_observed_and_removed() -> None:
    runner = BackgroundTaskRunner(component="test")

    async def _boom() -> None:
        raise RuntimeError("boom")

    runner.create(_boom(), name="boom")

    await runner.drain(timeout_s=1)

    assert runner.pending_count == 0


async def test_cancel_and_drain_cancels_pending_tasks() -> None:
    runner = BackgroundTaskRunner(component="test")
    started = asyncio.Event()

    async def _wait() -> None:
        started.set()
        await asyncio.sleep(60)

    task = runner.create(_wait(), name="wait")
    await asyncio.wait_for(started.wait(), timeout=1)

    await runner.cancel_and_drain(timeout_s=1)

    assert task.cancelled()
    assert runner.pending_count == 0
