from __future__ import annotations

import json

import jwt
import pytest

from eidolon_sdk.livekit import build_livekit_token

SECRET = "test-secret-with-enough-entropy-32b"


def test_build_livekit_token_pins_identity_grants_metadata_and_dispatch() -> None:
    token = build_livekit_token(
        api_key="devkey",
        api_secret=SECRET,
        room_name="room-a",
        identity="alice",
        participant_metadata={"kind": "user", "display_name": "Alice"},
        agent_metadata={"agent_mode": "streaming"},
    )

    payload = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert payload["iss"] == "devkey"
    assert payload["sub"] == "alice"
    assert json.loads(payload["metadata"]) == {
        "kind": "user",
        "display_name": "Alice",
    }
    video = payload["video"]
    assert video["roomJoin"] is True
    assert video["room"] == "room-a"
    assert video["canPublish"] is True
    assert video["canSubscribe"] is True
    assert video["canPublishData"] is True
    assert payload["roomConfig"]["agents"] == [
        {
            "agentName": "eidolon",
            "metadata": json.dumps({"agent_mode": "streaming"}, ensure_ascii=False),
        }
    ]


def test_build_livekit_token_supports_subscribe_only_without_agent() -> None:
    token = build_livekit_token(
        api_key="devkey",
        api_secret=SECRET,
        room_name="room-a",
        identity="observer",
        dispatch_agent=False,
        can_publish=False,
        can_subscribe=True,
        can_publish_data=False,
    )

    payload = jwt.decode(token, SECRET, algorithms=["HS256"])

    video = payload["video"]
    assert "roomConfig" not in payload
    assert video["canPublish"] is False
    assert video["canSubscribe"] is True
    assert video["canPublishData"] is False
    assert "metadata" not in payload


def test_build_livekit_token_rejects_missing_secret() -> None:
    with pytest.raises(ValueError, match="LIVEKIT_API_KEY"):
        build_livekit_token(
            api_key="",
            api_secret="",
            room_name="room-a",
            identity="alice",
        )
