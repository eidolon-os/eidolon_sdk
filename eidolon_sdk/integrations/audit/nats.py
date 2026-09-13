"""Fail-fast NATS JetStream publisher for authority-local audit outboxes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from eidolon_sdk.biz.audit import AuditEnvelope

from .stream import (
    AUDIT_STREAM_NAME,
    AUDIT_SUBJECT_PREFIX,
    audit_subject,
    ensure_audit_stream,
)


class AuditPublishError(RuntimeError):
    """A publish that failed, described well enough to act on.

    Carries the original as ``__cause__``; what it adds is the context the
    transport's own message leaves out.
    """


#: One failure in how many is worth a log line.
#:
#: The dispatchers' backoff caps at sixty seconds, so an attempt count is very
#: nearly a minute count and this is very nearly hourly. The first failure is
#: always reported — the thing worth knowing is *when it started*, and a Host
#: that recovers on its second attempt should still have said so once.
FAILURE_REPORT_EVERY = 60


def should_report_publish_failure(attempt_count: int) -> bool:
    """Whether this attempt is one to log, rather than only to record.

    A dispatcher catches transport failures into its outbox on purpose: a bus
    that is down must not take an authority with it. But catching and hiding are
    different, and this had been both — 5336 failures over six days produced
    exactly zero log lines, because the only record was a column no operator
    reads. Logging every attempt would replace silence with noise, which is the
    same defect wearing the other hat.
    """

    if attempt_count <= 1:
        return True
    return attempt_count % FAILURE_REPORT_EVERY == 0


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

        try:
            return set(await asyncio.gather(*(_publish(item) for item in events)))
        except Exception as error:
            raise AuditPublishError(
                await self._describe_failure(error, events[0].producer)
            ) from error

    async def _describe_failure(self, error: Exception, producer: str) -> str:
        """Turn a transport error into a line somebody can act on.

        ``nats: timeout`` names nothing — not the stream, not the subject, not
        whether the broker even knows about either — and it is the whole of what
        one Host had to go on while a publish failed every minute for six days.

        The broker does not publish its own storage failures anywhere a client
        can subscribe: they go to its log and nowhere else. What a client *can*
        do is say which of its own questions the broker answered. A broker that
        describes the stream but will not store into it is a specific, findable
        state — a stream whose directory was removed under a running server
        behaves exactly that way — and saying so points at the broker's log
        instead of leaving a timeout to look like a network problem.
        """

        detail = f"{type(error).__name__}: {error}"
        described = f"publishing to {AUDIT_STREAM_NAME} as {audit_subject(producer)} failed — {detail}"
        jetstream = self._jetstream
        if jetstream is None:
            return described
        try:
            info = await jetstream.stream_info(AUDIT_STREAM_NAME)
            state = f"messages={info.state.messages}, last_seq={info.state.last_seq}"
        except Exception as probe_error:  # noqa: BLE001 - diagnosis, never a new failure
            # Reading the answer is inside the guard along with asking for it. A
            # diagnostic that raises replaces the fault it was called to explain,
            # which is worse than the opaque message it set out to improve on.
            return (
                f"{described}; the broker could not describe {AUDIT_STREAM_NAME} either "
                f"({type(probe_error).__name__}: {probe_error})"
            )
        return (
            f"{described}; the broker still describes {AUDIT_STREAM_NAME} ({state}) but "
            "did not store this one — the reason is in the broker's own log, which it "
            "does not publish to any subject"
        )


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
