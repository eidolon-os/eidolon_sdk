"""Server-Sent Events framing helpers.

The SDK provides protocol framing only. Connection lifecycle, auth, routing,
and retry policies remain in the owning service.
"""

from __future__ import annotations

import json
from typing import Any

SSE_HEARTBEAT_COMMENT = "keepalive"
SSE_HEARTBEAT_BYTES = b": keepalive\n\n"


def encode_sse_comment(comment: str = SSE_HEARTBEAT_COMMENT) -> bytes:
    """Return an SSE comment frame."""

    return f": {comment}\n\n".encode("utf-8")


def encode_sse_event(
    event: str, data: dict[str, Any], *, event_id: str | None = None
) -> bytes:
    """Return a JSON Server-Sent Event frame.

    ``event_id`` emits the protocol's own cursor. A browser remembers the last
    id it saw and sends it back as ``Last-Event-ID`` when it reconnects, so a
    stream that stamps its frames can resume where the reader stopped instead of
    starting at "now" and losing whatever happened while the connection was
    down. Frames from a source that has no position — a keepalive, a hello, a
    proxied substream — are left unstamped on purpose: an id that does not mean
    a position would overwrite one that does.

    Newlines are stripped from the id rather than escaped: SSE has no escaping
    and a newline there would end the field early, splitting one frame into two.
    """

    stamp = ""
    if event_id:
        stamp = f"id: {event_id.replace(chr(10), ' ').replace(chr(13), ' ')}\n"
    return (
        f"{stamp}"
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    ).encode("utf-8")
