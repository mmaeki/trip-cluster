"""Unit tests for the clustering module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trip_cluster.clustering import cluster_places, suggest_num_days
from trip_cluster.exceptions import ClusteringError
from trip_cluster.models import TravelTimeMatrix

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _matrix_from_fixture(name: str = "mock_matrix.json") -> TravelTimeMatrix:
    data = json.loads((FIXTURES / name).read_text())
    return TravelTimeMatrix(
        durations=data["durations"],
        place_ids=data["place_ids"],
        primary_source=data.get("source", "mock"),
        departure_bucket=data["departure_bucket"],
    )


def _assignment_sets(result) -> list[frozenset[int]]:
    return [frozenset(day) for day in result.day_assignments if day]


class TestSuggestNumDays:
    def test_zero_places_defaults_to_one_day(self) -> None:
        assert suggest_num_days(0) == 1

    def test_five_places_one_day(self) -> None:
        assert suggest_num_days(5) == 1

    def test_fourteen_places_three_days(self) -> None:
        assert suggest_num_days(14) == 3


class TestClusterPlaces:
    def test_groups_nearby_places_together(self) -> None:
        matrix = _matrix_from_fixture()
        result = cluster_places(matrix, days=2)

        assert result.num_days == 2
        assert sorted(sum(result.day_assignments, [])) == [0, 1, 2]
        assert _assignment_sets(result) == [frozenset({0, 1}), frozenset({2})]

    def test_auto_suggests_days_when_not_provided(self) -> None:
        matrix = _matrix_from_fixture()
        result = cluster_places(matrix)

        assert result.num_days == 1
        assert any("No --days given" in warning for warning in result.warnings)

    def test_more_days_than_places_leaves_empty_days(self) -> None:
        matrix = _matrix_from_fixture()
        result = cluster_places(matrix, days=5)

        assert result.num_days == 5
        assert len(result.day_assignments) == 5
        assert result.non_empty_days == 3
        assert sorted(sum(result.day_assignments, [])) == [0, 1, 2]
        assert result.day_assignments.count([]) == 2

    def test_single_place_single_day(self) -> None:
        matrix = TravelTimeMatrix(
            durations=[[0.0]],
            place_ids=["line_1"],
            primary_source="mock",
            departure_bucket="2026-07-15T09:00",
        )
        result = cluster_places(matrix, days=1)

        assert result.day_assignments == [[0]]

    def test_rejects_zero_places(self) -> None:
        matrix = TravelTimeMatrix(
            durations=[],
            place_ids=[],
            primary_source="mock",
            departure_bucket="2026-07-15T09:00",
        )
        with pytest.raises(ClusteringError, match="zero places"):
            cluster_places(matrix, days=1)

    def test_enforces_max_per_day_split(self) -> None:
        matrix = TravelTimeMatrix(
            durations=[
                [0, 100, 100, 1000],
                [100, 0, 100, 1000],
                [100, 100, 0, 1000],
                [1000, 1000, 1000, 0],
            ],
            place_ids=["a", "b", "c", "d"],
            primary_source="mock",
            departure_bucket="2026-07-15T09:00",
        )
        result = cluster_places(matrix, days=2, max_per_day=2)

        assert all(len(day) <= 2 for day in result.day_assignments)
        assert sorted(sum(result.day_assignments, [])) == [0, 1, 2, 3]

    def test_warns_when_max_per_day_is_impossible(self) -> None:
        matrix = _matrix_from_fixture()
        result = cluster_places(matrix, days=1, max_per_day=2)

        assert any("Cannot fit" in warning for warning in result.warnings)

    def test_works_with_osrm_sourced_matrix(self) -> None:
        matrix = _matrix_from_fixture()
        matrix = TravelTimeMatrix(
            durations=matrix.durations,
            place_ids=matrix.place_ids,
            primary_source="osrm",
            departure_bucket=matrix.departure_bucket,
        )
        result = cluster_places(matrix, days=2)

        assert result.num_days == 2
        assert sorted(sum(result.day_assignments, [])) == [0, 1, 2]
