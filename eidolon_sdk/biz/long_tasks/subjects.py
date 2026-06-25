"""Long-task key and subject contracts.

This module only constructs stable wire identifiers shared by agent, admin,
and worker processes. Task scheduling and execution remain in owning projects.
"""

from __future__ import annotations

import base64
import re
from datetime import date

LONG_TASK_PROGRESS_BASE = "long_task.progress"

_SAFE_USER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def safe_user_key(user_id: str) -> str:
    """Return a compact key-safe user id segment."""

    if _SAFE_USER_RE.fullmatch(user_id) and not user_id.startswith("b64_"):
        return user_id
    encoded = base64.urlsafe_b64encode(user_id.encode("utf-8")).decode("ascii")
    return f"b64_{encoded.rstrip('=')}"


def user_id_from_safe_key(segment: str) -> str:
    """Reverse :func:`safe_user_key`."""

    if not segment.startswith("b64_"):
        return segment
    encoded = segment.removeprefix("b64_")
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}").decode("utf-8")


def session_key_for(user_id: str, local_date: date | str) -> str:
    """Daily long-task session key: ``e.{safe_user}.{yyyymmdd}``."""

    if isinstance(local_date, date):
        yyyymmdd = local_date.strftime("%Y%m%d")
    else:
        yyyymmdd = local_date.replace("-", "")
    return f"e.{safe_user_key(user_id)}.{yyyymmdd}"


def parse_session_key(session_key: str) -> tuple[str, str]:
    """Return ``(user_id, yyyymmdd)`` from ``e.{safe_user}.{yyyymmdd}``."""

    prefix, segment, yyyymmdd = session_key.split(".", 2)
    if prefix != "e" or not segment or len(yyyymmdd) != 8:
        raise ValueError(f"invalid long-task session key: {session_key}")
    return user_id_from_safe_key(segment), yyyymmdd


def task_key_for(session_key: str, task_id: str) -> str:
    """Return a stable per-task key within a daily session."""

    return f"{session_key}.{task_id[:12]}"


def progress_subject_for(task_id: str) -> str:
    """Return the per-task progress subject."""

    return f"{LONG_TASK_PROGRESS_BASE}.{task_id}"
