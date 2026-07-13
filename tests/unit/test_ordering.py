"""Unit tests for the route ordering module."""

from __future__ import annotations

from datetime import time

from trip_cluster.models import ClusterResult, GeocodedPlace, Place, TravelTimeMatrix
from trip_cluster.routing.ordering import (
    _nearest_neighbor,
    _route_travel_seconds,
    _two_opt,
    build_day_plans,
    order_day_route,
    warn_for_tags_before_day_start,
)


def _place(name: str, line: int, fixed: time | None = None) -> GeocodedPlace:
    return GeocodedPlace(
        place=Place(raw_name=name, fixed_time=fixed, line_number=line),
        lat=0.0,
        lng=0.0,
        formatted_address=name,
    )


def _matrix(durations: list[list[float]]) -> TravelTimeMatrix:
    n = len(durations)
    return TravelTimeMatrix(
        durations=durations,
        place_ids=[f"line_{index + 1}" for index in range(n)],
        primary_source="mock",
        departure_bucket="2026-07-15T09:00",
    )


class TestRouteHelpers:
    def test_two_opt_does_not_increase_travel_time(self) -> None:
        durations = [
            [0, 10, 50],
            [10, 0, 10],
            [50, 10, 0],
        ]
        matrix = _matrix(durations)
        initial = _nearest_neighbor([0, 1, 2], matrix, start=0)
        optimized = _two_opt(initial, matrix)
        assert _route_travel_seconds(optimized, matrix) <= _route_travel_seconds(initial, matrix)

    def test_open_path_travel_sum(self) -> None:
        matrix = _matrix(
            [
                [0, 100, 300],
                [120, 0, 50],
                [310, 60, 0],
            ]
        )
        assert _route_travel_seconds([0, 1, 2], matrix) == 150


class TestOrderDayRoute:
    def test_single_place_has_zero_travel(self) -> None:
        places = [_place("Only", 1)]
        matrix = _matrix([[0.0]])
        route, travel = order_day_route([0], matrix, places)
        assert route == [0]
        assert travel == 0

    def test_two_places_visits_both(self) -> None:
        places = [_place("A", 1), _place("B", 2)]
        matrix = _matrix([[0, 200], [220, 0]])
        route, travel = order_day_route([0, 1], matrix, places)
        assert sorted(route) == [0, 1]
        assert travel == 200

    def test_timed_anchors_keep_chronological_order(self) -> None:
        places = [
            _place("Breakfast", 1, fixed=time(8, 0)),
            _place("Museum", 2),
            _place("Dinner", 3, fixed=time(18, 0)),
            _place("Park", 4),
        ]
        matrix = _matrix(
            [
                [0, 100, 1000, 120],
                [110, 0, 900, 80],
                [1100, 920, 0, 950],
                [130, 90, 980, 0],
            ]
        )
        route, _ = order_day_route([0, 1, 2, 3], matrix, places, day_start=time(9, 0))
        assert route.index(0) < route.index(2)


class TestBuildDayPlans:
    def test_warns_when_tag_is_before_day_start(self) -> None:
        places = [
            _place("Mt. Tam", 1, fixed=time(6, 0)),
            _place("Lands End", 2, fixed=time(10, 0)),
        ]
        warnings: list[str] = []

        result = warn_for_tags_before_day_start(
            places,
            day_start=time(9, 0),
            on_warning=warnings.append,
        )

        assert result == warnings
        assert len(warnings) == 1
        assert '"Mt. Tam" is tagged for 06:00' in warnings[0]
        assert "before --day-start 09:00" in warnings[0]
        assert "set --day-start to 06:00 or earlier" in warnings[0]

    def test_build_day_plans_emits_early_tag_warning(self) -> None:
        places = [_place("Mt. Tam", 1, fixed=time(6, 0))]
        matrix = _matrix([[0.0]])
        cluster = ClusterResult(day_assignments=[[0]], num_days=1)
        warnings: list[str] = []

        build_day_plans(
            places,
            cluster,
            matrix,
            day_start=time(9, 0),
            on_warning=warnings.append,
        )

        assert len(warnings) == 1
        assert "before --day-start 09:00" in warnings[0]

    def test_builds_only_non_empty_days(self) -> None:
        places = [_place("A", 1), _place("B", 2), _place("C", 3)]
        matrix = _matrix(
            [
                [0, 100, 1000],
                [110, 0, 900],
                [1000, 910, 0],
            ]
        )
        cluster = ClusterResult(day_assignments=[[0, 1], [], [2]], num_days=3)
        day_plans = build_day_plans(places, cluster, matrix)

        assert len(day_plans) == 2
        assert day_plans[0].day == 1
        assert day_plans[1].day == 3
        assert len(day_plans[0].places) == 2
        assert day_plans[0].total_travel_seconds == 100

    def test_route_order_is_local_permutation(self) -> None:
        places = [_place("A", 1), _place("B", 2), _place("C", 3)]
        matrix = _matrix(
            [
                [0, 100, 1000],
                [110, 0, 900],
                [1000, 910, 0],
            ]
        )
        cluster = ClusterResult(day_assignments=[[0, 1, 2]], num_days=1)
        day_plans = build_day_plans(places, cluster, matrix)

        plan = day_plans[0]
        assert sorted(plan.route_order) == [0, 1, 2]
        assert len(plan.places) == 3

    def test_works_with_osrm_sourced_matrix(self) -> None:
        places = [_place("A", 1), _place("B", 2)]
        matrix = TravelTimeMatrix(
            durations=[[0, 480], [500, 0]],
            place_ids=["line_1", "line_2"],
            primary_source="osrm",
            departure_bucket="2026-07-15T09:00",
        )
        cluster = ClusterResult(day_assignments=[[0, 1]], num_days=1)
        day_plans = build_day_plans(places, cluster, matrix)

        assert day_plans[0].total_travel_seconds == 480
