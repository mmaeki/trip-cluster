"""JSON export for itineraries."""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path
from typing import Any

from trip_cluster.config import DEFAULT_DAY_START
from trip_cluster.models import GeocodedPlace, Itinerary, TravelTimeMatrix
from trip_cluster.output._helpers import format_clock_time, format_time_value, global_route_for_day
from trip_cluster.routing.ordering import simulate_arrival_times


def itinerary_to_dict(
    itinerary: Itinerary,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
) -> dict[str, Any]:
    """Convert an itinerary into a JSON-serializable dictionary."""
    return {
        "region": itinerary.region,
        "days": [
            _day_to_dict(day_plan, matrix, all_places, day_start=day_start)
            for day_plan in itinerary.days
        ],
        "warnings": list(itinerary.warnings),
        "matrix_source": itinerary.matrix_source,
    }


def itinerary_to_json(
    itinerary: Itinerary,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
    indent: int = 2,
) -> str:
    """Serialize an itinerary to a JSON string."""
    return json.dumps(
        itinerary_to_dict(
            itinerary,
            matrix,
            all_places,
            day_start=day_start,
        ),
        indent=indent,
    )


def write_itinerary_json(
    path: str | Path,
    itinerary: Itinerary,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
) -> None:
    """Write itinerary JSON to disk."""
    Path(path).write_text(
        itinerary_to_json(
            itinerary,
            matrix,
            all_places,
            day_start=day_start,
        ),
        encoding="utf-8",
    )


def _day_to_dict(
    day_plan,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time,
) -> dict[str, Any]:
    global_route = global_route_for_day(day_plan, all_places)
    arrivals = simulate_arrival_times(global_route, matrix, day_start=day_start)
    arrival_by_local_index: dict[int, str] = {}
    for visit_position, local_index in enumerate(day_plan.route_order):
        global_index = global_route[visit_position]
        arrival_by_local_index[local_index] = format_clock_time(arrivals[global_index])

    return {
        "day": day_plan.day,
        "places": [
            {
                "name": place.place.raw_name,
                "lat": place.lat,
                "lng": place.lng,
                "arrival_estimate": arrival_by_local_index[local_index],
                "fixed_time": format_time_value(place.place.fixed_time),
            }
            for local_index, place in enumerate(day_plan.places)
        ],
        "total_travel_seconds": day_plan.total_travel_seconds,
        "route_order": list(day_plan.route_order),
    }
