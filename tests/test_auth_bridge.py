"""Tests for auth bridge adapters (Alliance Auth and SeAT)."""

import pytest
import respx
from httpx import Response

from backend.connectors.alliance_auth import AllianceAuthAdapter
from backend.connectors.auth_bridge import (
    AuthBridgeConnectionError,
    AuthBridgeNotFoundError,
    get_auth_bridge,
)
from backend.connectors.seat import SeATAdapter
from backend.models.applicant import Applicant

# Alliance Auth Test Data
AA_CHARACTER_RESPONSE = {
    "character_id": 12345678,
    "character_name": "Test Pilot",
    "corporation_id": 98000001,
    "corporation_name": "Test Corporation",
    "alliance_id": 99000001,
    "alliance_name": "Test Alliance",
    "main_character_id": None,
    "esi_token_valid": True,
}

AA_WALLET_JOURNAL_RESPONSE = [
    {
        "id": 1001,
        "date": "2026-01-10T15:30:00Z",
        "ref_type": "player_donation",
        "amount": 1000000.0,
        "balance": 5000000.0,
        "first_party_id": 99999999,
        "second_party_id": 12345678,
        "reason": "Test donation",
    },
    {
        "id": 1002,
        "date": "2026-01-09T10:00:00Z",
        "ref_type": "bounty_prizes",
        "amount": 500000.0,
        "balance": 4000000.0,
        "first_party_id": 1,
        "second_party_id": 12345678,
        "reason": None,
    },
]

AA_ASSETS_RESPONSE = [
    {
        "item_id": 2001,
        "type_id": 23757,  # Archon (carrier)
        "type_name": "Archon",
        "quantity": 1,
        "location_id": 60003760,
        "location_name": "Jita IV - Moon 4 - Caldari Navy Assembly Plant",
        "location_flag": "Hangar",
        "value": 2500000000.0,
    },
    {
        "item_id": 2002,
        "type_id": 587,  # Rifter
        "type_name": "Rifter",
        "quantity": 10,
        "location_id": 60003760,
        "location_name": "Jita IV - Moon 4 - Caldari Navy Assembly Plant",
        "location_flag": "Hangar",
        "value": 5000000.0,
    },
]

AA_LOGINS_RESPONSE = [
    {
        "login_time": "2026-01-10T19:30:00Z",
        "location_id": 60003760,
        "location_name": "Jita IV - Moon 4",
        "ship_type_id": 587,
        "ship_type_name": "Rifter",
        "online": True,
    },
    {
        "login_time": "2026-01-09T20:00:00Z",
        "location_id": 60003760,
        "location_name": "Jita IV - Moon 4",
        "ship_type_id": 587,
        "ship_type_name": "Rifter",
        "online": False,
    },
    {
        "login_time": "2026-01-08T18:30:00Z",
        "location_id": 30000142,
        "location_name": "Jita",
        "ship_type_id": 23757,
        "ship_type_name": "Archon",
        "online": False,
    },
]

AA_STANDINGS_RESPONSE = {
    "agent_standings": [],
    "faction_standings": [
        {"faction_id": 500001, "standing": 5.0},
    ],
    "npc_standings": [],
}

# SeAT Test Data (wrapped in 'data' key)
SEAT_CHARACTER_RESPONSE = {
    "data": {
        "character_id": 12345678,
        "name": "Test Pilot",
        "corporation_id": 98000001,
        "corporation": {"name": "Test Corporation"},
        "alliance_id": 99000001,
        "alliance": {"name": "Test Alliance"},
        "security_status": 2.5,
        "birthday": "2020-01-15T12:00:00Z",
    }
}

SEAT_WALLET_JOURNAL_RESPONSE = {
    "data": [
        {
            "id": 1001,
            "date": "2026-01-10T15:30:00Z",
            "ref_type": "player_donation",
            "amount": 1000000.0,
            "balance": 5000000.0,
            "first_party_id": 99999999,
            "second_party_id": 12345678,
            "reason": "Test donation",
        },
    ]
}

