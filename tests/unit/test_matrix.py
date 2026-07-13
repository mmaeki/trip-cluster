"""Unit tests for the travel-time matrix module."""

from __future__ import annotations

from datetime import date, time
from unittest.mock import MagicMock, patch

import pytest

from trip_cluster.cache.sqlite import SQLiteCache
from trip_cluster.exceptions import MatrixError
from trip_cluster.matrix.haversine import HaversineMatrixProvider
from trip_cluster.matrix.service import MatrixService, format_departure_bucket
from trip_cluster.matrix.tomtom import TomTomMatrixProvider, _parse_matrix_response
from trip_cluster.models import GeocodedPlace, Place


def _geocoded(
    name: str, line: int, lat: float, lng: float, fixed: time | None = None
) -> GeocodedPlace:
    return GeocodedPlace(
        place=Place(raw_name=name, fixed_time=fixed, line_number=line),
        lat=lat,
        lng=lng,
        formatted_address=name,
    )


GOLDEN_GATE = _geocoded("Golden Gate Park", 1, 37.7694, -122.4862)
LANDS_END = _geocoded("Lands End", 2, 37.784, -122.507)
MT_TAM = _geocoded("Mt. Tam", 3, 37.9235, -122.5965, fixed=time(6, 0))


@pytest.fixture
def cache() -> SQLiteCache:
    with SQLiteCache(":memory:") as memory_cache:
        yield memory_cache


class TestFormatDepartureBucket:
    def test_formats_datetime_bucket(self) -> None:
        assert format_departure_bucket(date(2026, 7, 15), time(9, 0)) == "2026-07-15T09:00"


class TestTomTomParse:
    def test_partial_cells_do_not_raise(self) -> None:
        data = {
            "data": [
                {
                    "originIndex": 0,
                    "destinationIndex": 1,
                    "routeSummary": {"travelTimeInSeconds": 600},
                },
                {
                    "originIndex": 0,
                    "destinationIndex": 2,
                    "detailedError": {"code": "NO_ROUTE_FOUND"},
                },
            ]
        }
        matrix = _parse_matrix_response(data, 3)
        assert matrix[0][1] == 600.0
        assert matrix[0][2] is None


