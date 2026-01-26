"""Tests for authenticated ESI client."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.connectors.esi_authenticated import AuthenticatedESIClient
from backend.models.applicant import Applicant


class TestAuthenticatedESIClient:
    """Tests for AuthenticatedESIClient class."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return AuthenticatedESIClient(
            access_token="test_token_12345",
            character_id=12345678,
        )

    def test_init_stores_token_and_character(self, client):
        """Test that init stores access token and character ID."""
        assert client.access_token == "test_token_12345"
        assert client.character_id == 12345678
        assert client._client is None

    def test_scopes_defined(self):
        """Test that required scopes are defined."""
        assert "wallet" in AuthenticatedESIClient.SCOPES
        assert "assets" in AuthenticatedESIClient.SCOPES
        assert "contacts" in AuthenticatedESIClient.SCOPES
        assert "standings" in AuthenticatedESIClient.SCOPES

    def test_capital_type_ids_defined(self):
        """Test that capital ship type IDs are defined."""
        caps = AuthenticatedESIClient.CAPITAL_TYPE_IDS
        assert len(caps) > 0
        # Check for known capital type IDs
        assert 23757 in caps  # Archon
        assert 19720 in caps  # Revelation
        assert 28352 in caps  # Rorqual

    def test_supercapital_type_ids_defined(self):
        """Test that supercapital type IDs are defined."""
        supers = AuthenticatedESIClient.SUPERCAPITAL_TYPE_IDS
        assert len(supers) > 0
        # Check for known supercapital type IDs
        assert 23919 in supers  # Aeon
        assert 11567 in supers  # Avatar
        assert 671 in supers    # Erebus


