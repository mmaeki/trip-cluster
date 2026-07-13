"""CLI text summary for itineraries."""

from __future__ import annotations

from datetime import time

from trip_cluster.config import DEFAULT_DAY_START
from trip_cluster.models import GeocodedPlace, Itinerary, TravelTimeMatrix
from trip_cluster.output._helpers import format_clock_time, format_time_value, global_route_for_day
from trip_cluster.routing.ordering import simulate_arrival_times


def format_itinerary_text(
    itinerary: Itinerary,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
) -> str:
    """Render a human-readable multi-day itinerary summary."""
    total_places = sum(len(day.places) for day in itinerary.days)
    lines = [
        f"TripCluster Itinerary — {len(itinerary.days)} days, {total_places} places",
    ]
    if itinerary.region:
        lines.append(f"Region: {itinerary.region}")
    lines.append("")

    for day_plan in itinerary.days:
        driving_minutes = round(day_plan.total_travel_seconds / 60)
        lines.append(
            f"Day {day_plan.day} ({len(day_plan.places)} places, ~{driving_minutes} min driving):"
        )
        lines.extend(
            _format_day_lines(
                day_plan,
                matrix,
                all_places,
                day_start=day_start,
            )
        )
        lines.append("")

    if itinerary.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in itinerary.warnings)

    return "\n".join(lines).rstrip() + "\n"


def _format_day_lines(
    day_plan,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time,
) -> list[str]:
    global_route = global_route_for_day(day_plan, all_places)
    arrivals = simulate_arrival_times(global_route, matrix, day_start=day_start)
    lines: list[str] = []

    for visit_number, local_index in enumerate(day_plan.route_order, start=1):
        place = day_plan.places[local_index]
        global_index = global_route[visit_number - 1]
        suffix = _stop_suffix(
            visit_number=visit_number,
            global_route=global_route,
            matrix=matrix,
            arrival_seconds=arrivals[global_index],
            fixed_time=place.place.fixed_time,
        )
        lines.append(f"  {visit_number}. {place.place.raw_name:<22}{suffix}")

    return lines


def _stop_suffix(
    *,
    visit_number: int,
    global_route: list[int],
    matrix: TravelTimeMatrix,
    arrival_seconds: float,
    fixed_time: time | None,
) -> str:
    if visit_number == 1:
        text = f"arr ~{format_clock_time(arrival_seconds)}"
        tagged = format_time_value(fixed_time)
        if tagged is not None:
            text += f" (tagged {tagged})"
        return text

    previous = global_route[visit_number - 2]
    current = global_route[visit_number - 1]
    leg_minutes = round(matrix.durations[previous][current] / 60)
    return f"(+{leg_minutes} min)"
