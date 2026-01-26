"""zKillboard API client for fetching PvP data."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from cachetools import TTLCache  # type: ignore[import-untyped]

from backend.cache import cache as redis_cache
from backend.models.applicant import Applicant, KillboardStats


class ZKillClient:
    """
    Client for zKillboard API.

    Fetches kill/loss data for characters including:
    - Recent kills and losses
    - Statistics (total kills, ISK destroyed, etc.)
    - AWOX detection (kills on corp/alliance mates)
    """

    BASE_URL = "https://zkillboard.com/api"
    USER_AGENT = "EVE-Sentinel/1.0 (https://github.com/AreteDriver/EVE-Sentinel)"

    # Rate limiting - zKill allows ~10 req/sec but be nice
    RATE_LIMIT_DELAY = 0.2  # seconds between requests

    def __init__(self) -> None:
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=500, ttl=600)  # 10 min cache
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
        cache_namespace: str = "killboard",
    ) -> list[dict[str, Any]]:
        """Make a GET request to zKillboard with caching."""
        cache_key = endpoint

        # Check Redis cache first
        if redis_cache.is_available:
            cached = await redis_cache.get(cache_namespace, cache_key)
            if cached is not None:
                return list(cached)

        # Check local cache
        if cache_key in self._cache:
            return list(self._cache[cache_key])

        # Fetch from zKillboard
        client = await self._get_client()
        url = f"{self.BASE_URL}{endpoint}"

        response = await client.get(url)
        response.raise_for_status()

        data = response.json()
        result = list(data) if isinstance(data, list) else []

        # Store in both caches
        self._cache[cache_key] = result
        if redis_cache.is_available:
            await redis_cache.set(cache_namespace, cache_key, result)

        return result

    async def get_character_kills(
        self,
        character_id: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Get character's recent kills."""
        return await self._get(f"/kills/characterID/{character_id}/limit/{limit}/")

    async def get_character_losses(
        self,
        character_id: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Get character's recent losses."""
        return await self._get(f"/losses/characterID/{character_id}/limit/{limit}/")

    async def get_character_stats(
        self,
        character_id: int,
    ) -> dict[str, Any]:
        """Get character statistics from zKill."""
        data = await self._get(f"/stats/characterID/{character_id}/")
        return dict(data[0]) if data else {}

    async def build_killboard_stats(
        self,
        character_id: int,
        current_corp_id: int | None = None,
        current_alliance_id: int | None = None,
    ) -> KillboardStats:
        """
        Build KillboardStats from zKillboard data.

        Analyzes kills for:
        - Activity levels (30d, 90d)
        - AWOX detection (kills on corp/alliance mates)
        - Ship preferences
        - Region activity
        """
        kills = await self.get_character_kills(character_id, limit=500)
        losses = await self.get_character_losses(character_id, limit=200)

        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)
        ninety_days_ago = now - timedelta(days=90)

        # Process kills
        kills_30d = 0
        kills_90d = 0
        solo_kills = 0
        awox_kills = 0
        isk_destroyed = 0.0
        ships_used: dict[str, int] = {}
        regions: dict[str, int] = {}
        fleet_sizes: list[int] = []

        for kill in kills:
            kill_time = datetime.fromisoformat(
                kill.get("killmail_time", "2000-01-01T00:00:00Z").replace("Z", "+00:00")
            )

            if kill_time >= thirty_days_ago:
                kills_30d += 1
            if kill_time >= ninety_days_ago:
                kills_90d += 1

            # Check for AWOX (killed someone in same corp/alliance)
            victim = kill.get("victim", {})
            victim_corp = victim.get("corporation_id")
            victim_alliance = victim.get("alliance_id")

            if current_corp_id and victim_corp == current_corp_id:
                awox_kills += 1
            elif current_alliance_id and victim_alliance == current_alliance_id:
                awox_kills += 1

            # Track ships used
            attackers = kill.get("attackers", [])
            fleet_sizes.append(len(attackers))

            for attacker in attackers:
                if attacker.get("character_id") == character_id:
                    ship = attacker.get("ship_type_id")
                    if ship:
                        ships_used[str(ship)] = ships_used.get(str(ship), 0) + 1

                    if len(attackers) == 1:
                        solo_kills += 1
                    break

            # Track ISK destroyed
            zkb = kill.get("zkb", {})
            isk_destroyed += zkb.get("totalValue", 0)

            # Track region (would need ESI lookup for actual region name)
            solar_system = kill.get("solar_system_id")
            if solar_system:
                regions[str(solar_system)] = regions.get(str(solar_system), 0) + 1

        # Process losses
        deaths_total = len(losses)
        deaths_30d = sum(
            1
            for loss in losses
            if datetime.fromisoformat(
                loss.get("killmail_time", "2000-01-01T00:00:00Z").replace("Z", "+00:00")
            )
            >= thirty_days_ago
        )

        isk_lost = sum(loss.get("zkb", {}).get("totalValue", 0) for loss in losses)

        # Top ships (by usage count)
        top_ships = sorted(ships_used.keys(), key=lambda x: ships_used[x], reverse=True)[:10]

        # Top regions
        top_regions = sorted(regions.keys(), key=lambda x: regions[x], reverse=True)[:5]

        # Average fleet size
        avg_fleet = sum(fleet_sizes) / len(fleet_sizes) if fleet_sizes else None

        return KillboardStats(
            kills_total=len(kills),
            kills_30d=kills_30d,
            kills_90d=kills_90d,
            deaths_total=deaths_total,
            deaths_30d=deaths_30d,
            solo_kills=solo_kills,
            awox_kills=awox_kills,
            isk_destroyed=isk_destroyed,
            isk_lost=isk_lost,
            top_ships=top_ships,  # These are type IDs, would need resolution
            top_regions=top_regions,  # These are system IDs
            avg_fleet_size=avg_fleet,
        )

    async def enrich_applicant(
        self,
        applicant: Applicant,
    ) -> Applicant:
        """Add killboard data to an applicant."""
        stats = await self.build_killboard_stats(
            applicant.character_id,
            applicant.corporation_id,
            applicant.alliance_id,
        )

        applicant.killboard = stats
        if "zkill" not in applicant.data_sources:
            applicant.data_sources.append("zkill")

        return applicant
