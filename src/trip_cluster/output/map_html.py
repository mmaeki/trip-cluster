"""Folium HTML map export for itineraries."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import folium

from trip_cluster.config import DEFAULT_DAY_START
from trip_cluster.models import GeocodedPlace, Itinerary, TravelTimeMatrix
from trip_cluster.output._helpers import global_route_for_day

_DAY_COLORS = (
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
)


def write_itinerary_map(
    path: str | Path,
    itinerary: Itinerary,
    matrix: TravelTimeMatrix,
    all_places: list[GeocodedPlace],
    *,
    day_start: time = DEFAULT_DAY_START,
) -> None:
    """Write a standalone folium HTML map for the itinerary."""
    del matrix, day_start  # reserved for future time-aware map overlays
    if not itinerary.days:
        raise ValueError("Cannot render a map with no day plans")

    center_lat, center_lng = _centroid(all_places)
    base_map = folium.Map(location=[center_lat, center_lng], zoom_start=11)

    for day_index, day_plan in enumerate(itinerary.days):
        color = _DAY_COLORS[day_index % len(_DAY_COLORS)]
        group = folium.FeatureGroup(name=f"Day {day_plan.day}", show=True)
        global_route = global_route_for_day(day_plan, all_places)
        route_coords = [(all_places[index].lat, all_places[index].lng) for index in global_route]

        for visit_number, local_index in enumerate(day_plan.route_order, start=1):
            place = day_plan.places[local_index]
            popup = (
                f"<b>{place.place.raw_name}</b><br>"
                f"Day {day_plan.day}, stop {visit_number}"
            )
            folium.Marker(
                location=[place.lat, place.lng],
                popup=popup,
                tooltip=f"Day {day_plan.day} #{visit_number}: {place.place.raw_name}",
                icon=folium.Icon(color="blue", icon="info-sign"),
            ).add_to(group)

        if len(route_coords) >= 2:
            folium.PolyLine(
                route_coords,
                color=color,
                weight=4,
                opacity=0.8,
                tooltip=f"Day {day_plan.day} route",
            ).add_to(group)

        group.add_to(base_map)

    folium.LayerControl(collapsed=False).add_to(base_map)
    base_map.save(str(path))


def _centroid(places: list[GeocodedPlace]) -> tuple[float, float]:
    lat = sum(place.lat for place in places) / len(places)
    lng = sum(place.lng for place in places) / len(places)
    return lat, lng
