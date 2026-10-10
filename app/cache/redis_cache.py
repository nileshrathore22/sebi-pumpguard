"""Redis JSON cache with TTL. Degrades to a no-op cache if Redis is unreachable."""

import json
from typing import Any, Protocol

import redis

from app.core.logging import get_logger

log = get_logger(__name__)


class Cache(Protocol):
    def get_json(self, key: str) -> Any | None: ...

    def set_json(self, key: str, value: Any, ttl: int) -> None: ...

    def incr_window(self, key: str, ttl: int) -> int: ...

    def ping(self) -> bool: ...


class RedisCache:
    def __init__(self, client: "redis.Redis") -> None:
        self.client = client

    @classmethod
    def from_url(cls, url: str) -> "RedisCache":
        return cls(redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1))

    def get_json(self, key: str) -> Any | None:
        try:
            raw = self.client.get(key)
        except redis.RedisError as exc:
            log.warning("cache get failed", extra={"error": str(exc)})
            return None
        return json.loads(raw) if raw else None

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        try:
            self.client.setex(key, ttl, json.dumps(value, default=str))
        except redis.RedisError as exc:
            log.warning("cache set failed", extra={"error": str(exc)})

    def incr_window(self, key: str, ttl: int) -> int:
        try:
            pipe = self.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)
            count, _ = pipe.execute()
            return int(count)
        except redis.RedisError:
            return 0  # fail open: never block users because the cache is down

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except redis.RedisError:
            return False


class MemoryCache:
    """In-process fallback (and handy in tests). Ignores TTL for simplicity."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get_json(self, key: str) -> Any | None:
        return self.store.get(key)

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        self.store[key] = json.loads(json.dumps(value, default=str))

    def incr_window(self, key: str, ttl: int) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return int(self.store[key])

    def ping(self) -> bool:
        return True
