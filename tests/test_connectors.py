"""Tests for ESI and zKillboard connectors."""

import pytest
import respx
from httpx import Response

from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient

# ESI Test Data
ESI_CHARACTER_RESPONSE = {
    "birthday": "2020-01-15T12:00:00Z",
    "corporation_id": 98000001,
    "name": "Test Pilot",
    "security_status": 2.5,
}

ESI_CORPORATION_RESPONSE = {
    "name": "Test Corporation",
    "ticker": "TEST",
    "alliance_id": 99000001,
}

ESI_ALLIANCE_RESPONSE = {
    "name": "Test Alliance",
    "ticker": "TSTA",
}

ESI_CORP_HISTORY_RESPONSE = [
    {
        "corporation_id": 98000001,
        "record_id": 1,
        "start_date": "2022-06-01T00:00:00Z",
    },
    {
        "corporation_id": 98000002,
        "record_id": 2,
        "start_date": "2021-01-01T00:00:00Z",
    },
]

ESI_SEARCH_RESPONSE = {
    "character": [12345678],
}


# zKillboard Test Data
ZKILL_KILLS_RESPONSE = [
    {
        "killmail_id": 1001,
        "killmail_time": "2026-01-10T15:30:00Z",
        "victim": {
            "character_id": 99999999,
            "corporation_id": 88888888,
        },
        "attackers": [
            {"character_id": 12345678, "ship_type_id": 11567},
        ],
        "solar_system_id": 30000142,
        "zkb": {"totalValue": 50000000},
    },
    {
        "killmail_id": 1002,
        "killmail_time": "2026-01-05T10:00:00Z",
        "victim": {
            "character_id": 77777777,
            "corporation_id": 66666666,
        },
        "attackers": [
            {"character_id": 12345678, "ship_type_id": 11567},
            {"character_id": 55555555, "ship_type_id": 11567},
        ],
        "solar_system_id": 30000142,
        "zkb": {"totalValue": 25000000},
    },
]

ZKILL_LOSSES_RESPONSE = [
    {
        "killmail_id": 2001,
        "killmail_time": "2026-01-08T20:00:00Z",
        "victim": {
            "character_id": 12345678,
            "corporation_id": 98000001,
        },
        "attackers": [
            {"character_id": 11111111, "ship_type_id": 587},
        ],
        "zkb": {"totalValue": 100000000},
    },
]


class TestESIClient:
    """Tests for ESIClient."""

    @pytest.fixture
    def esi_client(self):
        """Create a fresh ESI client for each test."""
        client = ESIClient()
        yield client
        # Cleanup not strictly needed but good practice

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_character(self, esi_client):
        """Test fetching character info."""
        respx.get("https://esi.evetech.net/latest/characters/12345678/").mock(
            return_value=Response(200, json=ESI_CHARACTER_RESPONSE)
        )

        result = await esi_client.get_character(12345678)

        assert result["name"] == "Test Pilot"
        assert result["corporation_id"] == 98000001
        assert result["security_status"] == 2.5

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_corporation(self, esi_client):
        """Test fetching corporation info."""
        respx.get("https://esi.evetech.net/latest/corporations/98000001/").mock(
            return_value=Response(200, json=ESI_CORPORATION_RESPONSE)
        )

        result = await esi_client.get_corporation(98000001)

        assert result["name"] == "Test Corporation"
        assert result["alliance_id"] == 99000001

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_alliance(self, esi_client):
        """Test fetching alliance info."""
        respx.get("https://esi.evetech.net/latest/alliances/99000001/").mock(
            return_value=Response(200, json=ESI_ALLIANCE_RESPONSE)
        )

        result = await esi_client.get_alliance(99000001)

        assert result["name"] == "Test Alliance"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_character_corp_history(self, esi_client):
        """Test fetching corporation history."""
        respx.get("https://esi.evetech.net/latest/characters/12345678/corporationhistory/").mock(
            return_value=Response(200, json=ESI_CORP_HISTORY_RESPONSE)
        )

        result = await esi_client.get_character_corp_history(12345678)

        assert len(result) == 2
        assert result[0]["corporation_id"] == 98000001

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_character_found(self, esi_client):
        """Test searching for a character by name."""
        respx.get("https://esi.evetech.net/latest/search/").mock(
            return_value=Response(200, json=ESI_SEARCH_RESPONSE)
        )

        result = await esi_client.search_character("Test Pilot")

        assert result == 12345678

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_character_not_found(self, esi_client):
        """Test searching for a non-existent character."""
        respx.get("https://esi.evetech.net/latest/search/").mock(
            return_value=Response(200, json={})
        )

        result = await esi_client.search_character("NonexistentPilot")

        assert result is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_build_applicant(self, esi_client):
        """Test building a complete applicant profile."""
        # Mock all required endpoints
        respx.get("https://esi.evetech.net/latest/characters/12345678/").mock(
            return_value=Response(200, json=ESI_CHARACTER_RESPONSE)
        )
        respx.get("https://esi.evetech.net/latest/characters/12345678/corporationhistory/").mock(
            return_value=Response(200, json=ESI_CORP_HISTORY_RESPONSE)
        )
        respx.get("https://esi.evetech.net/latest/corporations/98000001/").mock(
            return_value=Response(200, json=ESI_CORPORATION_RESPONSE)
        )
        respx.get("https://esi.evetech.net/latest/corporations/98000002/").mock(
            return_value=Response(200, json={"name": "Previous Corp"})
        )
        respx.get("https://esi.evetech.net/latest/alliances/99000001/").mock(
            return_value=Response(200, json=ESI_ALLIANCE_RESPONSE)
        )

        applicant = await esi_client.build_applicant(12345678)

        assert applicant.character_id == 12345678
        assert applicant.character_name == "Test Pilot"
        assert applicant.corporation_id == 98000001
        assert applicant.corporation_name == "Test Corporation"
        assert applicant.alliance_id == 99000001
        assert applicant.alliance_name == "Test Alliance"
        assert len(applicant.corp_history) == 2
        assert "esi" in applicant.data_sources

    @pytest.mark.asyncio
    @respx.mock
    async def test_caching(self, esi_client):
        """Test that responses are cached."""
        route = respx.get("https://esi.evetech.net/latest/characters/12345678/").mock(
            return_value=Response(200, json=ESI_CHARACTER_RESPONSE)
        )

        # First call
        await esi_client.get_character(12345678)
        # Second call should use cache
        await esi_client.get_character(12345678)

        assert route.call_count == 1  # Only one HTTP request made


