from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nats.js.errors import NotFoundError

from eidolon_sdk.biz.audit import AuditEnvelope
from eidolon_sdk.integrations.audit import (
    AUDIT_STREAM_NAME,
    AuditNatsPublisherSettings,
    JetStreamAuditPublisher,
    require_audit_transport,
)


class _JetStream:
    def __init__(self, *, stream_exists: bool = True) -> None:
        self.calls = []
        self.added = []
        self._stream_exists = stream_exists

    async def publish(self, subject, payload, **kwargs):
        self.calls.append((subject, payload, kwargs))

    async def stream_info(self, name):
        if self._stream_exists:
            return SimpleNamespace(config=SimpleNamespace(name=name))
        raise NotFoundError()

    async def add_stream(self, config):
        self.added.append(config)
        self._stream_exists = True


class _Connection:
    is_closed = False

    def __init__(self, *, stream_exists: bool = True) -> None:
        self.js = _JetStream(stream_exists=stream_exists)
        self.drained = False

    def jetstream(self):
        return self.js

    async def drain(self):
        self.drained = True

    async def close(self):
        self.is_closed = True


async def test_publisher_uses_deduplication_header_and_bounded_connect(monkeypatch) -> None:
    connection = _Connection()
    connect_values = {}

    async def _connect(url, **kwargs):
        connect_values.update({"url": url, **kwargs})
        return connection

    monkeypatch.setattr(
        "eidolon_sdk.integrations.audit.nats._nats_module",
        lambda: SimpleNamespace(connect=_connect),
    )
    settings = AuditNatsPublisherSettings(
        url="nats://test:4222",
        connect_timeout_seconds=1.5,
        reconnect_attempts=2,
        publish_concurrency=1,
    )
    publisher = JetStreamAuditPublisher(settings)
    event = AuditEnvelope(
        event_id="audit-1",
        producer="eidolon/kernel",
        producer_seq=1,
        category="governance",
        subject_type="mount",
        subject_id="device-1",
        action="mount.created",
        occurred_at=datetime.now(UTC),
    )

    assert await publisher.publish_many([event]) == {"audit-1"}
    assert connect_values["connect_timeout"] == 1.5
    assert connect_values["max_reconnect_attempts"] == 2
    subject, _, publish_values = connection.js.calls[0]
    assert subject == "eidolon.audit.v1.eidolon_kernel"
    assert publish_values["headers"] == {"Nats-Msg-Id": "audit-1"}
    assert publish_values["timeout"] == 2.0
    await publisher.close()
    assert connection.drained is True


async def test_a_publisher_creates_the_stream_it_publishes_into(monkeypatch) -> None:
    """The dependency used to point the other way.

    Only Admin's indexer created the audit stream, so a Host whose Admin was not
    running had none — and every authority's dispatcher published into nothing.
    Governance transport must not hang on an Owner-facing component being up.
    """

    connection = _Connection(stream_exists=False)

    async def _connect(url, **kwargs):
        return connection

    monkeypatch.setattr(
        "eidolon_sdk.integrations.audit.nats._nats_module",
        lambda: SimpleNamespace(connect=_connect),
    )
    publisher = JetStreamAuditPublisher(AuditNatsPublisherSettings())

    await publisher.connect()

    assert [config.name for config in connection.js.added] == [AUDIT_STREAM_NAME]
    assert connection.js.added[0].subjects == ["eidolon.audit.v1.>"]
    await publisher.close()


async def test_an_existing_stream_is_left_exactly_as_the_operator_has_it(
    monkeypatch,
) -> None:
    """Create, never update: a widened retention window must survive a restart."""

    connection = _Connection(stream_exists=True)

    async def _connect(url, **kwargs):
        return connection

    monkeypatch.setattr(
        "eidolon_sdk.integrations.audit.nats._nats_module",
        lambda: SimpleNamespace(connect=_connect),
    )
    publisher = JetStreamAuditPublisher(AuditNatsPublisherSettings())

    await publisher.connect()

    assert connection.js.added == []
    await publisher.close()


def test_a_host_that_cannot_publish_says_so_before_it_serves(monkeypatch) -> None:
    """The check an authority owes for the capability it was configured with.

    Without it the only report was an exception per batch, which the dispatcher
    writes to ``last_error`` — a column no operator reads. One Host retried 5336
    times over six days while answering /health with 200.
    """

    def _missing():
        raise RuntimeError("install eidolon-sdk[audit] to publish global audit")

    monkeypatch.setattr(
        "eidolon_sdk.integrations.audit.nats._nats_module", _missing
    )

    with pytest.raises(RuntimeError, match=r"eidolon-sdk\[audit\]"):
        require_audit_transport()
