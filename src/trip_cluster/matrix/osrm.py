"""OSRM Table API client (no live traffic)."""

from __future__ import annotations

import time
from datetime import date
from datetime import time as time_type
from typing import Any

import httpx

from trip_cluster.config import OSRM_BASE_URL, OSRM_MAX_RETRIES
from trip_cluster.exceptions import MatrixError


class OsrmMatrixProvider:
    """Public OSRM /table endpoint — free, no API key, no traffic data."""

    def __init__(
        self,
        *,
        base_url: str = OSRM_BASE_URL,
        timeout_seconds: float = 30.0,
        max_retries: int = OSRM_MAX_RETRIES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def source_name(self) -> str:
        return "osrm"

    def get_durations(
        self,
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time_type,
    ) -> list[list[float | None]]:
        del trip_date, depart_at
        if not coordinates:
            return []
        if len(coordinates) == 1:
            return [[0.0]]

        coord_str = ";".join(f"{lng},{lat}" for lat, lng in coordinates)
        url = f"{self._base_url}/table/v1/driving/{coord_str}"
        params = {"annotations": "duration"}

        data = self._request_with_retries(url, params)
        durations = data.get("durations")
        if not isinstance(durations, list):
            raise MatrixError("Unexpected OSRM table response")

        n = len(coordinates)
        matrix: list[list[float | None]] = [[0.0] * n for _ in range(n)]
        for i in range(n):
            row = durations[i]
            if not isinstance(row, list) or len(row) != n:
                raise MatrixError("OSRM returned malformed duration matrix")
            for j in range(n):
                value = row[j]
                if i == j:
                    matrix[i][j] = 0.0
                elif value is None:
                    matrix[i][j] = None
                else:
                    matrix[i][j] = float(value)
        return matrix

    def get_pair_duration(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> float:
        """Driving time in seconds between two points."""
        matrix = self.get_durations(
            [origin, dest],
            trip_date=date.today(),
            depart_at=time_type(0, 0),
        )
        value = matrix[0][1]
        if value is None:
            raise MatrixError("OSRM could not route between the two points")
        return value

    def _request_with_retries(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                    if data.get("code") != "Ok":
                        raise MatrixError(f"OSRM error: {data.get('message', data.get('code'))}")
                    return data
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
        raise MatrixError(f"OSRM request failed after {self._max_retries} attempts") from last_error
