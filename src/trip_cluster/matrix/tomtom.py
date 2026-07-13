"""TomTom Matrix Routing v2 synchronous client."""

from __future__ import annotations

import time
from datetime import date, datetime
from datetime import time as time_type
from typing import Any

import httpx

from trip_cluster.config import TOMTOM_MATRIX_URL, TOMTOM_MAX_RETRIES, get_tomtom_api_key
from trip_cluster.exceptions import MatrixError

_USE_ENV_KEY = object()


class TomTomMatrixProvider:
    """Traffic-aware matrix via TomTom Matrix Routing v2."""

    def __init__(
        self,
        *,
        api_key: str | None | object = _USE_ENV_KEY,
        base_url: str = TOMTOM_MATRIX_URL,
        timeout_seconds: float = 60.0,
        max_retries: int = TOMTOM_MAX_RETRIES,
    ) -> None:
        if api_key is _USE_ENV_KEY:
            self._api_key = get_tomtom_api_key()
        else:
            self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def source_name(self) -> str:
        return "tomtom"

    def is_available(self) -> bool:
        return bool(self._api_key)

    def get_durations(
        self,
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time_type,
    ) -> list[list[float | None]]:
        if not self._api_key:
            raise MatrixError("TOMTOM_API_KEY is not set")
        if not coordinates:
            return []
        if len(coordinates) == 1:
            return [[0.0]]

        body = {
            "origins": [
                {"point": {"latitude": lat, "longitude": lng}} for lat, lng in coordinates
            ],
            "destinations": [
                {"point": {"latitude": lat, "longitude": lng}} for lat, lng in coordinates
            ],
            "options": {
                "departAt": _format_depart_at(trip_date, depart_at),
                "routeType": "fastest",
                "traffic": _traffic_mode(trip_date),
                "travelMode": "car",
            },
        }
        data = self._request_with_retries(body)
        return _parse_matrix_response(data, len(coordinates))

    def get_durations_partial(
        self,
        origin_coords: list[tuple[float, float]],
        dest_coords: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time_type,
    ) -> list[list[float | None]]:
        """Fetch a sub-matrix (len(origins) x len(destinations))."""
        if not self._api_key:
            raise MatrixError("TOMTOM_API_KEY is not set")
        if not origin_coords or not dest_coords:
            return []

        body = {
            "origins": [
                {"point": {"latitude": lat, "longitude": lng}} for lat, lng in origin_coords
            ],
            "destinations": [
                {"point": {"latitude": lat, "longitude": lng}} for lat, lng in dest_coords
            ],
            "options": {
                "departAt": _format_depart_at(trip_date, depart_at),
                "routeType": "fastest",
                "traffic": _traffic_mode(trip_date),
                "travelMode": "car",
            },
        }
        data = self._request_with_retries(body)
        return _parse_matrix_response(data, len(origin_coords), len(dest_coords))

    def _request_with_retries(self, body: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        url = f"{self._base_url}?key={self._api_key}"

        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, json=body)
                    if response.status_code == 429:
                        raise httpx.HTTPStatusError(
                            "rate limited", request=response.request, response=response
                        )
                    response.raise_for_status()
                    return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (
                    429,
                    503,
                ):
                    raise MatrixError(
                        f"TomTom matrix request failed: HTTP {exc.response.status_code}"
                    ) from exc
                last_error = exc
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)

        raise MatrixError(
            f"TomTom matrix request failed after {self._max_retries} attempts"
        ) from last_error


def _format_depart_at(trip_date: date, depart_at: time_type) -> str:
    return datetime.combine(trip_date, depart_at).isoformat(timespec="seconds")


def _traffic_mode(trip_date: date) -> str:
    return "live" if trip_date == date.today() else "historical"


def _parse_matrix_response(
    data: dict[str, Any],
    n_origins: int,
    n_destinations: int | None = None,
) -> list[list[float | None]]:
    if n_destinations is None:
        n_destinations = n_origins

    matrix: list[list[float | None]] = [[None] * n_destinations for _ in range(n_origins)]
    cells = data.get("data")
    if not isinstance(cells, list):
        raise MatrixError("Unexpected TomTom matrix response")

    for cell in cells:
        if not isinstance(cell, dict):
            continue
        origin_idx = cell.get("originIndex")
        dest_idx = cell.get("destinationIndex")
        if not isinstance(origin_idx, int) or not isinstance(dest_idx, int):
            continue
        if origin_idx >= n_origins or dest_idx >= n_destinations:
            continue

        summary = cell.get("routeSummary")
        if isinstance(summary, dict) and "travelTimeInSeconds" in summary:
            matrix[origin_idx][dest_idx] = float(summary["travelTimeInSeconds"])
        elif origin_idx == dest_idx:
            matrix[origin_idx][dest_idx] = 0.0

    return matrix
