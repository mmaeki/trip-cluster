"""Unit tests for the output module."""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest

from trip_cluster.models import DayPlan, GeocodedPlace, Itinerary, Place, TravelTimeMatrix
from trip_cluster.output import (
    build_itinerary,
    format_itinerary_text,
    itinerary_to_dict,
    write_itinerary_json,
    write_itinerary_map,
)


def _place(
    name: str,
    line: int,
    lat: float,
    lng: float,
    fixed: time | None = None,
) -> GeocodedPlace:
    return GeocodedPlace(
        place=Place(raw_name=name, fixed_time=fixed, line_number=line),
        lat=lat,
        lng=lng,
        formatted_address=name,
    )


def _sample_itinerary() -> tuple[Itinerary, TravelTimeMatrix, list[GeocodedPlace]]:
    places = [
        _place("Golden Gate Park", 1, 37.77, -122.48),
        _place("Lands End", 2, 37.78, -122.51, fixed=time(10, 0)),
        _place("Mt. Tam", 3, 37.92, -122.60),
    ]
    matrix = TravelTimeMatrix(
        durations=[
            [0, 720, 3000],
            [780, 0, 3200],
            [3100, 3300, 0],
        ],
        place_ids=["line_1", "line_2", "line_3"],
        primary_source="osrm",
        departure_bucket="2026-07-15T09:00",
    )
    itinerary = build_itinerary(
        region="San Francisco, CA",
        day_plans=[
            DayPlan(day=1, places=places[:2], total_travel_seconds=720, route_order=[0, 1]),
            DayPlan(day=2, places=[places[2]], total_travel_seconds=0, route_order=[0]),
        ],
        warnings=["Example warning"],
        matrix_source="osrm",
    )
    return itinerary, matrix, places


class TestTextOutput:
    def test_renders_header_and_day_lines(self) -> None:
        itinerary, matrix, places = _sample_itinerary()
        text = format_itinerary_text(itinerary, matrix, places, day_start=time(9, 0))

        assert "TripCluster Itinerary — 2 days, 3 places" in text
        assert "Region: San Francisco, CA" in text
        assert "Day 1 (2 places, ~12 min driving):" in text
        assert "Golden Gate Park" in text
        assert "arr ~09:00" in text
        assert "Lands End" in text
        assert "(+12 min)" in text
        assert "Example warning" in text

    def test_shows_tagged_time_on_first_stop(self) -> None:
        places = [
            _place("Sunrise", 1, 37.77, -122.48, fixed=time(6, 0)),
            _place("Cafe", 2, 37.78, -122.50),
        ]
        matrix = TravelTimeMatrix(
            durations=[[0, 600], [620, 0]],
            place_ids=["line_1", "line_2"],
            primary_source="osrm",
            departure_bucket="2026-07-15T09:00",
        )
        itinerary = build_itinerary(
            region=None,
            day_plans=[
                DayPlan(day=1, places=places, total_travel_seconds=600, route_order=[0, 1]),
            ],
            warnings=[],
            matrix_source="osrm",
        )
        text = format_itinerary_text(itinerary, matrix, places, day_start=time(9, 0))

        assert "arr ~09:00 (tagged 06:00)" in text


class TestJsonOutput:
    def test_serializes_expected_schema(self) -> None:
        itinerary, matrix, places = _sample_itinerary()
        payload = itinerary_to_dict(itinerary, matrix, places, day_start=time(9, 0))

        assert payload["region"] == "San Francisco, CA"
        assert payload["matrix_source"] == "osrm"
        assert payload["warnings"] == ["Example warning"]
        assert payload["days"][0]["route_order"] == [0, 1]
        assert payload["days"][0]["places"][0]["name"] == "Golden Gate Park"
        assert payload["days"][0]["places"][1]["arrival_estimate"] == "09:12"
        assert payload["days"][0]["places"][1]["fixed_time"] == "10:00"

    def test_write_itinerary_json(self, tmp_path: Path) -> None:
        itinerary, matrix, places = _sample_itinerary()
        output_path = tmp_path / "itinerary.json"
        write_itinerary_json(output_path, itinerary, matrix, places, day_start=time(9, 0))

        loaded = json.loads(output_path.read_text(encoding="utf-8"))
        assert loaded["matrix_source"] == "osrm"
        assert len(loaded["days"]) == 2


class TestMapOutput:
    def test_writes_standalone_html(self, tmp_path: Path) -> None:
        itinerary, matrix, places = _sample_itinerary()
        output_path = tmp_path / "itinerary.html"
        write_itinerary_map(output_path, itinerary, matrix, places)

        html = output_path.read_text(encoding="utf-8")
        assert "folium" in html
        assert "Golden Gate Park" in html
        assert "Day 1" in html
        assert "Mt. Tam" in html

    def test_rejects_empty_itinerary(self, tmp_path: Path) -> None:
        itinerary = build_itinerary(
            region=None,
            day_plans=[],
            warnings=[],
            matrix_source="osrm",
        )
        with pytest.raises(ValueError, match="no day plans"):
            write_itinerary_map(tmp_path / "empty.html", itinerary, _sample_itinerary()[1], [])
