"""Per-day open-path TSP ordering with nearest-neighbor, 2-opt, and timed anchors."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import time

from trip_cluster.config import (
    DEFAULT_DAY_START,
    TIME_DEVIATION_PENALTY_LAMBDA,
    TIME_DEVIATION_TARGET_SECONDS,
    TIME_REFINEMENT_MAX_SWAPS,
    TWO_OPT_MAX_ITERATIONS,
)
from trip_cluster.models import ClusterResult, DayPlan, GeocodedPlace, TravelTimeMatrix


class RouteOrderer:
    """Order places within each day cluster for minimum driving time."""

    def __init__(
        self,
        *,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._on_warning = on_warning if on_warning is not None else _default_warning_handler

    def build_day_plans(
        self,
        places: list[GeocodedPlace],
        cluster: ClusterResult,
        matrix: TravelTimeMatrix,
        *,
        day_start: time = DEFAULT_DAY_START,
    ) -> list[DayPlan]:
        return build_day_plans(
            places,
            cluster,
            matrix,
            day_start=day_start,
            on_warning=self._on_warning,
        )


def build_day_plans(
    places: list[GeocodedPlace],
    cluster: ClusterResult,
    matrix: TravelTimeMatrix,
    *,
    day_start: time = DEFAULT_DAY_START,
    on_warning: Callable[[str], None] | None = None,
) -> list[DayPlan]:
    """Build ordered day plans from clustering output and an asymmetric matrix."""
    warn = on_warning if on_warning is not None else _default_warning_handler
    warn_for_tags_before_day_start(places, day_start=day_start, on_warning=warn)

    day_plans: list[DayPlan] = []
    for day_number, global_indices in enumerate(cluster.day_assignments, start=1):
        if not global_indices:
            continue
        route_order, travel_seconds = order_day_route(
            global_indices,
            matrix,
            places,
            day_start=day_start,
        )
        local_places = [places[index] for index in sorted(global_indices)]
        day_plans.append(
            DayPlan(
                day=day_number,
                places=local_places,
                total_travel_seconds=travel_seconds,
                route_order=route_order,
            )
        )
    return day_plans


def warn_for_tags_before_day_start(
    places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
    on_warning: Callable[[str], None] | None = None,
) -> list[str]:
    """Warn when a requested visit time is earlier than itinerary start."""
    warn = on_warning if on_warning is not None else _default_warning_handler
    warnings: list[str] = []
    for place in places:
        fixed_time = place.place.fixed_time
        if fixed_time is None or fixed_time >= day_start:
            continue
        message = (
            f'"{place.place.raw_name}" is tagged for {fixed_time.strftime("%H:%M")}, '
            f'before --day-start {day_start.strftime("%H:%M")}; '
            f"set --day-start to {fixed_time.strftime('%H:%M')} or earlier "
            "to make that arrival possible."
        )
        warnings.append(message)
        warn(message)
    return warnings


def order_day_route(
    global_indices: list[int],
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
) -> tuple[list[int], int]:
    """Return local route permutation and total driving seconds for one day."""
    if not global_indices:
        return [], 0
    if len(global_indices) == 1:
        return [0], 0

    local_indices = sorted(global_indices)
    global_to_local = {
        global_index: local_index
        for local_index, global_index in enumerate(local_indices)
    }

    global_route = _order_global_route(global_indices, matrix, places)
    if _has_timed_places(global_indices, places):
        global_route = _refine_timed_route(global_route, matrix, places, day_start=day_start)

    local_route = [global_to_local[global_index] for global_index in global_route]
    travel_seconds = _route_travel_seconds(global_route, matrix)
    return local_route, travel_seconds


def _order_global_route(
    global_indices: list[int],
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
) -> list[int]:
    timed = [
        (index, places[index].place.fixed_time)
        for index in global_indices
        if places[index].place.fixed_time is not None
    ]
    if not timed:
        start = _medoid(global_indices, matrix)
        route = _nearest_neighbor(global_indices, matrix, start=start)
        return _two_opt(route, matrix)

    timed.sort(key=lambda item: item[1])
    anchor_indices = [index for index, _ in timed]
    untimed = [index for index in global_indices if index not in anchor_indices]
    segments = _partition_untimed_by_anchors(untimed, anchor_indices, matrix)

    route: list[int] = []
    if segments[0]:
        route.extend(_order_segment(segments[0], matrix, start=_medoid(segments[0], matrix)))
    for anchor_position, anchor in enumerate(anchor_indices):
        route.append(anchor)
        middle = segments[anchor_position + 1]
        if middle:
            route.extend(
                _order_segment(
                    middle,
                    matrix,
                    start=_closest_to_anchor(middle, anchor, matrix),
                )
            )
    if segments[len(anchor_indices)]:
        route.extend(
            _order_segment(
                segments[len(anchor_indices)],
                matrix,
                start=_closest_to_anchor(segments[len(anchor_indices)], anchor_indices[-1], matrix),
            )
        )
    return route


def _order_segment(
    indices: list[int],
    matrix: TravelTimeMatrix,
    *,
    start: int,
) -> list[int]:
    route = _nearest_neighbor(indices, matrix, start=start)
    return _two_opt(route, matrix)


def _has_timed_places(global_indices: list[int], places: list[GeocodedPlace]) -> bool:
    return any(places[index].place.fixed_time is not None for index in global_indices)


def _partition_untimed_by_anchors(
    untimed: list[int],
    anchor_indices: list[int],
    matrix: TravelTimeMatrix,
) -> list[list[int]]:
    segment_count = len(anchor_indices) + 1
    segments: list[list[int]] = [[] for _ in range(segment_count)]
    for place_index in untimed:
        segment_index = _best_segment_for_untimed(place_index, anchor_indices, matrix)
        segments[segment_index].append(place_index)
    return segments


def _best_segment_for_untimed(
    place_index: int,
    anchor_indices: list[int],
    matrix: TravelTimeMatrix,
) -> int:
    best_segment = 0
    best_distance = float("inf")
    for segment_index in range(len(anchor_indices) + 1):
        distance = _segment_attachment_distance(
            place_index,
            segment_index,
            anchor_indices,
            matrix,
        )
        if distance < best_distance:
            best_distance = distance
            best_segment = segment_index
    return best_segment


def _segment_attachment_distance(
    place_index: int,
    segment_index: int,
    anchor_indices: list[int],
    matrix: TravelTimeMatrix,
) -> float:
    if segment_index == 0:
        return matrix.durations[place_index][anchor_indices[0]]
    if segment_index == len(anchor_indices):
        return matrix.durations[place_index][anchor_indices[-1]]
    left = anchor_indices[segment_index - 1]
    right = anchor_indices[segment_index]
    return min(
        matrix.durations[place_index][left],
        matrix.durations[place_index][right],
    )


def _nearest_neighbor(
    indices: list[int],
    matrix: TravelTimeMatrix,
    *,
    start: int,
) -> list[int]:
    remaining = set(indices)
    route = [start]
    remaining.remove(start)
    while remaining:
        current = route[-1]
        next_index = min(remaining, key=lambda candidate: matrix.durations[current][candidate])
        route.append(next_index)
        remaining.remove(next_index)
    return route


def _two_opt(route: list[int], matrix: TravelTimeMatrix) -> list[int]:
    if len(route) < 3:
        return route

    best = list(route)
    improved = True
    iterations = 0
    while improved and iterations < TWO_OPT_MAX_ITERATIONS:
        improved = False
        iterations += 1
        for i in range(len(best) - 2):
            for j in range(i + 2, len(best)):
                candidate = best[: i + 1] + list(reversed(best[i + 1 : j + 1])) + best[j + 1 :]
                if _route_travel_seconds(candidate, matrix) < _route_travel_seconds(best, matrix):
                    best = candidate
                    improved = True
    return best


def _medoid(indices: list[int], matrix: TravelTimeMatrix) -> int:
    return min(indices, key=lambda idx: _average_distance(idx, indices, matrix))


def _closest_to_anchor(indices: list[int], anchor: int, matrix: TravelTimeMatrix) -> int:
    return min(indices, key=lambda idx: matrix.durations[idx][anchor])


def _average_distance(place_index: int, members: list[int], matrix: TravelTimeMatrix) -> float:
    others = [member for member in members if member != place_index]
    if not others:
        return 0.0
    return sum(matrix.durations[place_index][other] for other in others) / len(others)


def _route_travel_seconds(route: list[int], matrix: TravelTimeMatrix) -> int:
    if len(route) < 2:
        return 0
    total = 0.0
    for left, right in zip(route, route[1:], strict=False):
        total += matrix.durations[left][right]
    return int(round(total))


def _refine_timed_route(
    route: list[int],
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
    *,
    day_start: time,
) -> list[int]:
    best = list(route)
    best_score = _timed_route_score(best, matrix, places, day_start=day_start)
    if (
        _max_time_deviation(best, matrix, places, day_start=day_start)
        <= TIME_DEVIATION_TARGET_SECONDS
    ):
        return best

    swaps = 0
    improved = True
    while improved and swaps < TIME_REFINEMENT_MAX_SWAPS:
        improved = False
        for i in range(len(best)):
            for j in range(i + 1, len(best)):
                candidate = list(best)
                candidate[i], candidate[j] = candidate[j], candidate[i]
                score = _timed_route_score(candidate, matrix, places, day_start=day_start)
                if score < best_score:
                    best = candidate
                    best_score = score
                    improved = True
                    swaps += 1
                    if swaps >= TIME_REFINEMENT_MAX_SWAPS:
                        break
            if swaps >= TIME_REFINEMENT_MAX_SWAPS:
                break
    return best


def _timed_route_score(
    route: list[int],
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
    *,
    day_start: time,
) -> float:
    travel = _route_travel_seconds(route, matrix)
    deviation = _total_time_deviation(route, matrix, places, day_start=day_start)
    return travel + TIME_DEVIATION_PENALTY_LAMBDA * deviation


def _total_time_deviation(
    route: list[int],
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
    *,
    day_start: time,
) -> float:
    arrivals = _simulate_arrivals(route, matrix, day_start=day_start)
    total = 0.0
    for index in route:
        tagged = places[index].place.fixed_time
        if tagged is None:
            continue
        total += abs(arrivals[index] - _time_to_seconds(tagged))
    return total


def _max_time_deviation(
    route: list[int],
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
    *,
    day_start: time,
) -> float:
    arrivals = _simulate_arrivals(route, matrix, day_start=day_start)
    deviations = [
        abs(arrivals[index] - _time_to_seconds(places[index].place.fixed_time))
        for index in route
        if places[index].place.fixed_time is not None
    ]
    return max(deviations, default=0.0)


def _simulate_arrivals(
    route: list[int],
    matrix: TravelTimeMatrix,
    *,
    day_start: time,
) -> dict[int, float]:
    if not route:
        return {}
    current = float(_time_to_seconds(day_start))
    arrivals = {route[0]: current}
    for previous, current_index in zip(route, route[1:], strict=False):
        current += matrix.durations[previous][current_index]
        arrivals[current_index] = current
    return arrivals


def _time_to_seconds(value: time) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def simulate_arrival_times(
    route: list[int],
    matrix: TravelTimeMatrix,
    *,
    day_start: time = DEFAULT_DAY_START,
) -> dict[int, float]:
    """Public helper for output formatting: global index -> arrival seconds."""
    return _simulate_arrivals(route, matrix, day_start=day_start)


def _default_warning_handler(message: str) -> None:
    print(message, file=sys.stderr)
