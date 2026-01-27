"""ESI (EVE Swagger Interface) client for fetching character data."""

from datetime import UTC, datetime
from typing import Any

import httpx
from cachetools import TTLCache  # type: ignore[import-untyped]

from backend.cache import cache as redis_cache
from backend.models.applicant import (
    Applicant,
    CorpHistoryEntry,
)


class ESIClient:
    """
    Client for EVE Online's ESI API.

    Fetches character data including:
    - Character info (name, birthday, security status)
    - Corporation history
    - Current corporation/alliance

    Note: Some endpoints require authentication (wallet, assets, etc.)
    """

    BASE_URL = "https://esi.evetech.net/latest"
    USER_AGENT = "EVE-Sentinel/1.0 (https://github.com/AreteDriver/EVE-Sentinel)"

    def __init__(self) -> None:
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=1000, ttl=300)  # 5 min cache
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self.USER_AGENT},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(
        self,
        endpoint: str,
        cache_namespace: str = "esi",
    ) -> dict[str, Any] | list[Any]:
        """Make a GET request to ESI with caching."""
        cache_key = endpoint

        # Check Redis cache first
        if redis_cache.is_available:
            cached = await redis_cache.get(cache_namespace, cache_key)
            if cached is not None:
                if isinstance(cached, dict):
                    return dict(cached)
                return list(cached)

        # Check local cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if isinstance(cached, dict):
                return dict(cached)
            return list(cached)

        # Fetch from ESI
        client = await self._get_client()
        url = f"{self.BASE_URL}{endpoint}"

        response = await client.get(url)
        response.raise_for_status()

        data = response.json()

        # Store in both caches
        self._cache[cache_key] = data
        if redis_cache.is_available:
            await redis_cache.set(cache_namespace, cache_key, data)

        if isinstance(data, dict):
            return dict(data)
        return list(data)

    async def get_character(self, character_id: int) -> dict[str, Any]:
        """Get character public info."""
        data = await self._get(
            f"/characters/{character_id}/",
            cache_namespace="character",
        )
        return dict(data) if isinstance(data, dict) else {}

    async def get_corporation(self, corporation_id: int) -> dict[str, Any]:
        """Get corporation public info."""
        data = await self._get(
            f"/corporations/{corporation_id}/",
            cache_namespace="corporation",
        )
        return dict(data) if isinstance(data, dict) else {}

    async def get_alliance(self, alliance_id: int) -> dict[str, Any]:
        """Get alliance public info."""
        data = await self._get(
            f"/alliances/{alliance_id}/",
            cache_namespace="alliance",
        )
        return dict(data) if isinstance(data, dict) else {}

    async def get_character_corp_history(
        self,
        character_id: int,
    ) -> list[dict[str, Any]]:
        """Get character corporation history."""
        data = await self._get(
            f"/characters/{character_id}/corporationhistory/",
            cache_namespace="corp_history",
        )
        return list(data) if isinstance(data, list) else []

    async def search_character(self, name: str) -> int | None:
        """Search for a character by name and return their ID."""
        data = await self._get(
            f"/search/?categories=character&search={name}&strict=true",
            cache_namespace="search",
        )
        if isinstance(data, dict) and "character" in data:
            chars = data["character"]
            if chars:
                return int(chars[0])
        return None

    async def search_corporation(self, name: str) -> int | None:
        """Search for a corporation by name and return its ID."""
        data = await self._get(
            f"/search/?categories=corporation&search={name}&strict=true",
            cache_namespace="search",
        )
        if isinstance(data, dict) and "corporation" in data:
            corps = data["corporation"]
            if corps:
                return int(corps[0])
        return None

    async def build_applicant(self, character_id: int) -> Applicant:
        """
        Build an Applicant model from ESI data.

        This fetches all available public data for a character.
        For authenticated data (wallet, assets), use auth_bridge.
        """
        # Fetch character info
        char_data = await self.get_character(character_id)

        # Calculate character age
        birthday = datetime.fromisoformat(char_data["birthday"].replace("Z", "+00:00"))
        age_days = (datetime.now(UTC) - birthday).days

        # Fetch corp history
        history_data = await self.get_character_corp_history(character_id)

        # NPC corps (starter corps, etc.)
        npc_corps = {
            1000002,
            1000003,
            1000006,
            1000007,
            1000008,
            1000009,
            1000010,
            1000011,
            1000012,
            1000013,
            1000014,
            1000015,
            1000016,
            1000017,
            1000018,
            1000019,
            1000020,
            1000044,
            1000045,
            1000046,
            1000047,
            1000048,
            1000049,
            1000050,
            1000051,
            1000052,
            1000053,
            1000054,
            1000055,
            1000056,
            1000057,
            1000058,
            1000059,
            1000060,
            1000061,
            1000062,
            1000066,
            1000077,
            1000078,
            1000079,
            1000080,
            1000081,
            1000082,
            1000083,
            1000084,
            1000085,
            1000125,
            1000127,
        }

        # Build corp history with durations
        corp_history: list[CorpHistoryEntry] = []
        sorted_history = sorted(
            history_data,
            key=lambda x: x["start_date"],
            reverse=True,
        )

        for i, entry in enumerate(sorted_history):
            start = datetime.fromisoformat(entry["start_date"].replace("Z", "+00:00"))

            # End date is start of next entry, or now for current
            if i == 0:
                end = None
                duration = (datetime.now(UTC) - start).days
            else:
                end = datetime.fromisoformat(
                    sorted_history[i - 1]["start_date"].replace("Z", "+00:00")
                )
                duration = (end - start).days

            corp_id = entry["corporation_id"]

            # Fetch corp name
            try:
                corp_data = await self.get_corporation(corp_id)
                corp_name = corp_data.get("name", f"Corp {corp_id}")
            except Exception:
                corp_name = f"Corp {corp_id}"

            corp_history.append(
                CorpHistoryEntry(
                    corporation_id=corp_id,
                    corporation_name=corp_name,
                    start_date=start,
                    end_date=end,
                    duration_days=duration,
                    is_npc=corp_id in npc_corps,
                )
            )

        # Get current corp/alliance
        corp_id = char_data.get("corporation_id")
        corp_name = None
        alliance_id = None
        alliance_name = None

        if corp_id:
            try:
                corp_data = await self.get_corporation(corp_id)
                corp_name = corp_data.get("name")
                alliance_id = corp_data.get("alliance_id")
                if alliance_id:
                    alliance_data = await self.get_alliance(alliance_id)
                    alliance_name = alliance_data.get("name")
            except Exception:
                pass

        return Applicant(
            character_id=character_id,
            character_name=char_data.get("name", f"Character {character_id}"),
            corporation_id=corp_id,
            corporation_name=corp_name,
            alliance_id=alliance_id,
            alliance_name=alliance_name,
            birthday=birthday,
            security_status=char_data.get("security_status"),
            character_age_days=age_days,
            corp_history=corp_history,
            data_sources=["esi"],
        )
