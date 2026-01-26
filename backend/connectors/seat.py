"""SeAT (Simple EVE API Tool) integration for EVE Sentinel.

SeAT is a comprehensive EVE Online corporation management tool.
https://github.com/eveseat/seat
"""

from typing import Any

import httpx

from backend.connectors.auth_bridge import (
    AuthBridge,
    AuthBridgeConnectionError,
    AuthBridgeNotFoundError,
)


class SeATAdapter(AuthBridge):
    """Adapter for SeAT API.

    SeAT provides extensive authenticated ESI data including:
    - Character sheets and skills
    - Wallet transactions and journal
    - Asset lists with locations
    - Mail and contacts
    - Industry jobs
    - PI installations
    """

    @property
    def system_name(self) -> str:
        """Return the auth system name."""
        return "seat"

    async def _get(self, endpoint: str) -> dict[str, Any] | list[Any]:
        """Make an authenticated GET request to SeAT.

        Args:
            endpoint: API endpoint (e.g., '/api/v2/character/sheet/123').

        Returns:
            JSON response data.

        Raises:
            AuthBridgeConnectionError: Connection or request failed.
        """
        cache_key = f"seat:{endpoint}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if isinstance(cached, dict):
                return dict(cached)
            return list(cached)

        client = await self._get_client()
        url = f"{self.base_url}{endpoint}"

        try:
            response = await client.get(
                url,
                headers={
                    "X-Token": self.api_token,
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

            # SeAT wraps responses in a 'data' key
            if isinstance(data, dict) and "data" in data:
                data = data["data"]

            self._cache[cache_key] = data
            if isinstance(data, dict):
                return dict(data)
            return list(data)

        except httpx.ConnectError as e:
            raise AuthBridgeConnectionError(f"Failed to connect to SeAT: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise AuthBridgeNotFoundError(f"Resource not found: {endpoint}") from e
            raise AuthBridgeConnectionError(f"SeAT request failed: {e.response.status_code}") from e

    async def get_character_info(self, character_id: int) -> dict[str, Any]:
        """Get character sheet from SeAT.

        Args:
            character_id: EVE character ID.

        Returns:
            Character profile data including skills, implants, and attributes.

        Raises:
            AuthBridgeNotFoundError: Character not found in SeAT.
            AuthBridgeConnectionError: Connection failed.
        """
        data = await self._get(f"/api/v2/character/{character_id}")
        if isinstance(data, dict):
            return data
        return {}

    async def get_wallet_journal(
        self,
        character_id: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get wallet journal from SeAT.

        SeAT typically retains wallet history longer than ESI's 30-day limit.

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of wallet journal entries.
        """
        try:
            data = await self._get(f"/api/v2/character/{character_id}/wallet-journal")
            if isinstance(data, list):
                return data[:limit] if limit else data
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_assets(self, character_id: int) -> list[dict[str, Any]]:
        """Get character assets from SeAT.

        SeAT provides detailed asset information including:
        - Type and quantity
        - Location (station/structure/ship)
        - Estimated value

        Args:
            character_id: EVE character ID.

        Returns:
            List of asset entries.
        """
        try:
            data = await self._get(f"/api/v2/character/{character_id}/assets")
            if isinstance(data, list):
                return data
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_login_history(
        self,
        character_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get login/tracking history from SeAT.

        SeAT tracks character online status through the tracking module.
        Results are normalized to match Alliance Auth field names.

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of tracking records with normalized timestamps.
        """
        try:
            data = await self._get(f"/api/v2/character/{character_id}/tracking")
            if isinstance(data, list):
                # Normalize SeAT fields to match Alliance Auth format
                normalized = []
                for entry in data[:limit] if limit else data:
                    normalized_entry = dict(entry)
                    # Normalize timestamp -> login_time
                    if "timestamp" in entry and "login_time" not in entry:
                        normalized_entry["login_time"] = entry["timestamp"]
                    # Normalize nested location -> location_name
                    if "location" in entry and isinstance(entry["location"], dict):
                        normalized_entry["location_name"] = entry["location"].get("name")
                    # Normalize nested ship -> ship_type_name
                    if "ship" in entry and isinstance(entry["ship"], dict):
                        normalized_entry["ship_type_name"] = entry["ship"].get("name")
                    normalized.append(normalized_entry)
                return normalized
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_standings(self, character_id: int) -> dict[str, Any]:
        """Get character standings from SeAT.

        Args:
            character_id: EVE character ID.

        Returns:
            Standings data including agents, factions, and player entities.
        """
        try:
            data = await self._get(f"/api/v2/character/{character_id}/standings")
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"standings": data}
            return {}
        except AuthBridgeNotFoundError:
            return {}

    async def get_skills(self, character_id: int) -> list[dict[str, Any]]:
        """Get character skills from SeAT.

        Args:
            character_id: EVE character ID.

        Returns:
            List of skills with levels and skillpoints.
        """
        try:
            data = await self._get(f"/api/v2/character/skills/{character_id}")
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "skills" in data:
                return list(data["skills"])
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_contacts(self, character_id: int) -> list[dict[str, Any]]:
        """Get character contacts from SeAT.

        Args:
            character_id: EVE character ID.

        Returns:
            List of contacts with standings.
        """
        try:
            data = await self._get(f"/api/v2/character/contacts/{character_id}")
            if isinstance(data, list):
                return data
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_mail_headers(
        self,
        character_id: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get mail headers from SeAT.

        Note: Mail content may require additional permissions.

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of mail headers (subject, from, date).
        """
        try:
            data = await self._get(f"/api/v2/character/mail/{character_id}?limit={limit}")
            if isinstance(data, list):
                return data
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_corporation_members(self, corporation_id: int) -> list[dict[str, Any]]:
        """Get corporation member list from SeAT.

        Requires corporation director access in SeAT.

        Args:
            corporation_id: EVE corporation ID.

        Returns:
            List of corporation members with basic info.
        """
        try:
            data = await self._get(f"/api/v2/corporation/members/{corporation_id}")
            if isinstance(data, list):
                return data
            return []
        except AuthBridgeNotFoundError:
            return []

    async def search_character(self, name: str) -> int | None:
        """Search for a character by name in SeAT.

        Args:
            name: Character name to search.

        Returns:
            Character ID if found, None otherwise.
        """
        try:
            data = await self._get(f"/api/v2/character/search?name={name}")
            if isinstance(data, list) and len(data) > 0:
                return int(data[0].get("character_id", 0)) or None
            if isinstance(data, dict) and "character_id" in data:
                return int(data["character_id"])
            return None
        except AuthBridgeNotFoundError:
            return None
