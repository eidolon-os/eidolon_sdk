"""Compatibility exports for :mod:`eidolon_sdk.core.streaming`."""

from eidolon_sdk.core.streaming import (
    SSE_HEARTBEAT_BYTES,
    SSE_HEARTBEAT_COMMENT,
    encode_sse_comment,
    encode_sse_event,
)

__all__ = [
    "SSE_HEARTBEAT_BYTES",
    "SSE_HEARTBEAT_COMMENT",
    "encode_sse_comment",
    "encode_sse_event",
]
