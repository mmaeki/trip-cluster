"""Cache-aware geocoding orchestration."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from trip_cluster.cache.sqlite import SQLiteCache
from trip_cluster.config import AMBIGUITY_IMPORTANCE_RATIO, NOMINATIM_REQUEST_INTERVAL_SECONDS
from trip_cluster.exceptions import GeocodeError
from trip_cluster.geocoding.base import GeocodeCandidate, Geocoder
from trip_cluster.geocoding.nominatim import NominatimGeocoder
from trip_cluster.geocoding.query import (
    anchor_distance_threshold_km,
    build_fallback_queries,
    build_query,
    pick_best_candidate,
)
from trip_cluster.matrix.haversine import haversine_km
from trip_cluster.models import GeocodedPlace, Place


@dataclass(frozen=True, slots=True)
class GeocodingResult:
    """All successfully geocoded places plus any non-fatal warnings."""

    places: list[GeocodedPlace]
    warnings: list[str]


class GeocodingService:
    """Geocode a list of places, checking the SQLite cache first."""

    def __init__(
        self,
        cache: SQLiteCache,
        geocoder: Geocoder | None = None,
        *,
        request_interval_seconds: float = NOMINATIM_REQUEST_INTERVAL_SECONDS,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._cache = cache
        self._geocoder = geocoder or NominatimGeocoder()
        self._request_interval = request_interval_seconds
        self._on_warning = on_warning if on_warning is not None else _default_warning_handler
        self._last_api_call_at: float | None = None

    def geocode_all(
        self,
        places: list[Place],
        region: str | None,
        *,
        skip_failures: bool = False,
    ) -> GeocodingResult:
        geocoded: list[GeocodedPlace] = []
        warnings: list[str] = []
        anchor_points: list[tuple[float, float]] = []

        for place in places:
            try:
                result = self._geocode_one(place, region, anchor_points=anchor_points)
                geocoded.append(result)
                anchor_points.append((result.lat, result.lng))
            except GeocodeError as exc:
                if skip_failures:
                    message = (
                        f'Excluded "{place.raw_name}" (line {place.line_number}): {exc}'
                    )
                    warnings.append(message)
                    self._on_warning(message)
                    continue
                raise

        return GeocodingResult(places=geocoded, warnings=warnings)

    def _geocode_one(
        self,
        place: Place,
        region: str | None,
        *,
        anchor_points: list[tuple[float, float]],
    ) -> GeocodedPlace:
        cached = self._cache.get_geocode(place.raw_name, region)
        if cached is not None:
            if anchor_points and not self._cached_coords_plausible(
                cached.lat, cached.lng, anchor_points
            ):
                message = (
                    f'Cached geocode for "{place.raw_name}" looks too far from other stops; '
                    "re-resolving."
                )
                self._on_warning(message)
            else:
                return GeocodedPlace(
                    place=place,
                    lat=cached.lat,
                    lng=cached.lng,
                    formatted_address=cached.formatted_address,
                )

        candidates = self._search_with_fallbacks(place.raw_name, region)
        if not candidates:
            raise GeocodeError(f"No geocoding results for {place.raw_name!r}")

        best = pick_best_candidate(candidates, region=region, anchor_points=anchor_points)
        self._warn_if_ambiguous(place.raw_name, candidates, chosen=best)

        if anchor_points:
            centroid_lat = sum(lat for lat, _ in anchor_points) / len(anchor_points)
            centroid_lng = sum(lng for _, lng in anchor_points) / len(anchor_points)
            distance_km = haversine_km(centroid_lat, centroid_lng, best.lat, best.lng)
            max_distance_km = anchor_distance_threshold_km(anchor_points)
            if distance_km > max_distance_km:
                self._on_warning(
                    f'Geocoded "{place.raw_name}" to "{best.formatted_address}" '
                    f"({distance_km:.0f} km from other stops). "
                    "Consider using a more specific name in your input file."
                )

        self._cache.set_geocode(
            place.raw_name,
            region,
            lat=best.lat,
            lng=best.lng,
            formatted_address=best.formatted_address,
            osm_id=best.osm_id,
        )

        return GeocodedPlace(
            place=place,
            lat=best.lat,
            lng=best.lng,
            formatted_address=best.formatted_address,
        )

    def _search_with_fallbacks(
        self, name: str, region: str | None
    ) -> list[GeocodeCandidate]:
        primary_query = build_query(name, region)
        self._respect_rate_limit()
        candidates = self._geocoder.search(primary_query)
        self._last_api_call_at = time.monotonic()
        if candidates:
            return candidates

        for fallback_query in build_fallback_queries(name, region):
            if fallback_query == primary_query:
                continue
            message = f'No geocoding results for "{primary_query}"; trying "{fallback_query}"'
            self._on_warning(message)
            self._respect_rate_limit()
            candidates = self._geocoder.search(fallback_query)
            self._last_api_call_at = time.monotonic()
            if candidates:
                return candidates

        return []

    def _cached_coords_plausible(
        self,
        lat: float,
        lng: float,
        anchor_points: list[tuple[float, float]],
    ) -> bool:
        centroid_lat = sum(a_lat for a_lat, _ in anchor_points) / len(anchor_points)
        centroid_lng = sum(a_lng for _, a_lng in anchor_points) / len(anchor_points)
        distance_km = haversine_km(centroid_lat, centroid_lng, lat, lng)
        return distance_km <= anchor_distance_threshold_km(anchor_points)

    def _respect_rate_limit(self) -> None:
        if self._last_api_call_at is None:
            return
        elapsed = time.monotonic() - self._last_api_call_at
        if elapsed < self._request_interval:
            time.sleep(self._request_interval - elapsed)

    def _warn_if_ambiguous(
        self,
        name: str,
        candidates: list[GeocodeCandidate],
        *,
        chosen: GeocodeCandidate,
    ) -> None:
        if len(candidates) < 2:
            return
        ranked = sorted(candidates, key=lambda c: c.importance, reverse=True)
        top = ranked[0]
        if chosen is not top:
            return
        second = ranked[1]
        if second.importance >= top.importance * AMBIGUITY_IMPORTANCE_RATIO:
            message = (
                f'Ambiguous geocode for "{name}": using "{top.formatted_address}" '
                f'(importance {top.importance:.3f}); '
                f'runner-up "{second.formatted_address}" '
                f"(importance {second.importance:.3f})"
            )
            self._on_warning(message)


def geocode_places(
    places: list[Place],
    region: str | None,
    cache: SQLiteCache,
    *,
    geocoder: Geocoder | None = None,
    skip_failures: bool = False,
    on_warning: Callable[[str], None] | None = None,
) -> GeocodingResult:
    """Convenience wrapper around GeocodingService."""
    service = GeocodingService(cache, geocoder, on_warning=on_warning)
    return service.geocode_all(places, region, skip_failures=skip_failures)


def _default_warning_handler(message: str) -> None:
    print(message, file=sys.stderr)