SEAT_ASSETS_RESPONSE = {
    "data": [
        {
            "item_id": 2001,
            "type_id": 23757,  # Archon
            "type": {"name": "Archon"},
            "quantity": 1,
            "location_id": 60003760,
            "location": {"name": "Jita IV - Moon 4"},
            "location_flag": "Hangar",
        },
    ]
}

SEAT_TRACKING_RESPONSE = {
    "data": [
        {
            "timestamp": "2026-01-10T19:30:00Z",
            "location_id": 60003760,
            "location": {"name": "Jita IV - Moon 4"},
            "ship_type_id": 587,
            "ship": {"name": "Rifter"},
            "online": True,
        },
    ]
}

SEAT_STANDINGS_RESPONSE = {
    "data": {
        "agent": [],
        "faction": [{"faction_id": 500001, "standing": 5.0}],
        "npc_corporation": [],
    }
}


class TestAuthBridgeFactory:
    """Tests for auth bridge factory function."""

    def test_get_alliance_auth_bridge(self):
        """Test factory returns Alliance Auth adapter."""
        bridge = get_auth_bridge("alliance_auth", "https://auth.test", "token123")

        assert isinstance(bridge, AllianceAuthAdapter)
        assert bridge.base_url == "https://auth.test"
        assert bridge.api_token == "token123"
        assert bridge.system_name == "alliance_auth"

    def test_get_seat_bridge(self):
        """Test factory returns SeAT adapter."""
        bridge = get_auth_bridge("seat", "https://seat.test", "token456")

        assert isinstance(bridge, SeATAdapter)
        assert bridge.base_url == "https://seat.test"
        assert bridge.api_token == "token456"
        assert bridge.system_name == "seat"

    def test_get_unknown_bridge(self):
        """Test factory raises error for unknown system."""
        with pytest.raises(ValueError, match="Unknown auth system"):
            get_auth_bridge("unknown_system", "https://test.com", "token")

    def test_url_trailing_slash_stripped(self):
        """Test that trailing slashes are stripped from base URL."""
        bridge = get_auth_bridge("alliance_auth", "https://auth.test/", "token")

        assert bridge.base_url == "https://auth.test"


