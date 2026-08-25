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


def test_a_stamped_frame_carries_the_protocols_own_cursor() -> None:
    """So a reader that drops the connection can resume where it stopped.

    A browser remembers the last id it saw and sends it back as
    ``Last-Event-ID``; a stream whose frames carry no id can only start at
    "now", which loses whatever happened while the connection was down.
    """

    raw = encode_sse_event("runtime_event", {"ok": True}, event_id="2026-08-25T09:00:00+00:00").decode(
        "utf-8"
    )

    assert raw.startswith("id: 2026-08-25T09:00:00+00:00\n")
    assert "event: runtime_event\n" in raw


def test_a_frame_with_no_position_is_left_unstamped() -> None:
    """An id that does not mean a position would overwrite one that does.

    Keepalives, hellos and proxied substreams have no cursor of their own, and
    stamping them would move the reader's resume point to something it cannot
    resume from.
    """

    assert not encode_sse_event("hello", {"ok": True}).startswith(b"id:")
    assert not encode_sse_event("hello", {"ok": True}, event_id="").startswith(b"id:")


def test_a_newline_in_an_id_cannot_split_the_frame() -> None:
    """SSE has no escaping: a newline in a field ends it. One frame must stay
    one frame even when the cursor value is not what this code expected."""

    raw = encode_sse_event("e", {"ok": True}, event_id="a\nid: injected").decode("utf-8")
    lines = raw.split("\n")

    # One id line, and everything the caller passed is still on it: the injected
    # text is data, and dropping it would be its own surprise — it simply cannot
    # start a second field.
    assert lines[0] == "id: a id: injected"
    assert lines[1] == "event: e"
    # Still one frame.
    assert raw.count("\n\n") == 1
