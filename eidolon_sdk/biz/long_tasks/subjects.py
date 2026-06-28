"""Long-task key and subject contracts.

This module only constructs stable wire identifiers shared by agent, admin,
and worker processes. Task scheduling and execution remain in owning projects.
"""

from __future__ import annotations

import base64
import re
from datetime import date

LONG_TASK_PROGRESS_BASE = "long_task.progress"

_SAFE_OWNER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def safe_owner_key(owner_id: str) -> str:
    """Return a compact key-safe owner id segment."""

    if _SAFE_OWNER_RE.fullmatch(owner_id) and not owner_id.startswith("b64_"):
        return owner_id
    encoded = base64.urlsafe_b64encode(owner_id.encode("utf-8")).decode("ascii")
    return f"b64_{encoded.rstrip('=')}"


def owner_id_from_safe_key(segment: str) -> str:
    """Reverse :func:`safe_owner_key`."""

    if not segment.startswith("b64_"):
        return segment
    encoded = segment.removeprefix("b64_")
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}").decode("utf-8")


def session_key_for(owner_id: str, local_date: date | str) -> str:
    """Daily long-task session key: ``e.{safe_owner}.{yyyymmdd}``."""

    if isinstance(local_date, date):
        yyyymmdd = local_date.strftime("%Y%m%d")
    else:
        yyyymmdd = local_date.replace("-", "")
    return f"e.{safe_owner_key(owner_id)}.{yyyymmdd}"


def parse_session_key(session_key: str) -> tuple[str, str]:
    """Return ``(owner_id, yyyymmdd)`` from ``e.{safe_owner}.{yyyymmdd}``."""

    prefix, segment, yyyymmdd = session_key.split(".", 2)
    if prefix != "e" or not segment or len(yyyymmdd) != 8:
        raise ValueError(f"invalid long-task session key: {session_key}")
    return owner_id_from_safe_key(segment), yyyymmdd


def task_key_for(session_key: str, task_id: str) -> str:
    """Return a stable per-task key within a daily session."""

    return f"{session_key}.{task_id[:12]}"


def progress_subject_for(task_id: str) -> str:
    """Return the per-task progress subject."""

    return f"{LONG_TASK_PROGRESS_BASE}.{task_id}"
