"""Fail-fast NATS JetStream publisher for authority-local audit outboxes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from eidolon_sdk.biz.audit import AuditEnvelope

from .stream import AUDIT_SUBJECT_PREFIX, audit_subject, ensure_audit_stream


@dataclass(frozen=True)
class AuditNatsPublisherSettings:
    url: str = "nats://127.0.0.1:4222"
    subject_prefix: str = AUDIT_SUBJECT_PREFIX
    connect_timeout_seconds: float = 2.0
    reconnect_attempts: int = 3
    reconnect_wait_seconds: float = 0.25
    publish_timeout_seconds: float = 2.0
    publish_concurrency: int = 32


class JetStreamAuditPublisher:
    """Publish batches without owning consumer policy.

    It does ensure the stream exists — see :mod:`.stream` for why that is a
    publisher's job and not only a consumer's.
    """

    def __init__(
        self,
        settings: AuditNatsPublisherSettings | None = None,
        *,
        connection_name: str = "eidolon-audit-publisher",
    ) -> None:
        self.settings = settings or AuditNatsPublisherSettings()
        self._connection_name = connection_name
        self._connection: Any | None = None
        self._jetstream: Any | None = None

    async def connect(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            return
        self._connection = None
        self._jetstream = None
        nats = _nats_module()
        connection = await nats.connect(
            self.settings.url,
            name=self._connection_name,
            allow_reconnect=True,
            connect_timeout=self.settings.connect_timeout_seconds,
            max_reconnect_attempts=self.settings.reconnect_attempts,
            reconnect_time_wait=self.settings.reconnect_wait_seconds,
        )
        jetstream = connection.jetstream()
        try:
            await ensure_audit_stream(jetstream)
        except Exception:
            await connection.close()
            raise
        self._connection = connection
        self._jetstream = jetstream

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        self._jetstream = None
        if connection is None:
            return
        try:
            await asyncio.wait_for(connection.drain(), timeout=2.0)
        except TimeoutError:
            await connection.close()

    async def publish_many(self, events: list[AuditEnvelope]) -> set[str]:
        if not events:
            return set()
        await self.connect()
        jetstream = self._jetstream
        assert jetstream is not None
        concurrency = max(1, self.settings.publish_concurrency)
        semaphore = asyncio.Semaphore(concurrency)

        async def _publish(item: AuditEnvelope) -> str:
            subject = audit_subject(item.producer)
            async with semaphore:
                await jetstream.publish(
                    subject,
                    item.model_dump_json(exclude_none=False).encode("utf-8"),
                    timeout=self.settings.publish_timeout_seconds,
                    headers={"Nats-Msg-Id": item.event_id},
                )
            return item.event_id

        return set(await asyncio.gather(*(_publish(item) for item in events)))


def require_audit_transport() -> None:
    """Fail now if this process cannot publish, rather than once per batch.

    An authority that was given an audit URL has claimed it can reach the global
    stream. Without the ``audit`` extra installed it cannot, and the only place
    that used to say so was the exception from the first publish — which the
    dispatcher catches and writes to ``last_error``, a column no operator reads.
    One Host retried 5336 times over six days that way, answering /health with
    200 and logging nothing.

    So the claim is checked where it is made: at startup, before the dispatcher
    exists. A missing dependency is a broken deployment, not a passing outage,
    and refusing to start names it while somebody is still watching. A bus that
    is merely *down* is the opposite and must stay tolerated — the rows wait,
    and their Owner can still read them.
    """

    _nats_module()


def _nats_module():
    try:
        import nats
    except ImportError as exc:  # pragma: no cover - deployment optional extra
        raise RuntimeError("install eidolon-sdk[audit] to publish global audit") from exc
    return nats