class TestAuthenticatedESIClientHTTP:
    """Tests for HTTP methods with mocked client."""

    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        mock = MagicMock()
        mock.get = AsyncMock()
        mock.aclose = AsyncMock()
        return mock

    @pytest.fixture
    def client_with_mock(self, mock_http_client):
        """Create client with mock HTTP client."""
        client = AuthenticatedESIClient("test_token", 12345)
        client._client = mock_http_client
        return client

    @pytest.mark.asyncio
    async def test_close_closes_client(self, client_with_mock, mock_http_client):
        """Test that close() closes the HTTP client."""
        await client_with_mock.close()
        mock_http_client.aclose.assert_called_once()
        assert client_with_mock._client is None

    @pytest.mark.asyncio
    async def test_close_handles_no_client(self):
        """Test that close() handles no client gracefully."""
        client = AuthenticatedESIClient("token", 123)
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_get_wallet_journal(self, client_with_mock, mock_http_client):
        """Test fetching wallet journal."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": 1, "ref_type": "player_donation", "amount": 1000000},
            {"id": 2, "ref_type": "market_transaction", "amount": -50000},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response

        with patch("backend.connectors.esi_authenticated.redis_cache") as mock_cache:
            mock_cache.is_available = False

            result = await client_with_mock.get_wallet_journal()

        assert len(result) == 2
        assert result[0]["ref_type"] == "player_donation"

    @pytest.mark.asyncio
    async def test_get_wallet_balance(self, client_with_mock, mock_http_client):
        """Test fetching wallet balance."""
        mock_response = MagicMock()
        mock_response.json.return_value = 5000000000.50  # 5 billion ISK
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response

        with patch("backend.connectors.esi_authenticated.redis_cache") as mock_cache:
            mock_cache.is_available = False

            result = await client_with_mock.get_wallet_balance()

        assert result == 5000000000.50

    @pytest.mark.asyncio
    async def test_get_assets_pagination(self, client_with_mock, mock_http_client):
        """Test that assets fetches multiple pages."""
        page1 = [{"type_id": 1} for _ in range(1000)]  # Full page
        page2 = [{"type_id": 2} for _ in range(500)]   # Partial page

        mock_response1 = MagicMock()
        mock_response1.json.return_value = page1
        mock_response1.raise_for_status = MagicMock()

        mock_response2 = MagicMock()
        mock_response2.json.return_value = page2
        mock_response2.raise_for_status = MagicMock()

        mock_http_client.get.side_effect = [mock_response1, mock_response2]

        with patch("backend.connectors.esi_authenticated.redis_cache") as mock_cache:
            mock_cache.is_available = False

            result = await client_with_mock.get_assets()

        assert len(result) == 1500  # Both pages combined

    @pytest.mark.asyncio
    async def test_get_contacts(self, client_with_mock, mock_http_client):
        """Test fetching contacts."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"contact_id": 111, "standing": 10.0},
            {"contact_id": 222, "standing": -10.0},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response

        with patch("backend.connectors.esi_authenticated.redis_cache") as mock_cache:
            mock_cache.is_available = False

            result = await client_with_mock.get_contacts()

        assert len(result) == 2
        assert result[0]["standing"] == 10.0

    @pytest.mark.asyncio
    async def test_get_standings(self, client_with_mock, mock_http_client):
        """Test fetching standings."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"from_id": 500001, "from_type": "faction", "standing": 5.0},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response

        with patch("backend.connectors.esi_authenticated.redis_cache") as mock_cache:
            mock_cache.is_available = False

            result = await client_with_mock.get_standings()

        assert len(result) == 1
        assert result[0]["from_type"] == "faction"


class TestBuildMethods:
    """Tests for build_* methods."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return AuthenticatedESIClient("token", 12345)

    @pytest.mark.asyncio
    async def test_build_wallet_entries(self, client):
        """Test building wallet entries from journal."""
        journal_data = [
            {
                "id": 1,
                "date": "2024-01-15T12:00:00Z",
                "ref_type": "player_donation",
                "amount": 1000000,
                "balance": 5000000,
                "first_party_id": 123,
                "second_party_id": 456,
                "reason": "Thanks!",
            },
            {
                "id": 2,
                "date": "2024-01-14T10:00:00Z",
                "ref_type": "market_transaction",
                "amount": -50000,
            },
        ]

        with patch.object(client, "get_wallet_journal", return_value=journal_data):
            entries = await client.build_wallet_entries(limit=10)

        assert len(entries) == 2
        assert entries[0].ref_type == "player_donation"
        assert entries[0].amount == 1000000
        assert entries[1].ref_type == "market_transaction"
        assert entries[1].amount == -50000

    @pytest.mark.asyncio
    async def test_build_asset_summary_detects_capitals(self, client):
        """Test that asset summary detects capital ships."""
        assets_data = [
            {"type_id": 23757, "location_id": 1000, "quantity": 1},  # Archon
            {"type_id": 19720, "location_id": 1000, "quantity": 1},  # Revelation
            {"type_id": 587, "location_id": 2000, "quantity": 100},  # Random item
        ]

        with patch.object(client, "get_assets", return_value=assets_data):
            summary = await client.build_asset_summary()

        assert len(summary.capital_ships) == 2
        assert "TypeID:23757" in summary.capital_ships  # Archon
        assert "TypeID:19720" in summary.capital_ships  # Revelation

    @pytest.mark.asyncio
    async def test_build_asset_summary_detects_supercapitals(self, client):
        """Test that asset summary detects supercapitals."""
        assets_data = [
            {"type_id": 23919, "location_id": 1000, "quantity": 1},  # Aeon
            {"type_id": 11567, "location_id": 1000, "quantity": 1},  # Avatar
        ]

        with patch.object(client, "get_assets", return_value=assets_data):
            summary = await client.build_asset_summary()

        assert len(summary.supercapitals) == 2
        assert "TypeID:23919" in summary.supercapitals  # Aeon
        assert "TypeID:11567" in summary.supercapitals  # Avatar

    @pytest.mark.asyncio
    async def test_build_asset_summary_tracks_locations(self, client):
        """Test that asset summary tracks primary locations."""
        assets_data = [
            {"type_id": 1, "location_id": 60003760, "quantity": 50},
            {"type_id": 2, "location_id": 60003760, "quantity": 30},
            {"type_id": 3, "location_id": 60004588, "quantity": 10},
        ]

        with patch.object(client, "get_assets", return_value=assets_data):
            summary = await client.build_asset_summary()

        # 60003760 should be first (80 items) then 60004588 (10 items)
        assert len(summary.primary_regions) <= 5
        assert "60003760" in summary.primary_regions

    @pytest.mark.asyncio
    async def test_build_standings_data(self, client):
        """Test building standings data structure."""
        contacts = [{"contact_id": 1, "standing": 10}]
        standings = [{"from_id": 500001, "standing": 5}]

        with patch.object(client, "get_contacts", return_value=contacts):
            with patch.object(client, "get_standings", return_value=standings):
                data = await client.build_standings_data()

        assert "contacts" in data
        assert "standings" in data
        assert len(data["contacts"]) == 1
        assert len(data["standings"]) == 1


