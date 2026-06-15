"""Portable registry identifier validation."""

from __future__ import annotations

import re

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_registry_id(value: str, *, field_name: str) -> str:
    """Validate the shared Eidolon portable id charset."""
    if not ID_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be 1-64 chars of [A-Za-z0-9_-]; got {value!r}"
        )
    return value

