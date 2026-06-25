"""Supervised asyncio background task utilities."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

_log = logging.getLogger(__name__)


class BackgroundTaskRunner:
    """Track fire-and-forget tasks so exceptions and shutdown are controlled."""

    def __init__(self, *, component: str = "background") -> None:
        self.component = component
        self._tasks: set[asyncio.Task[Any]] = set()

    def create(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str,
    ) -> asyncio.Task[Any]:
        task_name = f"{self.component}:{name}" if self.component else name
        task = asyncio.create_task(coro, name=task_name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    async def drain(self, *, timeout_s: float = 5.0) -> None:
        if not self._tasks:
            return
        pending = list(self._tasks)
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            _log.warning(
                "background task drain timed out component=%s pending=%d timeout_s=%.2f",
                self.component,
                len(self._tasks),
                timeout_s,
            )

    async def cancel_and_drain(self, *, timeout_s: float = 5.0) -> None:
        for task in list(self._tasks):
            task.cancel()
        await self.drain(timeout_s=timeout_s)

    @property
    def pending_count(self) -> int:
        return len(self._tasks)

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            _log.error(
                "background task failed component=%s name=%s",
                self.component,
                task.get_name(),
                exc_info=(type(exc), exc, exc.__traceback__),
            )


__all__ = ["BackgroundTaskRunner"]
