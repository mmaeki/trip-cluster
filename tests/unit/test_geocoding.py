"""Unit tests for the geocoding module."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import httpx
import pytest

from trip_cluster.cache.sqlite import SQLiteCache
from trip_cluster.config import DEFAULT_USER_AGENT, validate_user_agent
from trip_cluster.exceptions import GeocodeError
from trip_cluster.geocoding.base import GeocodeCandidate
from trip_cluster.geocoding.nominatim import NominatimGeocoder
from trip_cluster.geocoding.service import GeocodingService, _build_query
from trip_cluster.models import Place


@dataclass
class FakeGeocoder:
    """In-memory geocoder for service-layer tests."""

    responses: dict[str, list[GeocodeCandidate]]
    calls: list[str] = field(default_factory=list)

    def search(self, query: str) -> list[GeocodeCandidate]:
        self.calls.append(query)
        return self.responses.get(query, [])


def _place(name: str, line_number: int = 1) -> Place:
    return Place(raw_name=name, fixed_time=None, line_number=line_number)


GOLDEN_GATE = GeocodeCandidate(
    lat=37.7694,
    lng=-122.4862,
    formatted_address="Golden Gate Park, San Francisco, CA",
    osm_id="way/123",
    importance=0.9,
)


@pytest.fixture
def cache() -> SQLiteCache:
    with SQLiteCache(":memory:") as memory_cache:
        yield memory_cache


class TestBuildQuery:
    def test_appends_region_when_present(self) -> None:
        assert _build_query("Golden Gate Park", "Bay Area, CA") == "Golden Gate Park, Bay Area, CA"

    def test_returns_name_only_without_region(self) -> None:
        assert _build_query("Eiffel Tower", None) == "Eiffel Tower"


class TestGeocodingService:
    def test_cache_hit_skips_geocoder(self, cache: SQLiteCache) -> None:
        cache.set_geocode(
            "Golden Gate Park",
            "Bay Area, CA",
            lat=37.7694,
            lng=-122.4862,
            formatted_address="cached address",
        )
        geocoder = FakeGeocoder(responses={})

        service = GeocodingService(cache, geocoder)
        result = service.geocode_all([_place("Golden Gate Park")], "Bay Area, CA")

        assert len(result.places) == 1
        assert result.places[0].formatted_address == "cached address"
        assert geocoder.calls == []

    def test_cache_miss_calls_geocoder_and_stores_result(self, cache: SQLiteCache) -> None:
        geocoder = FakeGeocoder(
            responses={"Golden Gate Park, Bay Area, CA": [GOLDEN_GATE]}
        )
        service = GeocodingService(cache, geocoder)

        result = service.geocode_all([_place("Golden Gate Park")], "Bay Area, CA")

        assert result.places[0].lat == GOLDEN_GATE.lat
        assert geocoder.calls == ["Golden Gate Park, Bay Area, CA"]

        cached = cache.get_geocode("Golden Gate Park", "Bay Area, CA")
        assert cached is not None
        assert cached.lat == GOLDEN_GATE.lat

    def test_zero_results_raises_by_default(self, cache: SQLiteCache) -> None:
        geocoder = FakeGeocoder(responses={"Nowhere, Bay Area, CA": []})
        service = GeocodingService(cache, geocoder)

        with pytest.raises(GeocodeError, match="No geocoding results"):
            service.geocode_all([_place("Nowhere")], "Bay Area, CA")

    def test_zero_results_skipped_with_skip_failures(self, cache: SQLiteCache) -> None:
        warnings: list[str] = []
        geocoder = FakeGeocoder(
            responses={
                "Golden Gate Park, Bay Area, CA": [GOLDEN_GATE],
                "Nowhere, Bay Area, CA": [],
            }
        )
        service = GeocodingService(cache, geocoder, on_warning=warnings.append)

        result = service.geocode_all(
            [_place("Golden Gate Park", 1), _place("Nowhere", 2)],
            "Bay Area, CA",
            skip_failures=True,
        )

        assert len(result.places) == 1
        assert result.places[0].place.raw_name == "Golden Gate Park"
        assert len(result.warnings) == 1
        assert "Nowhere" in result.warnings[0]

    def test_picks_highest_importance_candidate(self, cache: SQLiteCache) -> None:
        geocoder = FakeGeocoder(
            responses={
                "Washington Park, Bay Area, CA": [
                    GeocodeCandidate(45.5, -122.7, "Portland", "way/1", 0.4),
                    GeocodeCandidate(37.8, -122.45, "San Francisco", "way/2", 0.8),
                ]
            }
        )
        service = GeocodingService(cache, geocoder)

        result = service.geocode_all([_place("Washington Park")], "Bay Area, CA")

        assert "San Francisco" in result.places[0].formatted_address

    def test_warns_on_ambiguous_results(self, cache: SQLiteCache) -> None:
        warnings: list[str] = []
        geocoder = FakeGeocoder(
            responses={
                "Park, Bay Area, CA": [
                    GeocodeCandidate(1.0, 2.0, "Park A", "way/1", 1.0),
                    GeocodeCandidate(3.0, 4.0, "Park B", "way/2", 0.9),
                ]
            }
        )
        service = GeocodingService(cache, geocoder, on_warning=warnings.append)

        service.geocode_all([_place("Park")], "Bay Area, CA")

        assert len(warnings) == 1
        assert "Ambiguous geocode" in warnings[0]

    def test_retries_without_region_when_regional_query_returns_empty(
        self, cache: SQLiteCache
    ) -> None:
        warnings: list[str] = []
        geocoder = FakeGeocoder(
            responses={
                "Golden Gate Park, Bay Area, CA": [],
                "Golden Gate Park": [GOLDEN_GATE],
            }
        )
        service = GeocodingService(cache, geocoder, on_warning=warnings.append)

        result = service.geocode_all([_place("Golden Gate Park")], "Bay Area, CA")

        assert result.places[0].lat == GOLDEN_GATE.lat
        assert geocoder.calls == ["Golden Gate Park, Bay Area, CA", "Golden Gate Park"]
        assert any("retrying without region" in w for w in warnings)

    def test_respects_rate_limit_between_api_calls(self, cache: SQLiteCache) -> None:
        geocoder = FakeGeocoder(
            responses={
                "A, Bay Area, CA": [
                    GeocodeCandidate(1.0, 1.0, "A", None, 1.0),
                ],
                "B, Bay Area, CA": [
                    GeocodeCandidate(2.0, 2.0, "B", None, 1.0),
                ],
            }
        )
        service = GeocodingService(cache, geocoder, request_interval_seconds=0.05)

        with patch("trip_cluster.geocoding.service.time.sleep") as mock_sleep:
            service.geocode_all(
                [_place("A", 1), _place("B", 2)],
                "Bay Area, CA",
            )

        assert mock_sleep.call_count == 1


class TestUserAgentValidation:
    def test_rejects_placeholder_email(self) -> None:
        message = validate_user_agent("TripCluster/0.1.0 (your-email@example.com)")
        assert message is not None
        assert "placeholder" in message.lower()

    def test_accepts_realistic_user_agent(self) -> None:
        assert validate_user_agent("TripCluster/0.1.0 (personal trip planning tool)") is None


class TestNominatimGeocoder:
    NOMINATIM_RESPONSE = [
        {
            "lat": "37.7694",
            "lon": "-122.4862",
            "display_name": "Golden Gate Park, San Francisco, CA",
            "importance": 0.9,
            "osm_type": "way",
            "osm_id": 123,
        }
    ]

    def test_get_user_agent_falls_back_on_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "NOMINATIM_USER_AGENT", "TripCluster/0.1.0 (your-email@example.com)"
        )
        from trip_cluster.config import get_user_agent

        assert get_user_agent() == DEFAULT_USER_AGENT

    def test_raises_when_placeholder_passed_explicitly(self) -> None:
        with pytest.raises(GeocodeError, match="placeholder email"):
            NominatimGeocoder(user_agent="TripCluster/0.1.0 (your-email@example.com)")

    def test_uses_default_when_env_has_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "NOMINATIM_USER_AGENT", "TripCluster/0.1.0 (your-email@example.com)"
        )
        geocoder = NominatimGeocoder()
        assert geocoder._user_agent == DEFAULT_USER_AGENT

    def test_parses_successful_response(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = self.NOMINATIM_RESPONSE

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("trip_cluster.geocoding.nominatim.httpx.Client", return_value=mock_client):
            geocoder = NominatimGeocoder(user_agent="test-agent")
            results = geocoder.search("Golden Gate Park")

        assert len(results) == 1
        assert results[0].lat == 37.7694
        assert results[0].osm_id == "way/123"
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["params"]["q"] == "Golden Gate Park"

    def test_retries_on_timeout(self) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [
            httpx.TimeoutException("timeout"),
            MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value=self.NOMINATIM_RESPONSE),
            ),
        ]

        with (
            patch("trip_cluster.geocoding.nominatim.httpx.Client", return_value=mock_client),
            patch("trip_cluster.geocoding.nominatim.time.sleep"),
        ):
            geocoder = NominatimGeocoder(user_agent="test-agent", max_retries=3)
            results = geocoder.search("Golden Gate Park")

        assert len(results) == 1
        assert mock_client.get.call_count == 2

    def test_raises_after_exhausted_retries(self) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        with (
            patch("trip_cluster.geocoding.nominatim.httpx.Client", return_value=mock_client),
            patch("trip_cluster.geocoding.nominatim.time.sleep"),
            pytest.raises(GeocodeError, match="after 3 attempts"),
        ):
            NominatimGeocoder(user_agent="test-agent", max_retries=3).search("Nowhere")
