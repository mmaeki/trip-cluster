"""Domain models for TripCluster."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True, slots=True)
class Place:
    """A tourist location parsed from the input file."""

    raw_name: str
    fixed_time: time | None
    line_number: int


@dataclass(frozen=True, slots=True)
class ParsedInput:
    """Result of parsing an input file."""

    region: str | None
    places: list[Place]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GeocodedPlace:
    """A place with resolved coordinates."""

    place: Place
    lat: float
    lng: float
    formatted_address: str


@dataclass(frozen=True, slots=True)
class DayPlan:
    """Ordered places assigned to a single day."""

    day: int
    places: list[GeocodedPlace]
    total_travel_seconds: int
    route_order: list[int]


@dataclass(frozen=True, slots=True)
class Itinerary:
    """Complete multi-day trip plan."""

    region: str | None
    days: list[DayPlan]
    warnings: list[str]
    matrix_source: str
