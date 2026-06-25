from __future__ import annotations

import json

from eidolon_sdk.core.streaming import SSE_HEARTBEAT_BYTES, encode_sse_comment, encode_sse_event


def test_encode_sse_comment_matches_heartbeat_contract() -> None:
    assert encode_sse_comment() == SSE_HEARTBEAT_BYTES


def test_encode_sse_event_serializes_json_data() -> None:
    raw = encode_sse_event("event", {"text": "你好", "ok": True}).decode("utf-8")
    lines = raw.splitlines()

    assert lines[0] == "event: event"
    assert json.loads(lines[1].removeprefix("data: ")) == {"text": "你好", "ok": True}
