"""Authenticated ESI client for fetching protected character data."""

from datetime import datetime
from typing import Any

import httpx

from backend.cache import cache as redis_cache
from backend.logging_config import get_logger
from backend.models.applicant import (
    Applicant,
    AssetSummary,
    WalletEntry,
)

logger = get_logger(__name__)


class AuthenticatedESIClient:
    """
    Authenticated ESI client for fetching protected character data.

    Uses OAuth2 access tokens from EVE SSO to access:
    - Wallet journal
    - Assets
    - Contacts and standings
    - Skills (future)

    Requires the character to have logged in via SSO and granted
    the appropriate scopes.
    """

    BASE_URL = "https://esi.evetech.net/latest"
    USER_AGENT = "EVE-Sentinel/1.0 (https://github.com/AreteDriver/EVE-Sentinel)"

    # Required scopes for different endpoints
    SCOPES = {
        "wallet": "esi-wallet.read_character_wallet.v1",
        "assets": "esi-assets.read_assets.v1",
        "contacts": "esi-characters.read_contacts.v1",
        "standings": "esi-characters.read_standings.v1",
    }

    # Capital and supercapital type IDs for asset analysis
    CAPITAL_TYPE_IDS = {
        # Carriers
        23757,  # Archon
        23915,  # Chimera
        24483,  # Nidhoggur
        23911,  # Thanatos
        # Force Auxiliaries
        37604,  # Apostle
        37605,  # Minokawa
        37606,  # Lif
        37607,  # Ninazu
        # Dreadnoughts
        19720,  # Revelation
        19722,  # Phoenix
        19726,  # Naglfar
        19724,  # Moros
        # Rorqual
        28352,  # Rorqual
    }

    SUPERCAPITAL_TYPE_IDS = {
        # Supercarriers
        23919,  # Aeon
        23917,  # Wyvern
        22852,  # Hel
        23913,  # Nyx
        42241,  # Vendetta
        3514,   # Revenant
        # Titans
        11567,  # Avatar
        3764,   # Leviathan
        23773,  # Ragnarok
        671,    # Erebus
        42126,  # Vanquisher
        45649,  # Komodo
        42243,  # Molok
    }

    def __init__(self, access_token: str, character_id: int) -> None:
        """
        Initialize authenticated ESI client.

        Args:
            access_token: OAuth2 access token from EVE SSO
            character_id: Character ID the token belongs to
        """
        self.access_token = access_token
        self.character_id = character_id
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with auth headers."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Authorization": f"Bearer {self.access_token}",
                },
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
        cache_namespace: str = "esi_auth",
        cache_ttl: int = 300,
    ) -> dict[str, Any] | list[Any] | float:
        """
        Make an authenticated GET request to ESI.

        Authenticated data is cached with shorter TTLs since it's
        more sensitive and changes more frequently.
        """
        # Cache key includes character ID for isolation
        cache_key = f"{self.character_id}:{endpoint}"

        # Check Redis cache
        if redis_cache.is_available:
            cached = await redis_cache.get(cache_namespace, cache_key)
            if cached is not None:
                if isinstance(cached, (int, float)):
                    return float(cached)
                if isinstance(cached, dict):
                    return dict(cached)
                return list(cached)

        # Fetch from ESI
        client = await self._get_client()
        url = f"{self.BASE_URL}{endpoint}"

        response = await client.get(url)
        response.raise_for_status()

        data = response.json()

        # Cache the result
        if redis_cache.is_available:
            await redis_cache.set(cache_namespace, cache_key, data, ttl=cache_ttl)

        if isinstance(data, (int, float)):
            return float(data)
        if isinstance(data, dict):
            return dict(data)
        return list(data)

    async def get_wallet_journal(
        self,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Get character wallet journal.

        Requires scope: esi-wallet.read_character_wallet.v1

        Returns recent wallet transactions including:
        - Player donations
        - Market transactions
        - Contract payments
        - Bounties
        """
        data = await self._get(
            f"/characters/{self.character_id}/wallet/journal/?page={page}",
            cache_namespace="wallet",
            cache_ttl=120,  # 2 minutes - wallet changes frequently
        )
        return list(data) if isinstance(data, list) else []

    async def get_wallet_balance(self) -> float:
        """
        Get character wallet balance.

        Requires scope: esi-wallet.read_character_wallet.v1
        """
        data = await self._get(
            f"/characters/{self.character_id}/wallet/",
            cache_namespace="wallet",
            cache_ttl=60,  # 1 minute
        )
        return float(data) if isinstance(data, (int, float)) else 0.0

    async def get_assets(self) -> list[dict[str, Any]]:
        """
        Get character assets.

        Requires scope: esi-assets.read_assets.v1

        Returns all items owned by the character.
        Note: This can be a large response for wealthy characters.
        """
        all_assets: list[dict[str, Any]] = []
        page = 1

        while True:
            data = await self._get(
                f"/characters/{self.character_id}/assets/?page={page}",
                cache_namespace="assets",
                cache_ttl=600,  # 10 minutes
            )

            if not data:
                break

            if isinstance(data, list):
                all_assets.extend(data)
                if len(data) < 1000:  # ESI returns max 1000 per page
                    break
                page += 1
            else:
                break

        return all_assets

    async def get_contacts(self) -> list[dict[str, Any]]:
        """
        Get character contacts.

        Requires scope: esi-characters.read_contacts.v1

        Returns the character's contact list with standings.
        """
        data = await self._get(
            f"/characters/{self.character_id}/contacts/",
            cache_namespace="contacts",
            cache_ttl=300,  # 5 minutes
        )
        return list(data) if isinstance(data, list) else []

    async def get_standings(self) -> list[dict[str, Any]]:
        """
        Get character standings.

        Requires scope: esi-characters.read_standings.v1

        Returns NPC faction/corp standings.
        """
        data = await self._get(
            f"/characters/{self.character_id}/standings/",
            cache_namespace="standings",
            cache_ttl=600,  # 10 minutes - standings change slowly
        )
        return list(data) if isinstance(data, list) else []

    async def build_wallet_entries(self, limit: int = 100) -> list[WalletEntry]:
        """
        Build WalletEntry models from wallet journal.

        Fetches and parses wallet journal into structured entries.
        """
        journal = await self.get_wallet_journal()
        entries: list[WalletEntry] = []

        for entry in journal[:limit]:
            try:
                entries.append(
                    WalletEntry(
                        id=entry.get("id", 0),
                        date=datetime.fromisoformat(
                            entry.get("date", "2000-01-01T00:00:00Z").replace("Z", "+00:00")
                        ),
                        ref_type=entry.get("ref_type", "unknown"),
                        amount=entry.get("amount", 0.0),
                        balance=entry.get("balance"),
                        first_party_id=entry.get("first_party_id"),
                        second_party_id=entry.get("second_party_id"),
                        reason=entry.get("reason"),
                    )
                )
            except Exception as e:
                logger.debug(f"Failed to parse wallet entry: {e}")
                continue

        return entries

    async def build_asset_summary(self) -> AssetSummary:
        """
        Build AssetSummary from character assets.

        Analyzes assets to identify:
        - Capital ships
        - Supercapitals
        - Total approximate value
        - Primary regions
        """
        assets = await self.get_assets()

        capital_ships: list[str] = []
        supercapitals: list[str] = []
        locations: dict[int, int] = {}  # location_id -> count
        total_items = 0

        for asset in assets:
            type_id = asset.get("type_id")
            location_id = asset.get("location_id", 0)
            quantity = asset.get("quantity", 1)

            total_items += quantity

            # Track locations
            if location_id:
                locations[location_id] = locations.get(location_id, 0) + quantity

            # Check for capitals
            if type_id in self.CAPITAL_TYPE_IDS:
                # Would need type name resolution - for now use type ID
                capital_ships.append(f"TypeID:{type_id}")

            # Check for supercapitals
            if type_id in self.SUPERCAPITAL_TYPE_IDS:
                supercapitals.append(f"TypeID:{type_id}")

        # Get top locations
        top_locations = sorted(
            locations.keys(),
            key=lambda x: locations[x],
            reverse=True,
        )[:5]

        return AssetSummary(
            total_value_isk=None,  # Would need price data to calculate
            capital_ships=capital_ships,
            supercapitals=supercapitals,
            primary_regions=[str(loc) for loc in top_locations],  # Location IDs
            has_structures=False,  # Would need to check for structure type IDs
        )

    async def build_standings_data(self) -> dict[str, Any]:
        """
        Build standings data structure for analysis.

        Combines contacts and NPC standings into a unified format.
        """
        contacts = await self.get_contacts()
        standings = await self.get_standings()

        return {
            "contacts": contacts,
            "standings": standings,
        }

    async def enrich_applicant(self, applicant: Applicant) -> Applicant:
        """
        Enrich an applicant with authenticated ESI data.

        Adds wallet, assets, and standings data if the scopes allow.
        """
        try:
            # Add wallet data
            wallet_entries = await self.build_wallet_entries(limit=200)
            applicant.wallet_journal = wallet_entries
            logger.info(f"Added {len(wallet_entries)} wallet entries for {applicant.character_name}")
        except Exception as e:
            logger.debug(f"Failed to fetch wallet data: {e}")

        try:
            # Add asset summary
            assets = await self.build_asset_summary()
            applicant.assets = assets
            logger.info(f"Added asset summary for {applicant.character_name}")
        except Exception as e:
            logger.debug(f"Failed to fetch asset data: {e}")

        try:
            # Add standings data
            standings = await self.build_standings_data()
            applicant.standings_data = standings
            logger.info(f"Added standings data for {applicant.character_name}")
        except Exception as e:
            logger.debug(f"Failed to fetch standings data: {e}")

        # Update data sources
        if "esi_auth" not in applicant.data_sources:
            applicant.data_sources.append("esi_auth")

        return applicant
