"""SQLite settings shared by SQL adapters."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SqliteSettings(BaseModel):
    path: Path | str
    enable_wal: bool = True
    busy_timeout_ms: int = Field(10_000, ge=0)
    synchronous: str = "NORMAL"

