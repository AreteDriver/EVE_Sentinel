"""Tests for Redis caching layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.cache import CACHE_TTLS, RedisCache


class TestCacheTTLs:
    """Tests for cache TTL configuration."""

    def test_ttls_has_required_namespaces(self):
        """Test that CACHE_TTLS has all required namespaces."""
        required = [
            "character",
            "corporation",
            "alliance",
            "corp_history",
            "killboard",
            "zkill_stats",
            "search",
            "default",
        ]
        for ns in required:
            assert ns in CACHE_TTLS, f"Missing TTL for namespace: {ns}"

    def test_ttls_are_positive_integers(self):
        """Test that all TTLs are positive integers."""
        for ns, ttl in CACHE_TTLS.items():
            assert isinstance(ttl, int), f"TTL for {ns} is not an int"
            assert ttl > 0, f"TTL for {ns} is not positive"

    def test_search_ttl_is_short(self):
        """Test that search results have a short TTL."""
        assert CACHE_TTLS["search"] <= 120  # 2 minutes max

    def test_corp_and_alliance_ttl_is_long(self):
        """Test that corp/alliance info has a long TTL."""
        assert CACHE_TTLS["corporation"] >= 1800  # 30 minutes min
        assert CACHE_TTLS["alliance"] >= 1800


class TestRedisCache:
    """Tests for RedisCache class."""

    @pytest.fixture
    def cache(self):
        """Create a cache instance for testing."""
        with patch("backend.cache.settings") as mock_settings:
            mock_settings.redis_enabled = True
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.redis_prefix = "test:"
            cache = RedisCache()
            cache._enabled = True
            cache._prefix = "test:"
            return cache

    def test_make_key_includes_prefix(self, cache):
        """Test that cache keys include the prefix."""
        key = cache._make_key("character", "12345")
        assert key == "test:character:12345"

    def test_make_key_with_namespace(self, cache):
        """Test that cache keys include namespace."""
        key = cache._make_key("killboard", "/kills/123")
        assert key == "test:killboard:/kills/123"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_no_client(self, cache):
        """Test that get returns None when not connected."""
        cache._client = None
        result = await cache.get("test", "key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_returns_false_when_no_client(self, cache):
        """Test that set returns False when not connected."""
        cache._client = None
        result = await cache.set("test", "key", {"data": "value"})
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_no_client(self, cache):
        """Test that delete returns False when not connected."""
        cache._client = None
        result = await cache.delete("test", "key")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_stats_when_not_connected(self, cache):
        """Test get_stats when not connected."""
        cache._client = None
        stats = await cache.get_stats()
        assert stats["connected"] is False

    def test_is_available_false_when_no_client(self, cache):
        """Test is_available returns False when no client."""
        cache._client = None
        assert cache.is_available is False

    def test_is_available_true_when_client_exists(self, cache):
        """Test is_available returns True when client exists."""
        cache._client = MagicMock()
        assert cache.is_available is True


class TestRedisCacheWithMockClient:
    """Tests for RedisCache with mocked Redis client."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = MagicMock()
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=1)
        mock.ping = AsyncMock(return_value=True)
        mock.close = AsyncMock()
        mock.info = AsyncMock(return_value={"used_memory_human": "1M"})
        mock.dbsize = AsyncMock(return_value=100)
        return mock

    @pytest.fixture
    def cache_with_client(self, mock_redis):
        """Create a cache with mock client."""
        with patch("backend.cache.settings") as mock_settings:
            mock_settings.redis_enabled = True
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.redis_prefix = "test:"
            cache = RedisCache()
            cache._client = mock_redis
            cache._enabled = True
            cache._prefix = "test:"
            return cache

    @pytest.mark.asyncio
    async def test_get_returns_cached_value(self, cache_with_client, mock_redis):
        """Test that get returns cached value."""
        import json
        mock_redis.get = AsyncMock(return_value=json.dumps({"name": "Test"}))

        result = await cache_with_client.get("character", "123")
        assert result == {"name": "Test"}

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(self, cache_with_client, mock_redis):
        """Test that get returns None for missing keys."""
        mock_redis.get = AsyncMock(return_value=None)

        result = await cache_with_client.get("character", "999")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_stores_value(self, cache_with_client, mock_redis):
        """Test that set stores values."""
        result = await cache_with_client.set("character", "123", {"name": "Test"})
        assert result is True
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_uses_namespace_ttl(self, cache_with_client, mock_redis):
        """Test that set uses namespace-specific TTL."""
        await cache_with_client.set("character", "123", {"name": "Test"})

        # Get the TTL used in the call
        call_args = mock_redis.setex.call_args
        ttl_used = call_args[0][1]
        assert ttl_used == CACHE_TTLS["character"]

    @pytest.mark.asyncio
    async def test_set_uses_custom_ttl(self, cache_with_client, mock_redis):
        """Test that set can use custom TTL."""
        await cache_with_client.set("character", "123", {"name": "Test"}, ttl=60)

        call_args = mock_redis.setex.call_args
        ttl_used = call_args[0][1]
        assert ttl_used == 60

    @pytest.mark.asyncio
    async def test_delete_removes_key(self, cache_with_client, mock_redis):
        """Test that delete removes keys."""
        result = await cache_with_client.delete("character", "123")
        assert result is True
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_stats_returns_info(self, cache_with_client, mock_redis):
        """Test that get_stats returns cache info."""
        stats = await cache_with_client.get_stats()

        assert stats["enabled"] is True
        assert stats["connected"] is True
        assert "used_memory" in stats
        assert stats["total_keys"] == 100


class TestCacheDisabled:
    """Tests for when caching is disabled."""

    @pytest.fixture
    def disabled_cache(self):
        """Create a disabled cache."""
        with patch("backend.cache.settings") as mock_settings:
            mock_settings.redis_enabled = False
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.redis_prefix = "test:"
            cache = RedisCache()
            cache._enabled = False
            cache._client = None
            return cache

    @pytest.mark.asyncio
    async def test_connect_does_nothing_when_disabled(self, disabled_cache):
        """Test that connect does nothing when disabled."""
        await disabled_cache.connect()
        assert disabled_cache._client is None

    @pytest.mark.asyncio
    async def test_operations_noop_when_disabled(self, disabled_cache):
        """Test that operations are no-ops when disabled."""
        assert await disabled_cache.get("ns", "key") is None
        assert await disabled_cache.set("ns", "key", "value") is False
        assert await disabled_cache.delete("ns", "key") is False
        assert await disabled_cache.clear_namespace("ns") == 0
        assert await disabled_cache.clear_all() == 0
