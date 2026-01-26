"""Redis caching layer for EVE Sentinel."""

import json
from typing import Any, TypeVar

import redis.asyncio as redis
from pydantic import BaseModel

from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CacheConfig(BaseModel):
    """Cache configuration."""

    enabled: bool = True
    url: str = "redis://localhost:6379"
    prefix: str = "sentinel:"
    default_ttl: int = 300  # 5 minutes


# TTL values for different data types (in seconds)
CACHE_TTLS = {
    "character": 300,  # 5 minutes - character info changes rarely
    "corporation": 3600,  # 1 hour - corp info is stable
    "alliance": 3600,  # 1 hour - alliance info is stable
    "corp_history": 600,  # 10 minutes - history can change
    "killboard": 300,  # 5 minutes - kills update frequently
    "zkill_stats": 600,  # 10 minutes - stats aggregate data
    "search": 60,  # 1 minute - search results
    "default": 300,  # 5 minutes default
}


class RedisCache:
    """
    Redis-based caching for API responses.

    Provides async get/set operations with automatic JSON serialization
    and configurable TTLs per data type.
    """

    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self._enabled = settings.redis_enabled
        self._url = settings.redis_url
        self._prefix = settings.redis_prefix

    async def connect(self) -> None:
        """Connect to Redis."""
        if not self._enabled:
            logger.info("Redis caching disabled")
            return

        try:
            self._client = redis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._client.ping()
            logger.info(f"Connected to Redis at {self._url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Caching disabled.")
            self._client = None
            self._enabled = False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    def _make_key(self, namespace: str, key: str) -> str:
        """Create a prefixed cache key."""
        return f"{self._prefix}{namespace}:{key}"

    async def get(self, namespace: str, key: str) -> Any | None:
        """
        Get a value from cache.

        Args:
            namespace: Cache namespace (e.g., "character", "killboard")
            key: Cache key within namespace

        Returns:
            Cached value or None if not found
        """
        if not self._client:
            return None

        try:
            cache_key = self._make_key(namespace, key)
            value = await self._client.get(cache_key)

            if value:
                return json.loads(value)
            return None

        except Exception as e:
            logger.debug(f"Cache get error: {e}")
            return None

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> bool:
        """
        Set a value in cache.

        Args:
            namespace: Cache namespace
            key: Cache key within namespace
            value: Value to cache (will be JSON serialized)
            ttl: Time-to-live in seconds (uses namespace default if not specified)

        Returns:
            True if successfully cached, False otherwise
        """
        if not self._client:
            return False

        try:
            cache_key = self._make_key(namespace, key)

            # Use namespace-specific TTL or default
            if ttl is None:
                ttl = CACHE_TTLS.get(namespace, CACHE_TTLS["default"])

            serialized = json.dumps(value)
            await self._client.setex(cache_key, ttl, serialized)
            return True

        except Exception as e:
            logger.debug(f"Cache set error: {e}")
            return False

    async def delete(self, namespace: str, key: str) -> bool:
        """Delete a value from cache."""
        if not self._client:
            return False

        try:
            cache_key = self._make_key(namespace, key)
            await self._client.delete(cache_key)
            return True
        except Exception as e:
            logger.debug(f"Cache delete error: {e}")
            return False

    async def clear_namespace(self, namespace: str) -> int:
        """
        Clear all keys in a namespace.

        Returns number of keys deleted.
        """
        if not self._client:
            return 0

        try:
            pattern = self._make_key(namespace, "*")
            keys = []
            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                return await self._client.delete(*keys)
            return 0

        except Exception as e:
            logger.debug(f"Cache clear error: {e}")
            return 0

    async def clear_all(self) -> int:
        """
        Clear all cached data.

        Returns number of keys deleted.
        """
        if not self._client:
            return 0

        try:
            pattern = f"{self._prefix}*"
            keys = []
            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                return await self._client.delete(*keys)
            return 0

        except Exception as e:
            logger.debug(f"Cache clear all error: {e}")
            return 0

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        if not self._client:
            return {"enabled": False, "connected": False}

        try:
            info = await self._client.info("memory")
            db_size = await self._client.dbsize()

            return {
                "enabled": True,
                "connected": True,
                "used_memory": info.get("used_memory_human", "unknown"),
                "total_keys": db_size,
                "prefix": self._prefix,
            }
        except Exception as e:
            return {
                "enabled": self._enabled,
                "connected": False,
                "error": str(e),
            }

    @property
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self._client is not None


# Global cache instance
cache = RedisCache()


async def get_cache() -> RedisCache:
    """Get the global cache instance."""
    return cache
