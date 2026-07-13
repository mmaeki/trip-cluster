"""Unit tests for haversine distance and duration estimates."""

from __future__ import annotations

from datetime import date, time

from trip_cluster.matrix.haversine import (
    HaversineMatrixProvider,
    estimate_duration_seconds,
    haversine_km,
    partial_durations,
)


class TestHaversineKm:
    def test_same_point_is_zero(self) -> None:
        assert haversine_km(37.77, -122.42, 37.77, -122.42) == 0.0

    def test_known_distance_is_reasonable(self) -> None:
        km = haversine_km(37.7694, -122.4862, 37.784, -122.507)
        assert 1.5 < km < 3.5


class TestEstimateDuration:
    def test_same_point_is_zero(self) -> None:
        assert estimate_duration_seconds(1.0, 2.0, 1.0, 2.0) == 0.0

    def test_scales_with_distance(self) -> None:
        short = estimate_duration_seconds(37.0, -122.0, 37.01, -122.0)
        long = estimate_duration_seconds(37.0, -122.0, 37.1, -122.0)
        assert long > short


class TestHaversineMatrixProvider:
    def test_single_place(self) -> None:
        provider = HaversineMatrixProvider()
        matrix = provider.get_durations(
            [(37.77, -122.42)], trip_date=date(2026, 7, 15), depart_at=time(9, 0)
        )
        assert matrix == [[0.0]]

    def test_diagonal_is_zero(self) -> None:
        coords = [(37.77, -122.42), (37.78, -122.50)]
        matrix = HaversineMatrixProvider().get_durations(
            coords, trip_date=date(2026, 7, 15), depart_at=time(9, 0)
        )
        assert matrix[0][0] == 0.0
        assert matrix[1][1] == 0.0
        assert matrix[0][1] > 0


class TestPartialDurations:
    def test_shape(self) -> None:
        origins = [(37.77, -122.42)]
        dests = [(37.78, -122.50), (37.79, -122.51)]
        matrix = partial_durations(origins, dests)
        assert len(matrix) == 1
        assert len(matrix[0]) == 2
