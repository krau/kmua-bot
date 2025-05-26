import asyncio
from typing import Any

from aiocache import SimpleMemoryCache


class _MemStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = value

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._data.get(key, default)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            try:
                del self._data[key]
                return True
            except KeyError:
                return False


memstore = _MemStore()


class _MemTTLCache:
    def __init__(self) -> None:
        self.cache = SimpleMemoryCache()

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        await self.cache.set(key, value, ttl=ttl)

    async def get(self, key: str, default: Any = None) -> Any:
        return await self.cache.get(key, default)

    async def delete(self, key: str) -> bool:
        return await self.cache.delete(key)


memttlcache = _MemTTLCache()

__all__ = ["memstore", "memttlcache"]
