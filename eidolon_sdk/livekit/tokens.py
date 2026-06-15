"""LiveKit access-token builder.

The SDK owns the wire/auth shape; each project still owns config loading and
policy decisions about which grants or metadata to request.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def build_livekit_token(
    *,
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
    name: str | None = None,
    participant_metadata: Mapping[str, Any] | None = None,
    dispatch_agent: bool = True,
    agent_name: str = "eidolon",
    agent_metadata: Mapping[str, Any] | None = None,
    can_publish: bool = True,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
) -> str:
    """Build a LiveKit JWT for an Eidolon participant.

    ``participant_metadata=None`` emits no metadata claim; an empty mapping
    emits ``{}``. That distinction is useful for compatibility tests.
    """

    if not api_key or not api_secret:
        raise ValueError("LIVEKIT_API_KEY or LIVEKIT_API_SECRET not configured")

    from livekit import api

    builder = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(name or identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=can_publish,
                can_subscribe=can_subscribe,
                can_publish_data=can_publish_data,
            )
        )
    )
    if dispatch_agent:
        dispatch = api.RoomAgentDispatch(agent_name=agent_name)
        if agent_metadata is not None:
            dispatch.metadata = json.dumps(dict(agent_metadata), ensure_ascii=False)
        builder = builder.with_room_config(
            api.RoomConfiguration(agents=[dispatch]),
        )
    if participant_metadata is not None:
        builder = builder.with_metadata(
            json.dumps(dict(participant_metadata), ensure_ascii=False)
        )
    return builder.to_jwt()