class TestAllianceAuthAdapter:
    """Tests for Alliance Auth adapter."""

    @pytest.fixture
    def aa_adapter(self):
        """Create a fresh Alliance Auth adapter for each test."""
        adapter = AllianceAuthAdapter("https://auth.test", "test_token")
        yield adapter

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_character_info(self, aa_adapter):
        """Test fetching character info from Alliance Auth."""
        respx.get("https://auth.test/api/characters/12345678/").mock(
            return_value=Response(200, json=AA_CHARACTER_RESPONSE)
        )

        result = await aa_adapter.get_character_info(12345678)

        assert result["character_id"] == 12345678
        assert result["character_name"] == "Test Pilot"
        assert result["esi_token_valid"] is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_wallet_journal(self, aa_adapter):
        """Test fetching wallet journal from Alliance Auth."""
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=AA_WALLET_JOURNAL_RESPONSE)
        )

        result = await aa_adapter.get_wallet_journal(12345678)

        assert len(result) == 2
        assert result[0]["amount"] == 1000000.0
        assert result[0]["ref_type"] == "player_donation"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_wallet_journal_with_limit(self, aa_adapter):
        """Test wallet journal respects limit parameter."""
        respx.get("https://auth.test/api/characters/12345678/journal/?limit=50").mock(
            return_value=Response(200, json=AA_WALLET_JOURNAL_RESPONSE[:1])
        )

        result = await aa_adapter.get_wallet_journal(12345678, limit=50)

        assert len(result) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_assets(self, aa_adapter):
        """Test fetching assets from Alliance Auth."""
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=AA_ASSETS_RESPONSE)
        )

        result = await aa_adapter.get_assets(12345678)

        assert len(result) == 2
        assert result[0]["type_name"] == "Archon"
        assert result[0]["value"] == 2500000000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_login_history(self, aa_adapter):
        """Test fetching login history from Alliance Auth."""
        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=AA_LOGINS_RESPONSE)
        )

        result = await aa_adapter.get_login_history(12345678)

        assert len(result) == 3
        assert result[0]["login_time"] == "2026-01-10T19:30:00Z"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_standings(self, aa_adapter):
        """Test fetching standings from Alliance Auth."""
        respx.get("https://auth.test/api/characters/12345678/standings/").mock(
            return_value=Response(200, json=AA_STANDINGS_RESPONSE)
        )

        result = await aa_adapter.get_standings(12345678)

        assert "faction_standings" in result
        assert len(result["faction_standings"]) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_raises_not_found_error(self, aa_adapter):
        """Test that 404 response raises AuthBridgeNotFoundError."""
        respx.get("https://auth.test/api/characters/99999999/").mock(
            return_value=Response(404, json={"detail": "Not found"})
        )

        with pytest.raises(AuthBridgeNotFoundError):
            await aa_adapter.get_character_info(99999999)

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_connection_error(self, aa_adapter):
        """Test that 500 response raises AuthBridgeConnectionError."""
        respx.get("https://auth.test/api/characters/12345678/").mock(
            return_value=Response(500, json={"detail": "Server error"})
        )

        with pytest.raises(AuthBridgeConnectionError):
            await aa_adapter.get_character_info(12345678)

    @pytest.mark.asyncio
    @respx.mock
    async def test_caching(self, aa_adapter):
        """Test that responses are cached."""
        route = respx.get("https://auth.test/api/characters/12345678/").mock(
            return_value=Response(200, json=AA_CHARACTER_RESPONSE)
        )

        # First call
        await aa_adapter.get_character_info(12345678)
        # Second call should use cache
        await aa_adapter.get_character_info(12345678)

        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_authorization_header(self, aa_adapter):
        """Test that correct authorization header is sent."""
        route = respx.get("https://auth.test/api/characters/12345678/").mock(
            return_value=Response(200, json=AA_CHARACTER_RESPONSE)
        )

        await aa_adapter.get_character_info(12345678)

        assert route.calls[0].request.headers["Authorization"] == "Bearer test_token"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_main_character(self, aa_adapter):
        """Test getting main character ID for an alt."""
        alt_response = {**AA_CHARACTER_RESPONSE, "main_character_id": 87654321}
        respx.get("https://auth.test/api/characters/12345678/").mock(
            return_value=Response(200, json=alt_response)
        )

        result = await aa_adapter.get_main_character(12345678)

        assert result == 87654321

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_main_character_returns_none_for_main(self, aa_adapter):
        """Test that main characters return None for main_character_id."""
        respx.get("https://auth.test/api/characters/12345678/").mock(
            return_value=Response(200, json=AA_CHARACTER_RESPONSE)
        )

        result = await aa_adapter.get_main_character(12345678)

        assert result is None


