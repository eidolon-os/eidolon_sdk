from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from eidolon_sdk.biz.audit import AuditEnvelope
from eidolon_sdk.integrations.audit import (
    AuditNatsPublisherSettings,
    JetStreamAuditPublisher,
)


class _JetStream:
    def __init__(self) -> None:
        self.calls = []

    async def publish(self, subject, payload, **kwargs):
        self.calls.append((subject, payload, kwargs))


class _Connection:
    is_closed = False

    def __init__(self) -> None:
        self.js = _JetStream()
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
