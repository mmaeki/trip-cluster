"""Shared helpers for itinerary output formatting."""

from __future__ import annotations

from datetime import time

from trip_cluster.models import DayPlan, GeocodedPlace


def place_id_to_index(places: list[GeocodedPlace]) -> dict[str, int]:
    return {place.place_id: index for index, place in enumerate(places)}


def global_route_for_day(
    plan: DayPlan,
    all_places: list[GeocodedPlace],
) -> list[int]:
    """Map a day plan's local visit order to global place indices."""
    lookup = place_id_to_index(all_places)
    return [lookup[plan.places[local_index].place_id] for local_index in plan.route_order]


def format_clock_time(seconds: float) -> str:
    """Format seconds-from-midnight as HH:MM."""
    total_minutes = int(round(seconds / 60))
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def format_time_value(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")
