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


def encode_sse_event(event: str, data: dict[str, Any]) -> bytes:
    """Return a JSON Server-Sent Event frame."""

    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    ).encode("utf-8")