class TestSeATAdapter:
    """Tests for SeAT adapter."""

    @pytest.fixture
    def seat_adapter(self):
        """Create a fresh SeAT adapter for each test."""
        adapter = SeATAdapter("https://seat.test", "test_token")
        yield adapter

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_character_info(self, seat_adapter):
        """Test fetching character info from SeAT."""
        respx.get("https://seat.test/api/v2/character/12345678").mock(
            return_value=Response(200, json=SEAT_CHARACTER_RESPONSE)
        )

        result = await seat_adapter.get_character_info(12345678)

        assert result["character_id"] == 12345678
        assert result["name"] == "Test Pilot"
        assert result["security_status"] == 2.5

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_wallet_journal(self, seat_adapter):
        """Test fetching wallet journal from SeAT."""
        respx.get("https://seat.test/api/v2/character/12345678/wallet-journal").mock(
            return_value=Response(200, json=SEAT_WALLET_JOURNAL_RESPONSE)
        )

        result = await seat_adapter.get_wallet_journal(12345678)

        assert len(result) == 1
        assert result[0]["amount"] == 1000000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_assets(self, seat_adapter):
        """Test fetching assets from SeAT."""
        respx.get("https://seat.test/api/v2/character/12345678/assets").mock(
            return_value=Response(200, json=SEAT_ASSETS_RESPONSE)
        )

        result = await seat_adapter.get_assets(12345678)

        assert len(result) == 1
        assert result[0]["type_id"] == 23757

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_login_history(self, seat_adapter):
        """Test fetching login history from SeAT (normalized fields)."""
        respx.get("https://seat.test/api/v2/character/12345678/tracking").mock(
            return_value=Response(200, json=SEAT_TRACKING_RESPONSE)
        )

        result = await seat_adapter.get_login_history(12345678)

        assert len(result) == 1
        # SeAT uses 'timestamp', but we normalize to 'login_time'
        assert result[0]["login_time"] == "2026-01-10T19:30:00Z"
        assert result[0]["location_name"] == "Jita IV - Moon 4"
        assert result[0]["ship_type_name"] == "Rifter"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_standings(self, seat_adapter):
        """Test fetching standings from SeAT."""
        respx.get("https://seat.test/api/v2/character/12345678/standings").mock(
            return_value=Response(200, json=SEAT_STANDINGS_RESPONSE)
        )

        result = await seat_adapter.get_standings(12345678)

        assert "faction" in result
        assert len(result["faction"]) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_x_token_header(self, seat_adapter):
        """Test that correct X-Token header is sent."""
        route = respx.get("https://seat.test/api/v2/character/12345678").mock(
            return_value=Response(200, json=SEAT_CHARACTER_RESPONSE)
        )

        await seat_adapter.get_character_info(12345678)

        assert route.calls[0].request.headers["X-Token"] == "test_token"

    @pytest.mark.asyncio
    @respx.mock
    async def test_data_wrapper_unwrapped(self, seat_adapter):
        """Test that SeAT's 'data' wrapper is unwrapped."""
        respx.get("https://seat.test/api/v2/character/12345678").mock(
            return_value=Response(200, json=SEAT_CHARACTER_RESPONSE)
        )

        result = await seat_adapter.get_character_info(12345678)

        # Should get the inner data, not the wrapper
        assert "data" not in result
        assert result["character_id"] == 12345678


