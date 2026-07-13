"""Typer CLI entry point and end-to-end orchestration."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path

import typer
from dateutil import parser as date_parser

from trip_cluster.cache.sqlite import SQLiteCache
from trip_cluster.clustering import cluster_places
from trip_cluster.config import DEFAULT_DAY_START, configured_user_agent_issue, get_cache_db_path
from trip_cluster.exceptions import TripClusterError
from trip_cluster.geocoding import geocode_places
from trip_cluster.input import parse_input_file
from trip_cluster.matrix import build_travel_time_matrix
from trip_cluster.models import GeocodedPlace, Itinerary, TravelTimeMatrix
from trip_cluster.output import (
    build_itinerary,
    format_itinerary_text,
    write_itinerary_json,
    write_itinerary_map,
)
from trip_cluster.routing import build_day_plans

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Cluster tourist locations into daily itineraries using driving travel times.",
)


@app.callback()
def main(
    input_path: Path = typer.Option(..., "--input", help="Plain-text file listing places."),
    days: int | None = typer.Option(None, "--days", min=1, help="Number of trip days."),
    output_map: Path | None = typer.Option(
        None, "--output-map", help="Write a folium HTML map to this path."
    ),
    output_json: Path | None = typer.Option(
        None, "--output-json", help="Write itinerary JSON to this path."
    ),
    max_per_day: int | None = typer.Option(
        None, "--max-per-day", min=1, help="Maximum attractions per day."
    ),
    day_start: str = typer.Option(
        "09:00",
        "--day-start",
        help="Departure time for each day (HH:MM).",
    ),
    trip_date: str | None = typer.Option(
        None,
        "--trip-date",
        help="Trip date (YYYY-MM-DD). Defaults to today.",
    ),
    cache_db: Path | None = typer.Option(
        None,
        "--cache-db",
        help="SQLite cache database path.",
    ),
    traffic: bool = typer.Option(
        False,
        "--traffic",
        help="Enable TomTom traffic-aware routing (requires TOMTOM_API_KEY).",
    ),
    skip_failures: bool = typer.Option(
        False,
        "--skip-failures",
        help="Skip places that fail to geocode instead of aborting.",
    ),
    cluster_method: str = typer.Option(
        "agglomerative",
        "--cluster-method",
        help="Clustering algorithm (only agglomerative is supported in v1).",
    ),
) -> None:
    """Build a multi-day itinerary from a plain-text place list."""
    try:
        run_pipeline(
            input_path=input_path,
            days=days,
            output_map=output_map,
            output_json=output_json,
            max_per_day=max_per_day,
            day_start=_parse_day_start(day_start),
            trip_date=_parse_trip_date(trip_date) if trip_date else date.today(),
            cache_db=cache_db or get_cache_db_path(),
            use_traffic=traffic,
            skip_failures=skip_failures,
            cluster_method=cluster_method,
        )
    except TripClusterError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def run_pipeline(
    *,
    input_path: Path,
    days: int | None = None,
    output_map: Path | None = None,
    output_json: Path | None = None,
    max_per_day: int | None = None,
    day_start: time = DEFAULT_DAY_START,
    trip_date: date | None = None,
    cache_db: Path | None = None,
    use_traffic: bool = False,
    skip_failures: bool = False,
    cluster_method: str = "agglomerative",
    on_warning: Callable[[str], None] | None = None,
) -> Itinerary:
    """Run the full TripCluster pipeline and return the assembled itinerary."""
    if cluster_method != "agglomerative":
        raise TripClusterError(
            f"Unsupported --cluster-method {cluster_method!r}; only 'agglomerative' is available."
        )

    warn = on_warning if on_warning is not None else _default_warning_handler
    user_agent_issue = configured_user_agent_issue()
    if user_agent_issue:
        warn(user_agent_issue)

    effective_trip_date = trip_date or date.today()
    warnings: list[str] = []

    def collect_warning(message: str) -> None:
        warnings.append(message)
        warn(message)

    parsed = parse_input_file(input_path, on_warning=collect_warning)
    warnings.extend(parsed.warnings)

    if not use_traffic and any(place.fixed_time is not None for place in parsed.places):
        message = "@time tags have no effect without --traffic (OSRM uses free-flow driving times)."
        warnings.append(message)
        warn(message)

    with SQLiteCache(cache_db or get_cache_db_path()) as cache:
        geocoded = geocode_places(
            parsed.places,
            parsed.region,
            cache,
            skip_failures=skip_failures,
            on_warning=collect_warning,
        )
        warnings.extend(geocoded.warnings)
        places = geocoded.places

        if not places:
            raise TripClusterError("No geocoded places remain after input processing.")

        matrix = build_travel_time_matrix(
            places,
            cache,
            trip_date=effective_trip_date,
            day_start=day_start,
            use_traffic=use_traffic,
            on_warning=collect_warning,
        )

        cluster_result = cluster_places(
            matrix,
            days=days,
            max_per_day=max_per_day,
            on_warning=collect_warning,
        )
        warnings.extend(cluster_result.warnings)

        day_plans = build_day_plans(
            places,
            cluster_result,
            matrix,
            day_start=day_start,
            on_warning=collect_warning,
        )

        itinerary = build_itinerary(
            region=parsed.region,
            day_plans=day_plans,
            warnings=warnings,
            matrix_source=matrix.primary_source,
        )

        _write_outputs(
            itinerary,
            matrix,
            places,
            day_start=day_start,
            output_json=output_json,
            output_map=output_map,
        )

    return itinerary


def _write_outputs(
    itinerary: Itinerary,
    matrix: TravelTimeMatrix,
    places: list[GeocodedPlace],
    *,
    day_start: time,
    output_json: Path | None,
    output_map: Path | None,
) -> None:
    typer.echo(format_itinerary_text(itinerary, matrix, places, day_start=day_start))
    if output_json is not None:
        write_itinerary_json(output_json, itinerary, matrix, places, day_start=day_start)
    if output_map is not None:
        write_itinerary_map(output_map, itinerary, matrix, places, day_start=day_start)


def _parse_day_start(value: str) -> time:
    try:
        parsed = date_parser.parse(value, default=datetime(2000, 1, 1))
    except (ValueError, TypeError) as exc:
        raise TripClusterError(f"Invalid --day-start {value!r}; use HH:MM format.") from exc
    return parsed.time()


def _parse_trip_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TripClusterError(f"Invalid --trip-date {value!r}; use YYYY-MM-DD format.") from exc


def _default_warning_handler(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    app()
