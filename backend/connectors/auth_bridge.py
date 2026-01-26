"""Abstract base class for alliance auth system integrations.

Supports Alliance Auth and SeAT for accessing authenticated ESI data
such as wallet journals, assets, and login history.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx
from cachetools import TTLCache  # type: ignore[import-untyped]

from backend.models.applicant import ActivityPattern, Applicant, AssetSummary, WalletEntry


class AuthBridgeError(Exception):
    """Base exception for auth bridge errors."""

    pass


class AuthBridgeConnectionError(AuthBridgeError):
    """Failed to connect to auth system."""

    pass


class AuthBridgeNotFoundError(AuthBridgeError):
    """Character not found in auth system."""

    pass


class AuthBridge(ABC):
    """Abstract base for alliance auth system integrations.

    Provides a common interface for fetching authenticated ESI data
    from alliance management tools like Alliance Auth or SeAT.
    """

    def __init__(self, base_url: str, api_token: str) -> None:
        """Initialize the auth bridge.

        Args:
            base_url: Base URL of the auth system API.
            api_token: API token for authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=500, ttl=300)  # 5 min cache
        self._client: httpx.AsyncClient | None = None

    @property
    @abstractmethod
    def system_name(self) -> str:
        """Return the name of this auth system (e.g., 'alliance_auth', 'seat')."""

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def _get(self, endpoint: str) -> dict[str, Any] | list[Any]:
        """Make an authenticated GET request to the auth system."""

    @abstractmethod
    async def get_character_info(self, character_id: int) -> dict[str, Any]:
        """Get cached character data from auth system.

        Args:
            character_id: EVE character ID.

        Returns:
            Character profile data from the auth system.

        Raises:
            AuthBridgeNotFoundError: Character not found.
            AuthBridgeConnectionError: Connection failed.
        """

    @abstractmethod
    async def get_wallet_journal(
        self,
        character_id: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get wallet journal (may have longer history than ESI).

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of wallet journal entries.
        """

    @abstractmethod
    async def get_assets(self, character_id: int) -> list[dict[str, Any]]:
        """Get character assets with location info.

        Args:
            character_id: EVE character ID.

        Returns:
            List of asset entries.
        """

    @abstractmethod
    async def get_login_history(
        self,
        character_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get login timestamps for activity/TZ analysis.

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of login records with timestamps.
        """

    @abstractmethod
    async def get_standings(self, character_id: int) -> dict[str, Any]:
        """Get character's standings against alliance entities.

        Args:
            character_id: EVE character ID.

        Returns:
            Standings data.
        """

    async def enrich_applicant(self, applicant: Applicant) -> Applicant:
        """Add auth-system data to applicant.

        This method fetches wallet, assets, and activity data from the auth
        system and enriches the applicant profile.

        Args:
            applicant: The applicant to enrich.

        Returns:
            Enriched applicant with auth system data.
        """
        character_id = applicant.character_id

        # Fetch login history for activity analysis
        try:
            logins = await self.get_login_history(character_id)
            if logins:
                activity = self._analyze_activity(logins)
                applicant.activity = activity
        except AuthBridgeError:
            pass  # Activity analysis is optional

        # Fetch assets for asset summary
        try:
            assets = await self.get_assets(character_id)
            if assets:
                asset_summary = self._summarize_assets(assets)
                applicant.assets = asset_summary
        except AuthBridgeError:
            pass  # Asset data is optional

        # Fetch wallet journal for RMT/transfer analysis
        try:
            wallet_data = await self.get_wallet_journal(character_id)
            if wallet_data:
                applicant.wallet_journal = self._parse_wallet_journal(wallet_data)
        except AuthBridgeError:
            pass  # Wallet data is optional

        # Mark data source
        if self.system_name not in applicant.data_sources:
            applicant.data_sources.append(self.system_name)

        return applicant

    def _analyze_activity(self, logins: list[dict[str, Any]]) -> ActivityPattern:
        """Analyze login history to determine activity patterns.

        Args:
            logins: List of login records with timestamps.

        Returns:
            ActivityPattern with timezone and activity analysis.
        """
        if not logins:
            return ActivityPattern()

        # Extract login times
        login_times: list[datetime] = []
        for login in logins:
            timestamp = login.get("login_time") or login.get("timestamp")
            if timestamp:
                if isinstance(timestamp, str):
                    try:
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        login_times.append(dt)
                    except ValueError:
                        continue
                elif isinstance(timestamp, datetime):
                    login_times.append(timestamp)

        if not login_times:
            return ActivityPattern()

        # Analyze peak hours (EVE time = UTC)
        hour_counts: dict[int, int] = {}
        for dt in login_times:
            hour = dt.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        # Find peak hours (top 3)
        sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
        peak_hours = [h for h, _ in sorted_hours[:3]]

        # Determine primary timezone based on peak hours
        primary_tz = self._determine_timezone(peak_hours)

        # Calculate active days per week
        if len(login_times) >= 7:
            days_span = (max(login_times) - min(login_times)).days
            if days_span > 0:
                unique_days = len({dt.date() for dt in login_times})
                active_days = (unique_days / days_span) * 7
            else:
                active_days = 1.0
        else:
            active_days = None

        # Determine activity trend
        now = datetime.now(UTC)
        last_login = max(login_times) if login_times else None
        if last_login:
            days_since = (now - last_login).days
            if days_since > 90:
                trend = "inactive"
            elif days_since > 30:
                trend = "declining"
            else:
                # Check recent vs historical activity
                recent = [dt for dt in login_times if (now - dt).days <= 30]
                older = [dt for dt in login_times if 30 < (now - dt).days <= 60]
                if len(recent) > len(older) * 1.2:
                    trend = "increasing"
                elif len(recent) < len(older) * 0.8:
                    trend = "declining"
                else:
                    trend = "stable"
        else:
            trend = None

        return ActivityPattern(
            primary_timezone=primary_tz,
            peak_hours=peak_hours,
            active_days_per_week=active_days,
            last_kill_date=None,  # Set by killboard analyzer
            last_loss_date=None,
            activity_trend=trend,
        )

    def _determine_timezone(self, peak_hours: list[int]) -> str | None:
        """Determine timezone from peak activity hours.

        Args:
            peak_hours: List of peak hours (0-23 EVE/UTC time).

        Returns:
            Timezone string like 'EU-TZ', 'US-TZ', 'AU-TZ', or None.
        """
        if not peak_hours:
            return None

        avg_hour = sum(peak_hours) / len(peak_hours)

        # EVE time is UTC
        # EU-TZ: ~17:00-23:00 UTC (evening in Europe)
        # US-TZ: ~00:00-06:00 UTC (evening in US)
        # AU-TZ: ~08:00-14:00 UTC (evening in Australia)
        if 17 <= avg_hour <= 23:
            return "EU-TZ"
        elif 0 <= avg_hour <= 6:
            return "US-TZ"
        elif 8 <= avg_hour <= 14:
            return "AU-TZ"
        else:
            return None

    def _summarize_assets(self, assets: list[dict[str, Any]]) -> AssetSummary:
        """Summarize character assets.

        Args:
            assets: List of asset entries.

        Returns:
            AssetSummary with key metrics.
        """
        # Capital ship type IDs
        capital_type_ids = {
            # Carriers
            23757,  # Archon
            23911,  # Thanatos
            23915,  # Nidhoggur
            24483,  # Chimera
            # Dreadnoughts
            19720,  # Revelation
            19722,  # Moros
            19724,  # Naglfar
            19726,  # Phoenix
            # Force Auxiliaries
            37604,  # Apostle
            37605,  # Ninazu
            37606,  # Lif
            37607,  # Minokawa
        }

        # Supercapital type IDs
        super_type_ids = {
            # Supercarriers
            3514,  # Revenant
            22852,  # Hel
            23913,  # Nyx
            23917,  # Aeon
            23919,  # Wyvern
            # Titans
            671,  # Erebus
            3764,  # Leviathan
            11567,  # Avatar
            23773,  # Ragnarok
            42241,  # Molok
            42126,  # Vanquisher
            45649,  # Komodo
        }

        capitals: list[str] = []
        supers: list[str] = []
        total_value = 0.0
        location_counts: dict[str, int] = {}
        has_structures = False

        for asset in assets:
            type_id = asset.get("type_id")
            type_name = asset.get("type_name", str(type_id))
            value = asset.get("value", 0)

            total_value += value

            if type_id in capital_type_ids:
                capitals.append(type_name)
            elif type_id in super_type_ids:
                supers.append(type_name)

            # Check for structures
            if asset.get("is_structure") or asset.get("location_flag") == "StructureActive":
                has_structures = True

            # Track locations
            location = asset.get("location_name") or asset.get("location_id")
            if location:
                loc_str = str(location)
                location_counts[loc_str] = location_counts.get(loc_str, 0) + 1

        # Get top regions
        sorted_locs = sorted(location_counts.items(), key=lambda x: x[1], reverse=True)
        primary_regions = [loc for loc, _ in sorted_locs[:5]]

        return AssetSummary(
            total_value_isk=total_value if total_value > 0 else None,
            capital_ships=capitals,
            supercapitals=supers,
            primary_regions=primary_regions,
            has_structures=has_structures,
        )

    def _parse_wallet_journal(self, wallet_data: list[dict[str, Any]]) -> list[WalletEntry]:
        """Parse wallet journal data into WalletEntry objects.

        Args:
            wallet_data: Raw wallet journal entries from auth system.

        Returns:
            List of parsed WalletEntry objects.
        """
        entries: list[WalletEntry] = []

        for entry in wallet_data:
            try:
                # Extract date - handle various formats
                date_str = entry.get("date") or entry.get("timestamp")
                if isinstance(date_str, str):
                    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                elif isinstance(date_str, datetime):
                    date = date_str
                else:
                    continue  # Skip entries without valid date

                # Extract entry ID
                entry_id = entry.get("id") or entry.get("journal_id")
                if not entry_id:
                    continue

                # Extract ref_type
                ref_type = entry.get("ref_type") or entry.get("type", "unknown")

                # Extract amount
                amount = entry.get("amount", 0.0)
                if not isinstance(amount, (int, float)):
                    try:
                        amount = float(amount)
                    except (ValueError, TypeError):
                        amount = 0.0

                wallet_entry = WalletEntry(
                    id=int(entry_id),
                    date=date,
                    ref_type=str(ref_type),
                    amount=float(amount),
                    balance=entry.get("balance"),
                    first_party_id=entry.get("first_party_id"),
                    second_party_id=entry.get("second_party_id"),
                    reason=entry.get("reason"),
                )
                entries.append(wallet_entry)

            except (ValueError, TypeError, KeyError):
                # Skip malformed entries
                continue

        return entries


def get_auth_bridge(system: str, base_url: str, token: str) -> AuthBridge:
    """Factory to get appropriate auth bridge.

    Args:
        system: Auth system type ('alliance_auth' or 'seat').
        base_url: Base URL of the auth system.
        token: API token for authentication.

    Returns:
        Configured AuthBridge instance.

    Raises:
        ValueError: Unknown auth system type.
    """
    if system == "alliance_auth":
        from backend.connectors.alliance_auth import AllianceAuthAdapter

        return AllianceAuthAdapter(base_url, token)
    elif system == "seat":
        from backend.connectors.seat import SeATAdapter

        return SeATAdapter(base_url, token)
    else:
        raise ValueError(f"Unknown auth system: {system}")
