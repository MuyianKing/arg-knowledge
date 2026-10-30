from __future__ import annotations

from app.core.cache import MemoryCache


async def test_memory_cache_clear_drops_entries() -> None:
    cache = MemoryCache()
    await cache.set("rag:answer:abc", {"answer": "cached"})
    assert await cache.get("rag:answer:abc") is not None

    await cache.clear()

    assert await cache.get("rag:answer:abc") is None
