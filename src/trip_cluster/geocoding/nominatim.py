"""Nominatim (OpenStreetMap) geocoding client."""

from __future__ import annotations

import sys
import time
from typing import Any

import httpx

from trip_cluster.config import (
    NOMINATIM_BASE_URL,
    NOMINATIM_MAX_RETRIES,
    configured_user_agent_issue,
    get_user_agent,
    validate_user_agent,
)
from trip_cluster.exceptions import GeocodeError
from trip_cluster.geocoding.base import GeocodeCandidate


class NominatimGeocoder:
    """Client for the public Nominatim search API.

    Nominatim requires a descriptive User-Agent and enforces a 1 req/sec
    rate limit. Retries transient failures with exponential backoff.
    """

    def __init__(
        self,
        *,
        base_url: str = NOMINATIM_BASE_URL,
        user_agent: str | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = NOMINATIM_MAX_RETRIES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        if user_agent is not None:
            self._user_agent = user_agent
            agent_error = validate_user_agent(self._user_agent)
            if agent_error:
                raise GeocodeError(agent_error)
        else:
            issue = configured_user_agent_issue()
            if issue:
                print(f"Warning: {issue} Using built-in User-Agent instead.", file=sys.stderr)
            self._user_agent = get_user_agent()
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    def search(self, query: str) -> list[GeocodeCandidate]:
        response_data = self._request_with_retries(query)
        candidates = [_parse_candidate(item) for item in response_data]
        return sorted(candidates, key=lambda c: c.importance, reverse=True)

    def _request_with_retries(self, query: str) -> list[dict[str, Any]]:
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                return self._request(query)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    if exc.response.status_code == 403:
                        raise GeocodeError(_forbidden_message(query, self._user_agent)) from exc
                    if exc.response.status_code != 429:
                        raise GeocodeError(
                            f"Nominatim request failed for {query!r}: "
                            f"HTTP {exc.response.status_code}"
                        ) from exc
                last_error = exc
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)

        raise GeocodeError(
            f"Nominatim request failed for {query!r} after {self._max_retries} attempts"
        ) from last_error

    def _request(self, query: str) -> list[dict[str, Any]]:
        with httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": self._user_agent},
        ) as client:
            response = client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "limit": 5},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise GeocodeError(f"Unexpected Nominatim response for {query!r}")
            return data


def _forbidden_message(query: str, user_agent: str) -> str:
    hint = validate_user_agent(user_agent)
    if hint:
        return hint
    return (
        f"Nominatim rejected the request for {query!r} with HTTP 403. "
        "This usually means the User-Agent is not acceptable. "
        "Set NOMINATIM_USER_AGENT to your app name plus a real contact email, "
        "or unset it to use the built-in default."
    )


def _parse_candidate(item: dict[str, Any]) -> GeocodeCandidate:
    try:
        osm_type = item.get("osm_type")
        osm_id = item.get("osm_id")
        combined_osm_id = f"{osm_type}/{osm_id}" if osm_type and osm_id else None
        return GeocodeCandidate(
            lat=float(item["lat"]),
            lng=float(item["lon"]),
            formatted_address=str(item["display_name"]),
            osm_id=combined_osm_id,
            importance=float(item.get("importance", 0.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodeError("Could not parse Nominatim response") from exc
