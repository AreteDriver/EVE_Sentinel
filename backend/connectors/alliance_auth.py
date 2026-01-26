"""Alliance Auth integration for EVE Sentinel.

Alliance Auth is a popular EVE Online authentication and management tool.
https://gitlab.com/allianceauth/allianceauth
"""

from typing import Any

import httpx

from backend.connectors.auth_bridge import (
    AuthBridge,
    AuthBridgeConnectionError,
    AuthBridgeNotFoundError,
)


class AllianceAuthAdapter(AuthBridge):
    """Adapter for Alliance Auth API.

    Alliance Auth provides authenticated ESI data access including:
    - Character information and registration status
    - Wallet journal (if scopes granted)
    - Asset lists (if scopes granted)
    - Login/activity tracking
    - Standing information
    """

    @property
    def system_name(self) -> str:
        """Return the auth system name."""
        return "alliance_auth"

    async def _get(self, endpoint: str) -> dict[str, Any] | list[Any]:
        """Make an authenticated GET request to Alliance Auth.

        Args:
            endpoint: API endpoint (e.g., '/api/characters/123/').

        Returns:
            JSON response data.

        Raises:
            AuthBridgeConnectionError: Connection or request failed.
        """
        cache_key = f"aa:{endpoint}"
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
                    "Authorization": f"Bearer {self.api_token}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
            self._cache[cache_key] = data
            if isinstance(data, dict):
                return dict(data)
            return list(data)

        except httpx.ConnectError as e:
            raise AuthBridgeConnectionError(
                f"Failed to connect to Alliance Auth: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise AuthBridgeNotFoundError(
                    f"Resource not found: {endpoint}"
                ) from e
            raise AuthBridgeConnectionError(
                f"Alliance Auth request failed: {e.response.status_code}"
            ) from e

    async def get_character_info(self, character_id: int) -> dict[str, Any]:
        """Get character data from Alliance Auth.

        Args:
            character_id: EVE character ID.

        Returns:
            Character profile data including registration status,
            main/alt relationship, and group memberships.

        Raises:
            AuthBridgeNotFoundError: Character not registered.
            AuthBridgeConnectionError: Connection failed.
        """
        data = await self._get(f"/api/characters/{character_id}/")
        if isinstance(data, dict):
            return data
        return {}

    async def get_wallet_journal(
        self,
        character_id: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get wallet journal from Alliance Auth.

        Alliance Auth may cache wallet data longer than ESI's 30-day limit,
        depending on configuration.

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of wallet journal entries.
        """
        try:
            endpoint = f"/api/characters/{character_id}/journal/"
            if limit != 1000:
                endpoint = f"{endpoint}?limit={limit}"
            data = await self._get(endpoint)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "results" in data:
                return list(data["results"])
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_assets(self, character_id: int) -> list[dict[str, Any]]:
        """Get character assets from Alliance Auth.

        Args:
            character_id: EVE character ID.

        Returns:
            List of asset entries with type, location, and quantity.
        """
        try:
            data = await self._get(f"/api/characters/{character_id}/assets/")
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "results" in data:
                return list(data["results"])
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_login_history(
        self,
        character_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get login history from Alliance Auth.

        Alliance Auth tracks character online/offline status via
        ESI's character_online scope.

        Args:
            character_id: EVE character ID.
            limit: Maximum entries to return.

        Returns:
            List of login records with timestamps.
        """
        try:
            data = await self._get(f"/api/characters/{character_id}/logins/")
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "results" in data:
                return list(data["results"])
            return []
        except AuthBridgeNotFoundError:
            return []

    async def get_standings(self, character_id: int) -> dict[str, Any]:
        """Get character standings from Alliance Auth.

        Args:
            character_id: EVE character ID.

        Returns:
            Standings data including personal, corp, and alliance standings.
        """
        try:
            data = await self._get(f"/api/characters/{character_id}/standings/")
            if isinstance(data, dict):
                return data
            return {}
        except AuthBridgeNotFoundError:
            return {}

    async def get_main_character(self, character_id: int) -> int | None:
        """Get the main character ID for an alt.

        Alliance Auth tracks main/alt relationships.

        Args:
            character_id: EVE character ID (may be an alt).

        Returns:
            Main character ID, or None if this is the main or not registered.
        """
        try:
            data = await self.get_character_info(character_id)
            main_id = data.get("main_character_id")
            if main_id and main_id != character_id:
                return int(main_id)
            return None
        except AuthBridgeNotFoundError:
            return None

    async def get_user_alts(self, character_id: int) -> list[int]:
        """Get all alt character IDs for a user.

        Args:
            character_id: EVE character ID (main or alt).

        Returns:
            List of character IDs associated with the same user account.
        """
        try:
            data = await self._get(f"/api/v1/characters/{character_id}/alts/")
            if isinstance(data, list):
                return [int(c.get("character_id", 0)) for c in data if c.get("character_id")]
            if isinstance(data, dict) and "characters" in data:
                return [
                    int(c.get("character_id", 0))
                    for c in data["characters"]
                    if c.get("character_id")
                ]
            return []
        except AuthBridgeNotFoundError:
            return []

    async def is_registered(self, character_id: int) -> bool:
        """Check if a character is registered in Alliance Auth.

        Args:
            character_id: EVE character ID.

        Returns:
            True if the character is registered, False otherwise.
        """
        try:
            await self.get_character_info(character_id)
            return True
        except AuthBridgeNotFoundError:
            return False
