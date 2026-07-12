"""Unit tests for the SQLite cache layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from trip_cluster.cache.sqlite import SQLiteCache


@pytest.fixture
def cache() -> SQLiteCache:
    with SQLiteCache(":memory:") as memory_cache:
        yield memory_cache


class TestGeocodeCache:
    def test_miss_returns_none(self, cache: SQLiteCache) -> None:
        assert cache.get_geocode("Golden Gate Park", "Bay Area, CA") is None

    def test_set_then_get(self, cache: SQLiteCache) -> None:
        cache.set_geocode(
            "Golden Gate Park",
            "Bay Area, CA",
            lat=37.7694,
            lng=-122.4862,
            formatted_address="Golden Gate Park, San Francisco, CA",
            osm_id="relation/1234",
        )

        hit = cache.get_geocode("Golden Gate Park", "Bay Area, CA")

        assert hit is not None
        assert hit.lat == 37.7694
        assert hit.lng == -122.4862
        assert hit.formatted_address == "Golden Gate Park, San Francisco, CA"
        assert hit.osm_id == "relation/1234"
        assert hit.fetched_at  # timestamp recorded

    def test_key_is_case_and_whitespace_insensitive(self, cache: SQLiteCache) -> None:
        cache.set_geocode(
            "Golden Gate Park", "Bay Area, CA", lat=1.0, lng=2.0, formatted_address="x"
        )

        assert cache.get_geocode("  golden gate park ", "bay area, ca") is not None

    def test_same_name_different_region_is_a_different_key(self, cache: SQLiteCache) -> None:
        cache.set_geocode(
            "Washington Park", "Portland, OR", lat=45.5, lng=-122.7, formatted_address="pdx"
        )

        assert cache.get_geocode("Washington Park", "Denver, CO") is None

    def test_none_region_is_its_own_key(self, cache: SQLiteCache) -> None:
        cache.set_geocode("Eiffel Tower", None, lat=48.858, lng=2.294, formatted_address="paris")

        assert cache.get_geocode("Eiffel Tower", None) is not None
        assert cache.get_geocode("Eiffel Tower", "Paris, France") is None

    def test_set_overwrites_existing_entry(self, cache: SQLiteCache) -> None:
        cache.set_geocode("Park", None, lat=1.0, lng=1.0, formatted_address="old")
        cache.set_geocode("Park", None, lat=2.0, lng=2.0, formatted_address="new")

        hit = cache.get_geocode("Park", None)
        assert hit is not None
        assert hit.lat == 2.0
        assert hit.formatted_address == "new"


class TestMatrixCache:
    def test_miss_returns_none(self, cache: SQLiteCache) -> None:
        assert cache.get_duration("a", "b", "2026-07-15T09:00") is None

    def test_set_then_get_single_edge(self, cache: SQLiteCache) -> None:
        cache.set_duration("a", "b", "2026-07-15T09:00", 720.0, source="tomtom")

        hit = cache.get_duration("a", "b", "2026-07-15T09:00")

        assert hit is not None
        assert hit.duration_seconds == 720.0
        assert hit.source == "tomtom"
        assert hit.fetched_at

    def test_edges_are_directional(self, cache: SQLiteCache) -> None:
        cache.set_duration("a", "b", "2026-07-15T09:00", 720.0, source="tomtom")

        assert cache.get_duration("b", "a", "2026-07-15T09:00") is None

    def test_departure_bucket_is_part_of_key(self, cache: SQLiteCache) -> None:
        cache.set_duration("a", "b", "2026-07-15T09:00", 720.0, source="tomtom")
        cache.set_duration("a", "b", "2026-07-15T17:00", 1500.0, source="tomtom")

        morning = cache.get_duration("a", "b", "2026-07-15T09:00")
        evening = cache.get_duration("a", "b", "2026-07-15T17:00")

        assert morning is not None and morning.duration_seconds == 720.0
        assert evening is not None and evening.duration_seconds == 1500.0

    def test_bulk_insert(self, cache: SQLiteCache) -> None:
        cache.set_durations(
            [
                ("a", "b", "2026-07-15T09:00", 100.0),
                ("b", "a", "2026-07-15T09:00", 130.0),
                ("a", "c", "2026-07-15T09:00", 200.0),
            ],
            source="osrm",
        )

        assert cache.get_duration("a", "b", "2026-07-15T09:00").duration_seconds == 100.0
        assert cache.get_duration("b", "a", "2026-07-15T09:00").duration_seconds == 130.0
        assert cache.get_duration("a", "c", "2026-07-15T09:00").source == "osrm"

    def test_set_overwrites_existing_edge(self, cache: SQLiteCache) -> None:
        cache.set_duration("a", "b", "2026-07-15T09:00", 100.0, source="haversine")
        cache.set_duration("a", "b", "2026-07-15T09:00", 90.0, source="tomtom")

        hit = cache.get_duration("a", "b", "2026-07-15T09:00")
        assert hit is not None
        assert hit.duration_seconds == 90.0
        assert hit.source == "tomtom"


class TestPersistence:
    def test_data_survives_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cache.db"

        with SQLiteCache(db_path) as cache:
            cache.set_geocode("Park", None, lat=1.0, lng=2.0, formatted_address="x")
            cache.set_duration("a", "b", "2026-07-15T09:00", 300.0, source="tomtom")

        with SQLiteCache(db_path) as reopened:
            assert reopened.get_geocode("Park", None) is not None
            assert reopened.get_duration("a", "b", "2026-07-15T09:00") is not None

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "deeply" / "nested" / "cache.db"

        with SQLiteCache(nested) as cache:
            cache.set_geocode("Park", None, lat=1.0, lng=2.0, formatted_address="x")

        assert nested.exists()
