"""Haversine straight-line distance with assumed driving speed."""

from __future__ import annotations

import math
from datetime import date, time

from trip_cluster.config import ASSUMED_SPEED_KPH


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in kilometers."""
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_duration_seconds(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Convert straight-line distance to seconds using assumed urban speed."""
    if lat1 == lat2 and lng1 == lng2:
        return 0.0
    distance_km = haversine_km(lat1, lng1, lat2, lng2)
    hours = distance_km / ASSUMED_SPEED_KPH
    return hours * 3600.0


class HaversineMatrixProvider:
    """Fallback matrix using straight-line distance / assumed speed."""

    @property
    def source_name(self) -> str:
        return "haversine"

    def get_durations(
        self,
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time,
    ) -> list[list[float]]:
        del trip_date, depart_at
        n = len(coordinates)
        matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            lat1, lng1 = coordinates[i]
            for j in range(n):
                if i == j:
                    continue
                lat2, lng2 = coordinates[j]
                matrix[i][j] = estimate_duration_seconds(lat1, lng1, lat2, lng2)
        return matrix


def partial_durations(
    origin_coords: list[tuple[float, float]],
    dest_coords: list[tuple[float, float]],
) -> list[list[float]]:
    """Build an |origins| x |destinations| matrix via haversine estimates."""
    return [
        [
            estimate_duration_seconds(lat1, lng1, lat2, lng2)
            for lat2, lng2 in dest_coords
        ]
        for lat1, lng1 in origin_coords
    ]