class TestAuthBridgeEnrichment:
    """Tests for applicant enrichment via auth bridges."""

    @pytest.fixture
    def sample_applicant(self):
        """Create a sample applicant for testing."""
        return Applicant(
            character_id=12345678,
            character_name="Test Pilot",
            corporation_id=98000001,
            corporation_name="Test Corporation",
            alliance_id=99000001,
            alliance_name="Test Alliance",
            data_sources=["esi", "zkill"],
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_enrich_applicant_adds_activity(self, sample_applicant):
        """Test that enrichment adds activity pattern."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=AA_LOGINS_RESPONSE)
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=AA_ASSETS_RESPONSE)
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        enriched = await adapter.enrich_applicant(sample_applicant)

        assert enriched.activity is not None
        # Login times are 18:30, 19:30, 20:00 UTC = EU-TZ
        assert enriched.activity.primary_timezone == "EU-TZ"
        assert "alliance_auth" in enriched.data_sources

    @pytest.mark.asyncio
    @respx.mock
    async def test_enrich_applicant_adds_assets(self, sample_applicant):
        """Test that enrichment adds asset summary."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=AA_ASSETS_RESPONSE)
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        enriched = await adapter.enrich_applicant(sample_applicant)

        assert enriched.assets is not None
        assert enriched.assets.total_value_isk == 2505000000.0  # 2.5B + 5M
        assert "Archon" in enriched.assets.capital_ships

    @pytest.mark.asyncio
    @respx.mock
    async def test_enrich_applicant_handles_errors_gracefully(self, sample_applicant):
        """Test that enrichment continues even if auth bridge errors."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        # All endpoints return 404
        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(404, json={"detail": "Not found"})
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(404, json={"detail": "Not found"})
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(404, json={"detail": "Not found"})
        )

        # Should not raise, just skip enrichment
        enriched = await adapter.enrich_applicant(sample_applicant)

        assert enriched is not None
        assert enriched.character_id == 12345678
        # Data source still added as we attempted enrichment
        assert "alliance_auth" in enriched.data_sources

    @pytest.mark.asyncio
    @respx.mock
    async def test_enrich_applicant_doesnt_duplicate_data_source(self, sample_applicant):
        """Test that data source isn't duplicated on re-enrichment."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")
        sample_applicant.data_sources.append("alliance_auth")

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        enriched = await adapter.enrich_applicant(sample_applicant)

        assert enriched.data_sources.count("alliance_auth") == 1


class TestActivityAnalysis:
    """Tests for activity pattern analysis."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_timezone_detection_eu(self):
        """Test EU timezone detection from peak hours."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        # Logins at 18:00, 19:00, 20:00 UTC
        eu_logins = [
            {"login_time": "2026-01-10T18:00:00Z"},
            {"login_time": "2026-01-10T19:00:00Z"},
            {"login_time": "2026-01-10T20:00:00Z"},
        ]

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=eu_logins)
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        assert enriched.activity.primary_timezone == "EU-TZ"

    @pytest.mark.asyncio
    @respx.mock
    async def test_timezone_detection_us(self):
        """Test US timezone detection from peak hours."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        # Logins at 01:00, 02:00, 03:00 UTC (evening US)
        us_logins = [
            {"login_time": "2026-01-10T01:00:00Z"},
            {"login_time": "2026-01-10T02:00:00Z"},
            {"login_time": "2026-01-10T03:00:00Z"},
        ]

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=us_logins)
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        assert enriched.activity.primary_timezone == "US-TZ"

    @pytest.mark.asyncio
    @respx.mock
    async def test_timezone_detection_au(self):
        """Test AU timezone detection from peak hours."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        # Logins at 09:00, 10:00, 11:00 UTC (evening AU)
        au_logins = [
            {"login_time": "2026-01-10T09:00:00Z"},
            {"login_time": "2026-01-10T10:00:00Z"},
            {"login_time": "2026-01-10T11:00:00Z"},
        ]

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=au_logins)
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        assert enriched.activity.primary_timezone == "AU-TZ"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_logins_returns_empty_activity(self):
        """Test that empty login history returns empty activity."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        assert enriched.activity.primary_timezone is None
        assert enriched.activity.peak_hours == []


class TestAssetAnalysis:
    """Tests for asset summary analysis."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_capital_ship_detection(self):
        """Test that capital ships are detected in assets."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        assets_with_capitals = [
            {"type_id": 23757, "type_name": "Archon", "value": 2500000000.0},
            {"type_id": 19720, "type_name": "Revelation", "value": 3500000000.0},
        ]

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=assets_with_capitals)
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        assert len(enriched.assets.capital_ships) == 2
        assert "Archon" in enriched.assets.capital_ships
        assert "Revelation" in enriched.assets.capital_ships

    @pytest.mark.asyncio
    @respx.mock
    async def test_supercapital_detection(self):
        """Test that supercapitals are detected in assets."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        assets_with_supers = [
            {"type_id": 23913, "type_name": "Nyx", "value": 25000000000.0},
            {"type_id": 671, "type_name": "Erebus", "value": 100000000000.0},
        ]

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=assets_with_supers)
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        assert len(enriched.assets.supercapitals) == 2
        assert "Nyx" in enriched.assets.supercapitals
        assert "Erebus" in enriched.assets.supercapitals

    @pytest.mark.asyncio
    @respx.mock
    async def test_total_value_calculation(self):
        """Test that total asset value is calculated correctly."""
        adapter = AllianceAuthAdapter("https://auth.test", "token")

        assets = [
            {"type_id": 587, "type_name": "Rifter", "value": 500000.0},
            {"type_id": 24690, "type_name": "Hurricane", "value": 50000000.0},
            {"type_id": 23757, "type_name": "Archon", "value": 2500000000.0},
        ]

        respx.get("https://auth.test/api/characters/12345678/logins/").mock(
            return_value=Response(200, json=[])
        )
        respx.get("https://auth.test/api/characters/12345678/assets/").mock(
            return_value=Response(200, json=assets)
        )
        respx.get("https://auth.test/api/characters/12345678/journal/").mock(
            return_value=Response(200, json=[])
        )

        applicant = Applicant(character_id=12345678, character_name="Test")
        enriched = await adapter.enrich_applicant(applicant)

        expected_total = 500000.0 + 50000000.0 + 2500000000.0
        assert enriched.assets.total_value_isk == expected_total
