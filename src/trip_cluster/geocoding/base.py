"""Geocoder interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GeocodeCandidate:
    """One result returned by a geocoding provider."""

    lat: float
    lng: float
    formatted_address: str
    osm_id: str | None
    importance: float


class Geocoder(Protocol):
    """Look up coordinates for a free-text place query."""

    def search(self, query: str) -> list[GeocodeCandidate]:
        """Return ranked candidates for the query (highest importance first)."""
        ...
