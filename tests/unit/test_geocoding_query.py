"""Unit tests for geocoding query helpers."""

from __future__ import annotations

from trip_cluster.geocoding.aliases import expand_place_alias
from trip_cluster.geocoding.base import GeocodeCandidate
from trip_cluster.geocoding.query import build_fallback_queries, pick_best_candidate


class TestExpandPlaceAlias:
    def test_expands_mt_tam(self) -> None:
        assert expand_place_alias("Mt. Tam") == "Mount Tamalpais"

    def test_expands_del_mar_fairgrounds(self) -> None:
        assert expand_place_alias("Del Mar Fairgrounds") == "San Diego County Fairgrounds"


class TestBuildFallbackQueries:
    def test_includes_state_level_query(self) -> None:
        queries = build_fallback_queries("Mt. Tam", "San Francisco, CA")
        assert "Mt. Tam, CA" in queries
        assert "Mount Tamalpais, California" in queries

    def test_includes_del_mar_disambiguation(self) -> None:
        queries = build_fallback_queries("Del Mar Fairgrounds", "San Diego, CA")
        assert "San Diego County Fairgrounds, Del Mar, California" in queries


class TestPickBestCandidate:
    def test_prefers_candidate_near_anchor_points(self) -> None:
        candidates = [
            GeocodeCandidate(-24.75, 150.24, "Australia", None, 0.9),
            GeocodeCandidate(37.89, -122.61, "California, USA", None, 0.5),
        ]
        anchors = [(37.77, -122.48), (37.78, -122.51)]

        best = pick_best_candidate(candidates, region="San Francisco, CA", anchor_points=anchors)

        assert "California" in best.formatted_address

    def test_rejects_orange_county_fair_when_trip_is_in_san_diego(self) -> None:
        candidates = [
            GeocodeCandidate(33.662, -117.904, "Costa Mesa, Orange County, CA", None, 0.9),
            GeocodeCandidate(32.976, -117.262, "Del Mar, San Diego County, CA", None, 0.5),
        ]
        anchors = [
            (32.832, -117.272),  # Windansea
            (32.848, -117.274),  # il giardino di lilli
            (32.896, -117.185),  # OMOMO
            (32.715, -117.161),  # An's Hatmakers
        ]

        best = pick_best_candidate(candidates, region="San Diego, CA", anchor_points=anchors)

        assert "Del Mar" in best.formatted_address
