"""Travel-time matrix provider interface."""

from __future__ import annotations

from datetime import date, time
from typing import Protocol


class MatrixProvider(Protocol):
    """Compute an NxN driving-duration matrix for a set of coordinates."""

    @property
    def source_name(self) -> str:
        """Short label stored in cache (e.g. 'tomtom', 'osrm')."""
        ...

    def get_durations(
        self,
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time,
    ) -> list[list[float]]:
        """Return durations[i][j] in seconds from place i to place j."""
        ...