class TestMatrixService:
    def test_uses_cache_on_second_call(self, cache: SQLiteCache) -> None:
        calls = 0

        class CountingProvider(HaversineMatrixProvider):
            def get_durations(self, coordinates, *, trip_date, depart_at):
                nonlocal calls
                calls += 1
                return super().get_durations(
                    coordinates, trip_date=trip_date, depart_at=depart_at
                )

        mock_osrm = MagicMock()
        mock_osrm.get_durations.side_effect = MatrixError("skip osrm")

        service = MatrixService(
            cache,
            use_traffic=False,
            tomtom=TomTomMatrixProvider(api_key=None),
            osrm=mock_osrm,
            haversine=CountingProvider(),
        )
        places = [GOLDEN_GATE, LANDS_END]
        trip = date(2026, 7, 15)

        first = service.build_matrix(places, trip_date=trip, day_start=time(9, 0))
        second = service.build_matrix(places, trip_date=trip, day_start=time(9, 0))

        assert calls == 1
        assert first.primary_source == "haversine"
        assert second.primary_source == "cache"
        assert first.durations == second.durations

    def test_fills_tomtom_gaps_with_osrm(self, cache: SQLiteCache) -> None:
        mock_tomtom = MagicMock()
        mock_tomtom.is_available.return_value = True
        mock_tomtom.get_durations.return_value = [
            [0.0, 100.0],
            [None, 0.0],
        ]

        mock_osrm = MagicMock()
        mock_osrm.get_pair_duration.return_value = 250.0

        service = MatrixService(
            cache,
            use_traffic=True,
            tomtom=mock_tomtom,
            osrm=mock_osrm,
            haversine=MagicMock(),
        )
        result = service.build_matrix(
            [GOLDEN_GATE, LANDS_END], trip_date=date(2026, 7, 15), day_start=time(9, 0)
        )

        assert result.durations[1][0] == 250.0
        mock_osrm.get_pair_duration.assert_called()

    def test_osrm_primary_by_default(self, cache: SQLiteCache) -> None:
        mock_tomtom = MagicMock()
        mock_tomtom.is_available.return_value = True
        mock_tomtom.get_durations.return_value = [[0.0, 999.0], [999.0, 0.0]]

        mock_osrm = MagicMock()
        mock_osrm.get_durations.return_value = [[0.0, 200.0], [220.0, 0.0]]

        service = MatrixService(
            cache,
            use_traffic=False,
            tomtom=mock_tomtom,
            osrm=mock_osrm,
            haversine=MagicMock(),
        )
        result = service.build_matrix(
            [GOLDEN_GATE, LANDS_END], trip_date=date(2026, 7, 15), day_start=time(9, 0)
        )

        assert result.primary_source == "osrm"
        assert result.durations[0][1] == 200.0
        mock_tomtom.get_durations.assert_not_called()

    def test_traffic_mode_falls_back_to_osrm_when_tomtom_fails(self, cache: SQLiteCache) -> None:
        mock_tomtom = MagicMock()
        mock_tomtom.is_available.return_value = True
        mock_tomtom.get_durations.side_effect = MatrixError("tomtom down")

        mock_osrm = MagicMock()
        mock_osrm.get_durations.return_value = [[0.0, 200.0], [220.0, 0.0]]

        service = MatrixService(
            cache,
            use_traffic=True,
            tomtom=mock_tomtom,
            osrm=mock_osrm,
            haversine=MagicMock(),
        )
        result = service.build_matrix(
            [GOLDEN_GATE, LANDS_END], trip_date=date(2026, 7, 15), day_start=time(9, 0)
        )

        assert result.primary_source == "osrm"
        assert result.durations[0][1] == 200.0

    def test_symmetrized_matrix(self, cache: SQLiteCache) -> None:
        mock_tomtom = MagicMock()
        mock_tomtom.is_available.return_value = True
        mock_tomtom.get_durations.return_value = [[0.0, 100.0], [200.0, 0.0]]

        service = MatrixService(
            cache,
            use_traffic=True,
            tomtom=mock_tomtom,
            osrm=MagicMock(),
            haversine=MagicMock(),
        )
        matrix = service.build_matrix(
            [GOLDEN_GATE, LANDS_END], trip_date=date(2026, 7, 15), day_start=time(9, 0)
        )

        sym = matrix.symmetrized()
        assert sym[0][1] == sym[1][0] == 150.0

    def test_tagged_place_triggers_partial_override(self, cache: SQLiteCache) -> None:
        mock_tomtom = MagicMock()
        mock_tomtom.is_available.return_value = True
        mock_tomtom.get_durations.return_value = [
            [0.0, 100.0, 300.0],
            [110.0, 0.0, 320.0],
            [310.0, 330.0, 0.0],
        ]
        mock_tomtom.get_durations_partial.return_value = [[999.0]]

        service = MatrixService(
            cache,
            use_traffic=True,
            tomtom=mock_tomtom,
            osrm=MagicMock(),
            haversine=MagicMock(),
        )
        service.build_matrix(
            [GOLDEN_GATE, LANDS_END, MT_TAM],
            trip_date=date(2026, 7, 15),
            day_start=time(9, 0),
        )

        assert mock_tomtom.get_durations_partial.call_count >= 1

    def test_tagged_override_uses_osrm_without_traffic_mode(self, cache: SQLiteCache) -> None:
        mock_tomtom = MagicMock()
        mock_tomtom.is_available.return_value = True

        mock_osrm = MagicMock()
        mock_osrm.get_durations.return_value = [
            [0.0, 100.0, 300.0],
            [110.0, 0.0, 320.0],
            [310.0, 330.0, 0.0],
        ]

        service = MatrixService(
            cache,
            use_traffic=False,
            tomtom=mock_tomtom,
            osrm=mock_osrm,
            haversine=MagicMock(),
        )
        service.build_matrix(
            [GOLDEN_GATE, LANDS_END, MT_TAM],
            trip_date=date(2026, 7, 15),
            day_start=time(9, 0),
        )

        mock_tomtom.get_durations.assert_not_called()
        mock_tomtom.get_durations_partial.assert_not_called()
        assert mock_osrm.get_durations.call_count >= 2

    def test_single_place_matrix(self, cache: SQLiteCache) -> None:
        service = MatrixService(cache)
        result = service.build_matrix([GOLDEN_GATE], trip_date=date(2026, 7, 15))
        assert result.durations == [[0.0]]
        assert result.size == 1


class TestTomTomClient:
    TOMTOM_RESPONSE = {
        "data": [
            {
                "originIndex": 0,
                "destinationIndex": 1,
                "routeSummary": {"travelTimeInSeconds": 500},
            }
        ]
    }

    def test_posts_matrix_request(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = self.TOMTOM_RESPONSE

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("trip_cluster.matrix.tomtom.httpx.Client", return_value=mock_client):
            provider = TomTomMatrixProvider(api_key="test-key")
            matrix = provider.get_durations(
                [(37.77, -122.42), (37.78, -122.50)],
                trip_date=date(2026, 7, 15),
                depart_at=time(9, 0),
            )

        assert matrix[0][1] == 500.0
        mock_client.post.assert_called_once()


class TestDotenv:
    def test_get_tomtom_api_key_reads_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TOMTOM_API_KEY", "test-key-from-env")
        from trip_cluster.config import get_tomtom_api_key

        assert get_tomtom_api_key() == "test-key-from-env"

    def test_placeholder_key_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TOMTOM_API_KEY", "your_key_here")
        from trip_cluster.config import get_tomtom_api_key

        assert get_tomtom_api_key() is None

    def test_traffic_routing_disabled_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TRIPCLUSTER_USE_TRAFFIC", raising=False)
        from trip_cluster.config import is_traffic_routing_enabled

        assert is_traffic_routing_enabled() is False

    def test_traffic_routing_enabled_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIPCLUSTER_USE_TRAFFIC", "true")
        from trip_cluster.config import is_traffic_routing_enabled

        assert is_traffic_routing_enabled() is True