class TestZKillClient:
    """Tests for ZKillClient."""

    @pytest.fixture
    def zkill_client(self):
        """Create a fresh zKill client for each test."""
        client = ZKillClient()
        yield client

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_character_kills(self, zkill_client):
        """Test fetching character kills."""
        respx.get("https://zkillboard.com/api/kills/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=ZKILL_KILLS_RESPONSE)
        )

        result = await zkill_client.get_character_kills(12345678)

        assert len(result) == 2
        assert result[0]["killmail_id"] == 1001

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_character_losses(self, zkill_client):
        """Test fetching character losses."""
        respx.get("https://zkillboard.com/api/losses/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=ZKILL_LOSSES_RESPONSE)
        )

        result = await zkill_client.get_character_losses(12345678)

        assert len(result) == 1
        assert result[0]["killmail_id"] == 2001

    @pytest.mark.asyncio
    @respx.mock
    async def test_build_killboard_stats(self, zkill_client):
        """Test building killboard statistics."""
        respx.get("https://zkillboard.com/api/kills/characterID/12345678/limit/500/").mock(
            return_value=Response(200, json=ZKILL_KILLS_RESPONSE)
        )
        respx.get("https://zkillboard.com/api/losses/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=ZKILL_LOSSES_RESPONSE)
        )

        stats = await zkill_client.build_killboard_stats(12345678)

        assert stats.kills_total == 2
        assert stats.deaths_total == 1
        assert stats.solo_kills == 1  # First kill is solo
        assert stats.isk_destroyed == 75000000  # 50M + 25M
        assert stats.isk_lost == 100000000

    @pytest.mark.asyncio
    @respx.mock
    async def test_build_killboard_stats_empty(self, zkill_client):
        """Test handling empty killboard."""
        respx.get("https://zkillboard.com/api/kills/characterID/12345678/limit/500/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://zkillboard.com/api/losses/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=[])
        )

        stats = await zkill_client.build_killboard_stats(12345678)

        assert stats.kills_total == 0
        assert stats.deaths_total == 0
        assert stats.solo_kills == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_enrich_applicant(self, zkill_client):
        """Test enriching an applicant with killboard data."""
        from backend.models.applicant import Applicant

        respx.get("https://zkillboard.com/api/kills/characterID/12345678/limit/500/").mock(
            return_value=Response(200, json=ZKILL_KILLS_RESPONSE)
        )
        respx.get("https://zkillboard.com/api/losses/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=ZKILL_LOSSES_RESPONSE)
        )

        applicant = Applicant(
            character_id=12345678,
            character_name="Test Pilot",
            corporation_id=98000001,
        )

        enriched = await zkill_client.enrich_applicant(applicant)

        assert enriched.killboard.kills_total == 2
        assert enriched.killboard.deaths_total == 1
        assert "zkill" in enriched.data_sources

    @pytest.mark.asyncio
    @respx.mock
    async def test_awox_detection(self, zkill_client):
        """Test AWOX kill detection (kills on corp mates)."""
        # Kill where victim is in same corp
        awox_kills = [
            {
                "killmail_id": 3001,
                "killmail_time": "2026-01-10T15:30:00Z",
                "victim": {
                    "character_id": 99999999,
                    "corporation_id": 98000001,  # Same corp as killer
                },
                "attackers": [
                    {"character_id": 12345678, "ship_type_id": 11567},
                ],
                "solar_system_id": 30000142,
                "zkb": {"totalValue": 10000000},
            },
        ]

        respx.get("https://zkillboard.com/api/kills/characterID/12345678/limit/500/").mock(
            return_value=Response(200, json=awox_kills)
        )
        respx.get("https://zkillboard.com/api/losses/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=[])
        )

        stats = await zkill_client.build_killboard_stats(12345678, current_corp_id=98000001)

        assert stats.awox_kills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_caching(self, zkill_client):
        """Test that responses are cached."""
        route = respx.get("https://zkillboard.com/api/kills/characterID/12345678/limit/200/").mock(
            return_value=Response(200, json=ZKILL_KILLS_RESPONSE)
        )

        # First call
        await zkill_client.get_character_kills(12345678)
        # Second call should use cache
        await zkill_client.get_character_kills(12345678)

        assert route.call_count == 1
