"""Generic async key-value store protocol.

NATS KV adapters can implement this later without changing domain stores.
"""

from __future__ import annotations

from typing import Protocol


class KVStore(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def put(self, key: str, value: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def keys(self, prefix: str = "") -> list[str]: ...

