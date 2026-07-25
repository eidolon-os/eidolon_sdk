"""Language-native client mirrors of the shared wire contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eidolon_sdk.biz import contracts as c


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source(relative: str) -> str:
    path = _workspace_root() / relative
    if not path.exists():
        pytest.skip(f"client checkout is not present: {relative}")
    return path.read_text(encoding="utf-8")


def test_mobile_contract_mirror_matches_sdk() -> None:
    source = _source("eidolon_client_mobile/lib/src/protocol/eidolon_protocol.dart")
    constants = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']*)';", source))

    assert constants["controlOpRoomJoin"] == c.CONTROL_OP_ROOM_JOIN
    assert constants["sessionIntentField"] == c.SESSION_INTENT_FIELD
    assert constants["sessionIntentUserInitiated"] == c.SESSION_INTENT_USER_INITIATED
    assert constants["sessionIntentProactive"] == c.SESSION_INTENT_PROACTIVE


def test_admin_contract_mirror_matches_sdk() -> None:
    source = _source("eidolon_admin/web/src/protocol/eidolonContract.ts")
    constants = dict(
        re.findall(
            r"export const\s+(\w+)\s*=\s*'([^']*)'\s+as const",
            source,
        )
    )

    assert constants["CONTROL_OP_ROOM_JOIN"] == c.CONTROL_OP_ROOM_JOIN
    assert constants["SESSION_INTENT_FIELD"] == c.SESSION_INTENT_FIELD
    assert constants["SESSION_INTENT_USER_INITIATED"] == c.SESSION_INTENT_USER_INITIATED
    assert constants["SESSION_INTENT_PROACTIVE"] == c.SESSION_INTENT_PROACTIVE
