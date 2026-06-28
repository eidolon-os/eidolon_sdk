from __future__ import annotations

from datetime import date

from eidolon_sdk.biz.long_tasks import (
    LONG_TASK_PROGRESS_BASE,
    owner_id_from_safe_key,
    parse_session_key,
    progress_subject_for,
    safe_owner_key,
    session_key_for,
    task_key_for,
)


def test_session_key_uses_safe_owner_and_date() -> None:
    assert session_key_for("manson", date(2026, 6, 14)) == "e.manson.20260614"
    assert session_key_for("owner-01", "2026-06-14") == "e.owner-01.20260614"


def test_session_key_round_trips_encoded_owner_id() -> None:
    segment = safe_owner_key("用户/01")

    assert segment.startswith("b64_")
    assert owner_id_from_safe_key(segment) == "用户/01"
    assert parse_session_key(f"e.{segment}.20260614") == ("用户/01", "20260614")


def test_b64_prefixed_owner_id_is_encoded_to_avoid_ambiguity() -> None:
    segment = safe_owner_key("b64_alice")

    assert segment.startswith("b64_")
    assert segment != "b64_alice"
    assert owner_id_from_safe_key(segment) == "b64_alice"


def test_task_key_and_progress_subject_contracts() -> None:
    session_key = session_key_for("manson", date(2026, 6, 14))

    assert task_key_for(session_key, "abcdef1234567890") == "e.manson.20260614.abcdef123456"
    assert progress_subject_for("task-1") == f"{LONG_TASK_PROGRESS_BASE}.task-1"