class TestEnrichApplicant:
    """Tests for enriching applicant data."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return AuthenticatedESIClient("token", 12345)

    @pytest.fixture
    def applicant(self):
        """Create a test applicant."""
        return Applicant(
            character_id=12345,
            character_name="Test Pilot",
            corporation_id=98000001,
            corporation_name="Test Corp",
        )

    @pytest.mark.asyncio
    async def test_enrich_adds_wallet_data(self, client, applicant):
        """Test that enrich adds wallet journal entries."""
        from backend.models.applicant import WalletEntry

        wallet_entries = [
            WalletEntry(
                id=1,
                date=datetime.now(UTC),
                ref_type="player_donation",
                amount=1000000,
            ),
        ]

        with patch.object(client, "build_wallet_entries", return_value=wallet_entries):
            with patch.object(client, "build_asset_summary", side_effect=Exception("skip")):
                with patch.object(client, "build_standings_data", side_effect=Exception("skip")):
                    result = await client.enrich_applicant(applicant)

        assert len(result.wallet_journal) == 1
        assert result.wallet_journal[0].ref_type == "player_donation"

    @pytest.mark.asyncio
    async def test_enrich_adds_asset_data(self, client, applicant):
        """Test that enrich adds asset summary."""
        from backend.models.applicant import AssetSummary

        assets = AssetSummary(
            capital_ships=["TypeID:23757"],
            supercapitals=["TypeID:23919"],
        )

        with patch.object(client, "build_wallet_entries", side_effect=Exception("skip")):
            with patch.object(client, "build_asset_summary", return_value=assets):
                with patch.object(client, "build_standings_data", side_effect=Exception("skip")):
                    result = await client.enrich_applicant(applicant)

        assert result.assets is not None
        assert "TypeID:23757" in result.assets.capital_ships

    @pytest.mark.asyncio
    async def test_enrich_adds_standings_data(self, client, applicant):
        """Test that enrich adds standings data."""
        standings = {"contacts": [], "standings": []}

        with patch.object(client, "build_wallet_entries", side_effect=Exception("skip")):
            with patch.object(client, "build_asset_summary", side_effect=Exception("skip")):
                with patch.object(client, "build_standings_data", return_value=standings):
                    result = await client.enrich_applicant(applicant)

        assert result.standings_data is not None

    @pytest.mark.asyncio
    async def test_enrich_adds_data_source(self, client, applicant):
        """Test that enrich adds esi_auth to data sources."""
        with patch.object(client, "build_wallet_entries", side_effect=Exception("skip")):
            with patch.object(client, "build_asset_summary", side_effect=Exception("skip")):
                with patch.object(client, "build_standings_data", side_effect=Exception("skip")):
                    result = await client.enrich_applicant(applicant)

        assert "esi_auth" in result.data_sources

    @pytest.mark.asyncio
    async def test_enrich_handles_all_failures_gracefully(self, client, applicant):
        """Test that enrich completes even if all fetches fail."""
        with patch.object(client, "build_wallet_entries", side_effect=Exception("fail")):
            with patch.object(client, "build_asset_summary", side_effect=Exception("fail")):
                with patch.object(client, "build_standings_data", side_effect=Exception("fail")):
                    result = await client.enrich_applicant(applicant)

        # Should still return the applicant
        assert result.character_id == 12345
        assert "esi_auth" in result.data_sources
