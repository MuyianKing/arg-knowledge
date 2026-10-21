from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

from redis.asyncio import Redis

from app.config import settings


class CacheProtocol(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def set(self, key: str, value: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


def make_cache_key(
    *,
    tenant_id: str,
    acl: tuple[str, ...],
    query: str,
    filters: dict[str, Any] | None,
    top_k: int,
    prompt_version: str,
    model_revision: str,
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "acl": sorted(acl),
        "query": " ".join(query.split()),
        "filters": filters or {},
        "top_k": top_k,
        "prompt_version": prompt_version,
        "model_revision": model_revision,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"rag:answer:{digest}"


class Cache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self._redis.set(
            key,
            json.dumps(value, ensure_ascii=False),
            ex=settings.cache_ttl_seconds,
        )

    async def close(self) -> None:
        await self._redis.aclose()


class MemoryCache:
    """In-process cache for local development; production uses Redis."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = (time.time() + settings.cache_ttl_seconds, value)

    async def close(self) -> None:
        self._store.clear()
