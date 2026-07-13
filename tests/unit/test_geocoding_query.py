"""Unit tests for geocoding query helpers."""

from __future__ import annotations

from trip_cluster.geocoding.aliases import expand_place_alias
from trip_cluster.geocoding.base import GeocodeCandidate
from trip_cluster.geocoding.query import build_fallback_queries, pick_best_candidate


class TestExpandPlaceAlias:
    def test_expands_mt_tam(self) -> None:
        assert expand_place_alias("Mt. Tam") == "Mount Tamalpais"


class TestBuildFallbackQueries:
    def test_includes_state_level_query(self) -> None:
        queries = build_fallback_queries("Mt. Tam", "San Francisco, CA")
        assert "Mt. Tam, CA" in queries
        assert "Mount Tamalpais, California" in queries


class TestPickBestCandidate:
    def test_prefers_candidate_near_anchor_points(self) -> None:
        candidates = [
            GeocodeCandidate(-24.75, 150.24, "Australia", None, 0.9),
            GeocodeCandidate(37.89, -122.61, "California, USA", None, 0.5),
        ]
        anchors = [(37.77, -122.48), (37.78, -122.51)]

        best = pick_best_candidate(candidates, region="San Francisco, CA", anchor_points=anchors)

        assert "California" in best.formatted_address
