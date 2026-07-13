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

    @property
    def place_id(self) -> str:
        """Stable identifier for matrix cache keys."""
        return f"line_{self.place.line_number}"


@dataclass(frozen=True, slots=True)
class TravelTimeMatrix:
    """NxN matrix of driving travel times in seconds (asymmetric)."""

    durations: list[list[float]]
    place_ids: list[str]
    primary_source: str
    departure_bucket: str

    @property
    def size(self) -> int:
        return len(self.place_ids)

    def symmetrized(self) -> list[list[float]]:
        """Average (i,j) and (j,i) for clustering algorithms that need symmetry."""
        n = self.size
        sym = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    sym[i][j] = 0.0
                else:
                    sym[i][j] = (self.durations[i][j] + self.durations[j][i]) / 2.0
        return sym


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
