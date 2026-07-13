"""Cache-aware travel-time matrix orchestration."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date, datetime, time

from trip_cluster.cache.sqlite import SQLiteCache
from trip_cluster.config import DEFAULT_DAY_START, is_traffic_routing_enabled
from trip_cluster.exceptions import MatrixError
from trip_cluster.matrix.haversine import HaversineMatrixProvider, partial_durations
from trip_cluster.matrix.osrm import OsrmMatrixProvider
from trip_cluster.matrix.tomtom import TomTomMatrixProvider
from trip_cluster.models import GeocodedPlace, TravelTimeMatrix


class MatrixService:
    """Build an NxN travel-time matrix with caching and provider fallbacks.

    By default uses OSRM (free-flow). TomTom is only used when ``use_traffic``
    is enabled (``TRIPCLUSTER_USE_TRAFFIC=true`` or explicit parameter).
    """

    def __init__(
        self,
        cache: SQLiteCache,
        *,
        use_traffic: bool | None = None,
        tomtom: TomTomMatrixProvider | None = None,
        osrm: OsrmMatrixProvider | None = None,
        haversine: HaversineMatrixProvider | None = None,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._cache = cache
        self._use_traffic = (
            is_traffic_routing_enabled() if use_traffic is None else use_traffic
        )
        if tomtom is not None:
            self._tomtom = tomtom
        elif self._use_traffic:
            self._tomtom = TomTomMatrixProvider()
        else:
            self._tomtom = None
        self._osrm = osrm or OsrmMatrixProvider()
        self._haversine = haversine or HaversineMatrixProvider()
        self._on_warning = on_warning if on_warning is not None else _default_warning_handler

        if self._use_traffic and self._tomtom is not None and not self._tomtom.is_available():
            self._on_warning(
                "TRIPCLUSTER_USE_TRAFFIC is enabled but TOMTOM_API_KEY is not set; "
                "using OSRM free-flow routing."
            )

    def build_matrix(
        self,
        places: list[GeocodedPlace],
        *,
        trip_date: date | None = None,
        day_start: time = DEFAULT_DAY_START,
    ) -> TravelTimeMatrix:
        if not places:
            raise MatrixError("Cannot build a matrix with zero places")
        if len(places) == 1:
            return TravelTimeMatrix(
                durations=[[0.0]],
                place_ids=[places[0].place_id],
                primary_source="none",
                departure_bucket=format_departure_bucket(trip_date or date.today(), day_start),
            )

        effective_date = trip_date or date.today()
        default_bucket = format_departure_bucket(effective_date, day_start)
        place_ids = [p.place_id for p in places]
        coordinates = [(p.lat, p.lng) for p in places]

        matrix, source = self._get_matrix_for_bucket(
            place_ids,
            coordinates,
            departure_bucket=default_bucket,
            trip_date=effective_date,
            depart_at=day_start,
        )

        for index, place in enumerate(places):
            tagged_time = place.place.fixed_time
            if tagged_time is None:
                continue
            tagged_bucket = format_departure_bucket(effective_date, tagged_time)
            if tagged_bucket == default_bucket:
                continue
            self._apply_tagged_overrides(
                matrix,
                place_ids=place_ids,
                coordinates=coordinates,
                tagged_index=index,
                departure_bucket=tagged_bucket,
                trip_date=effective_date,
                depart_at=tagged_time,
            )

        return TravelTimeMatrix(
            durations=matrix,
            place_ids=place_ids,
            primary_source=source,
            departure_bucket=default_bucket,
        )

    def _get_matrix_for_bucket(
        self,
        place_ids: list[str],
        coordinates: list[tuple[float, float]],
        *,
        departure_bucket: str,
        trip_date: date,
        depart_at: time,
    ) -> tuple[list[list[float]], str]:
        cached = _load_matrix_from_cache(self._cache, place_ids, departure_bucket)
        if cached is not None:
            return cached, "cache"

        matrix, source = self._fetch_full_with_fallback(
            coordinates, trip_date=trip_date, depart_at=depart_at
        )
        _save_matrix_to_cache(self._cache, place_ids, departure_bucket, matrix, source)
        return matrix, source

    def _apply_tagged_overrides(
        self,
        matrix: list[list[float]],
        *,
        place_ids: list[str],
        coordinates: list[tuple[float, float]],
        tagged_index: int,
        departure_bucket: str,
        trip_date: date,
        depart_at: time,
    ) -> None:
        n = len(place_ids)
        origin_id = place_ids[tagged_index]
        tagged_coord = coordinates[tagged_index]

        # Row: tagged place -> all destinations at tagged departure time
        for j in range(n):
            if j == tagged_index:
                continue
            dest_id = place_ids[j]
            cached = self._cache.get_duration(origin_id, dest_id, departure_bucket)
            if cached is not None:
                matrix[tagged_index][j] = cached.duration_seconds
                continue

            row, source = self._fetch_partial_with_fallback(
                [tagged_coord],
                [coordinates[j]],
                trip_date=trip_date,
                depart_at=depart_at,
            )
            duration = row[0][0]
            matrix[tagged_index][j] = duration
            self._cache.set_duration(origin_id, dest_id, departure_bucket, duration, source=source)

        # Column: all origins -> tagged place at tagged departure time
        for i in range(n):
            if i == tagged_index:
                continue
            origin_pid = place_ids[i]
            cached = self._cache.get_duration(origin_pid, origin_id, departure_bucket)
            if cached is not None:
                matrix[i][tagged_index] = cached.duration_seconds
                continue

            col, source = self._fetch_partial_with_fallback(
                [coordinates[i]],
                [tagged_coord],
                trip_date=trip_date,
                depart_at=depart_at,
            )
            duration = col[0][0]
            matrix[i][tagged_index] = duration
            self._cache.set_duration(
                origin_pid, origin_id, departure_bucket, duration, source=source
            )

    def _traffic_tomtom_available(self) -> bool:
        return (
            self._use_traffic
            and self._tomtom is not None
            and self._tomtom.is_available()
        )

    def _fetch_full_with_fallback(
        self,
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time,
    ) -> tuple[list[list[float]], str]:
        if self._traffic_tomtom_available():
            try:
                raw = self._tomtom.get_durations(  # type: ignore[union-attr]
                    coordinates, trip_date=trip_date, depart_at=depart_at
                )
                matrix, source = self._finalize_matrix(
                    raw, coordinates, trip_date=trip_date, depart_at=depart_at, primary="tomtom"
                )
                return matrix, source
            except MatrixError as exc:
                self._on_warning(f"TomTom matrix failed ({exc}); trying OSRM fallback.")

        try:
            raw = self._osrm.get_durations(
                coordinates, trip_date=trip_date, depart_at=depart_at
            )
            matrix, source = self._finalize_matrix(
                raw, coordinates, trip_date=trip_date, depart_at=depart_at, primary="osrm"
            )
            return matrix, source
        except MatrixError as exc:
            self._on_warning(f"OSRM matrix failed ({exc}); using haversine fallback.")

        return (
            self._haversine.get_durations(
                coordinates, trip_date=trip_date, depart_at=depart_at
            ),
            "haversine",
        )

    def _finalize_matrix(
        self,
        raw: list[list[float | None]],
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time,
        primary: str,
    ) -> tuple[list[list[float]], str]:
        """Fill missing cells and return a complete matrix."""
        filled, source_counts = self._fill_gaps(
            raw, coordinates, trip_date=trip_date, depart_at=depart_at, primary=primary
        )
        return filled, _primary_source_label(source_counts)

    def _fill_gaps(
        self,
        raw: list[list[float | None]],
        coordinates: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time,
        primary: str,
    ) -> tuple[list[list[float]], dict[str, int]]:
        n = len(coordinates)
        filled = [[0.0] * n for _ in range(n)]
        source_counts: dict[str, int] = {primary: 0}

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                value = raw[i][j]
                if value is not None:
                    filled[i][j] = value
                    source_counts[primary] = source_counts.get(primary, 0) + 1
                    continue

                try:
                    filled[i][j] = self._osrm.get_pair_duration(coordinates[i], coordinates[j])
                    source_counts["osrm"] = source_counts.get("osrm", 0) + 1
                    continue
                except MatrixError:
                    pass

                filled[i][j] = partial_durations(
                    [coordinates[i]], [coordinates[j]]
                )[0][0]
                source_counts["haversine"] = source_counts.get("haversine", 0) + 1
                self._on_warning(
                    f"Could not route {i} -> {j} via {primary}/OSRM; used straight-line estimate."
                )

        return filled, source_counts

    def _fetch_partial_with_fallback(
        self,
        origin_coords: list[tuple[float, float]],
        dest_coords: list[tuple[float, float]],
        *,
        trip_date: date,
        depart_at: time,
    ) -> tuple[list[list[float]], str]:
        if self._traffic_tomtom_available():
            try:
                raw = self._tomtom.get_durations_partial(  # type: ignore[union-attr]
                    origin_coords,
                    dest_coords,
                    trip_date=trip_date,
                    depart_at=depart_at,
                )
                if raw and raw[0][0] is not None:
                    return [[raw[0][0]]], "tomtom"
            except MatrixError:
                pass

        try:
            combined = origin_coords + dest_coords
            n_origins = len(origin_coords)
            full = self._osrm.get_durations(
                combined, trip_date=trip_date, depart_at=depart_at
            )
            value = full[0][n_origins]
            if value is not None:
                return [[value]], "osrm"
        except MatrixError:
            pass

        return partial_durations(origin_coords, dest_coords), "haversine"


def _primary_source_label(source_counts: dict[str, int]) -> str:
    if not source_counts:
        return "unknown"
    if len(source_counts) == 1:
        return next(iter(source_counts))
    return max(source_counts, key=source_counts.get)


def format_departure_bucket(trip_date: date, depart_at: time) -> str:
    return datetime.combine(trip_date, depart_at).strftime("%Y-%m-%dT%H:%M")


def _load_matrix_from_cache(
    cache: SQLiteCache,
    place_ids: list[str],
    departure_bucket: str,
) -> list[list[float]] | None:
    n = len(place_ids)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            hit = cache.get_duration(place_ids[i], place_ids[j], departure_bucket)
            if hit is None:
                return None
            matrix[i][j] = hit.duration_seconds
    return matrix


def _save_matrix_to_cache(
    cache: SQLiteCache,
    place_ids: list[str],
    departure_bucket: str,
    matrix: list[list[float]],
    source: str,
) -> None:
    n = len(place_ids)
    entries = [
        (place_ids[i], place_ids[j], departure_bucket, matrix[i][j])
        for i in range(n)
        for j in range(n)
        if i != j
    ]
    cache.set_durations(entries, source=source)


def _default_warning_handler(message: str) -> None:
    print(message, file=sys.stderr)


def build_travel_time_matrix(
    places: list[GeocodedPlace],
    cache: SQLiteCache,
    *,
    trip_date: date | None = None,
    day_start: time = DEFAULT_DAY_START,
    use_traffic: bool | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> TravelTimeMatrix:
    """Convenience wrapper around MatrixService."""
    service = MatrixService(cache, use_traffic=use_traffic, on_warning=on_warning)
    return service.build_matrix(places, trip_date=trip_date, day_start=day_start)
