"""Agglomerative clustering of places into daily groups."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from trip_cluster.config import DEFAULT_PLACES_PER_DAY
from trip_cluster.exceptions import ClusteringError
from trip_cluster.models import ClusterResult, TravelTimeMatrix

_MAX_SPLIT_ITERATIONS = 10_000


class Clusterer:
    """Partition places into day groups using matrix-based agglomerative clustering."""

    def __init__(
        self,
        *,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._on_warning = on_warning if on_warning is not None else _default_warning_handler

    def cluster(
        self,
        matrix: TravelTimeMatrix,
        *,
        days: int | None = None,
        max_per_day: int | None = None,
    ) -> ClusterResult:
        return cluster_places(
            matrix,
            days=days,
            max_per_day=max_per_day,
            on_warning=self._on_warning,
        )


def suggest_num_days(n_places: int) -> int:
    """Heuristic: assume ~DEFAULT_PLACES_PER_DAY attractions per day."""
    if n_places <= 0:
        return 1
    return max(1, math.ceil(n_places / DEFAULT_PLACES_PER_DAY))


def cluster_places(
    matrix: TravelTimeMatrix,
    *,
    days: int | None = None,
    max_per_day: int | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> ClusterResult:
    """Cluster places into day groups using a symmetrized travel-time matrix."""
    warn = on_warning if on_warning is not None else _default_warning_handler
    n = matrix.size
    warnings: list[str] = []

    if n == 0:
        raise ClusteringError("Cannot cluster zero places")

    effective_days = days if days is not None else suggest_num_days(n)
    if days is None:
        message = f"No --days given; using {effective_days} days for {n} places"
        warnings.append(message)
        warn(message)

    if effective_days < 1:
        raise ClusteringError("--days must be at least 1")

    if max_per_day is not None and max_per_day < 1:
        raise ClusteringError("--max-per-day must be at least 1")

    if max_per_day is not None and n > effective_days * max_per_day:
        message = (
            f"Cannot fit {n} places into {effective_days} days with "
            f"--max-per-day {max_per_day}"
        )
        warnings.append(message)
        warn(message)

    distance_matrix = matrix.symmetrized()
    day_assignments = _initial_partition(distance_matrix, num_days=effective_days)
    if n < effective_days:
        day_assignments = _normalize_day_slots(day_assignments, num_days=effective_days)

    if max_per_day is not None:
        day_assignments, split_warnings = _enforce_max_per_day(
            day_assignments,
            distance_matrix,
            max_per_day=max_per_day,
        )
        for message in split_warnings:
            warnings.append(message)
            warn(message)

    return ClusterResult(
        day_assignments=day_assignments,
        num_days=effective_days,
        warnings=warnings,
    )


def _initial_partition(
    distance_matrix: list[list[float]],
    *,
    num_days: int,
) -> list[list[int]]:
    n = len(distance_matrix)
    if n == 1:
        return [[0]]

    if n < num_days:
        return [[index] for index in range(n)]

    labels = AgglomerativeClustering(
        n_clusters=num_days,
        metric="precomputed",
        linkage="average",
    ).fit(np.asarray(distance_matrix, dtype=float)).labels_

    clusters: list[list[int]] = [[] for _ in range(num_days)]
    for index, label in enumerate(labels):
        clusters[int(label)].append(index)
    return clusters


def _normalize_day_slots(
    clusters: list[list[int]],
    *,
    num_days: int,
) -> list[list[int]]:
    """Return exactly num_days slots, padding with empty days when n < days."""
    non_empty = [sorted(day) for day in clusters if day]
    result: list[list[int]] = [[] for _ in range(num_days)]
    for day_index, members in enumerate(non_empty[:num_days]):
        result[day_index] = members
    return result


def _enforce_max_per_day(
    clusters: list[list[int]],
    distance_matrix: list[list[float]],
    *,
    max_per_day: int,
) -> tuple[list[list[int]], list[str]]:
    warnings: list[str] = []
    current = [list(day) for day in clusters]
    iterations = 0

    while iterations < _MAX_SPLIT_ITERATIONS:
        iterations += 1
        overloaded_index = _first_overloaded_cluster(current, max_per_day=max_per_day)
        if overloaded_index is None:
            return current, warnings

        overloaded = current[overloaded_index]
        medoid = _cluster_medoid(overloaded, distance_matrix)
        place_index = max(overloaded, key=lambda idx: distance_matrix[idx][medoid])
        target_index = _nearest_cluster_with_capacity(
            place_index,
            clusters=current,
            source_index=overloaded_index,
            distance_matrix=distance_matrix,
            max_per_day=max_per_day,
        )
        if target_index is None:
            message = (
                f"Could not enforce --max-per-day {max_per_day}; "
                f"day {overloaded_index + 1} still has {len(overloaded)} places"
            )
            if message not in warnings:
                warnings.append(message)
            return current, warnings

        current[overloaded_index].remove(place_index)
        current[target_index].append(place_index)

    warnings.append("Stopped --max-per-day enforcement after too many iterations")
    return current, warnings


def _first_overloaded_cluster(
    clusters: list[list[int]],
    *,
    max_per_day: int,
) -> int | None:
    for index, day in enumerate(clusters):
        if len(day) > max_per_day:
            return index
    return None


def _cluster_medoid(members: list[int], distance_matrix: list[list[float]]) -> int:
    return min(members, key=lambda idx: _average_distance(idx, members, distance_matrix))


def _average_distance(
    place_index: int,
    members: list[int],
    distance_matrix: list[list[float]],
) -> float:
    others = [member for member in members if member != place_index]
    if not others:
        return 0.0
    return sum(distance_matrix[place_index][other] for other in others) / len(others)


def _nearest_cluster_with_capacity(
    place_index: int,
    *,
    clusters: list[list[int]],
    source_index: int,
    distance_matrix: list[list[float]],
    max_per_day: int,
) -> int | None:
    candidates: list[tuple[float, int]] = []
    for cluster_index, members in enumerate(clusters):
        if cluster_index == source_index:
            continue
        if len(members) >= max_per_day:
            continue
        if not members:
            candidates.append((0.0, cluster_index))
            continue
        avg_distance = _average_distance(place_index, members, distance_matrix)
        candidates.append((avg_distance, cluster_index))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def _default_warning_handler(message: str) -> None:
    print(message, file=sys.stderr)
