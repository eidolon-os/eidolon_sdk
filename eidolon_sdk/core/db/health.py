"""SQLite health checks."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def quick_check(engine: AsyncEngine) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA quick_check"))
        return str(result.scalar_one())


async def integrity_check(engine: AsyncEngine) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA integrity_check"))
        return str(result.scalar_one())

