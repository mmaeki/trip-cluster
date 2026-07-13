"""Shared SQLite cache for geocoding results and travel-time matrix edges.

Both the geocoding module and the matrix module talk to external APIs.
This cache stores their responses on disk so a rerun of the same trip
makes zero repeat API calls.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS geocode_cache (
    cache_key         TEXT PRIMARY KEY,
    lat               REAL NOT NULL,
    lng               REAL NOT NULL,
    formatted_address TEXT NOT NULL,
    osm_id            TEXT,
    fetched_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matrix_cache (
    origin_id         TEXT NOT NULL,
    dest_id           TEXT NOT NULL,
    departure_bucket  TEXT NOT NULL,
    origin_coord      TEXT NOT NULL,
    dest_coord        TEXT NOT NULL,
    duration_seconds  REAL NOT NULL,
    source            TEXT NOT NULL,
    fetched_at        TEXT NOT NULL,
    PRIMARY KEY (origin_id, dest_id, departure_bucket, origin_coord, dest_coord)
);
"""


@dataclass(frozen=True, slots=True)
class CachedGeocode:
    """A geocoding result read from the cache."""

    lat: float
    lng: float
    formatted_address: str
    osm_id: str | None
    fetched_at: str


@dataclass(frozen=True, slots=True)
class CachedDuration:
    """A single travel-time matrix edge read from the cache."""

    duration_seconds: float
    source: str
    fetched_at: str


class SQLiteCache:
    """Key-value cache backed by a single SQLite file.

    Usage:
        with SQLiteCache("~/.tripcluster/cache.db") as cache:
            hit = cache.get_geocode("golden gate park", "Bay Area, CA")
    """

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path).expanduser()
        if str(db_path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path)
        else:
            self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_schema()
        self._conn.commit()

    # -- geocode cache -------------------------------------------------

    def get_geocode(self, name: str, region: str | None) -> CachedGeocode | None:
        """Return the cached geocode for a place, or None on a cache miss."""
        row = self._conn.execute(
            "SELECT lat, lng, formatted_address, osm_id, fetched_at"
            " FROM geocode_cache WHERE cache_key = ?",
            (_geocode_key(name, region),),
        ).fetchone()
        if row is None:
            return None
        return CachedGeocode(
            lat=row["lat"],
            lng=row["lng"],
            formatted_address=row["formatted_address"],
            osm_id=row["osm_id"],
            fetched_at=row["fetched_at"],
        )

    def set_geocode(
        self,
        name: str,
        region: str | None,
        *,
        lat: float,
        lng: float,
        formatted_address: str,
        osm_id: str | None = None,
    ) -> None:
        """Store (or overwrite) the geocode for a place."""
        existing = self.get_geocode(name, region)
        if existing is not None and (
            abs(existing.lat - lat) > 1e-4 or abs(existing.lng - lng) > 1e-4
        ):
            self.clear_matrix_cache()

        self._conn.execute(
            "INSERT OR REPLACE INTO geocode_cache"
            " (cache_key, lat, lng, formatted_address, osm_id, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_geocode_key(name, region), lat, lng, formatted_address, osm_id, _now()),
        )
        self._conn.commit()

    # -- matrix cache --------------------------------------------------

    def get_duration(
        self,
        origin_id: str,
        dest_id: str,
        departure_bucket: str,
        *,
        origin_coord: str,
        dest_coord: str,
    ) -> CachedDuration | None:
        """Return the cached travel time for one directed edge, or None."""
        row = self._conn.execute(
            "SELECT duration_seconds, source, fetched_at FROM matrix_cache"
            " WHERE origin_id = ? AND dest_id = ? AND departure_bucket = ?"
            " AND origin_coord = ? AND dest_coord = ?",
            (origin_id, dest_id, departure_bucket, origin_coord, dest_coord),
        ).fetchone()
        if row is None:
            return None
        return CachedDuration(
            duration_seconds=row["duration_seconds"],
            source=row["source"],
            fetched_at=row["fetched_at"],
        )

    def set_durations(
        self,
        entries: list[tuple[str, str, str, str, str, float]],
        *,
        source: str,
    ) -> None:
        """Store many directed edges at once.

        Each entry is
        (origin_id, dest_id, departure_bucket, origin_coord, dest_coord, duration_seconds).
        A full NxN matrix response is inserted in one transaction, which is
        far faster than N*N separate commits.
        """
        now = _now()
        self._conn.executemany(
            "INSERT OR REPLACE INTO matrix_cache"
            " (origin_id, dest_id, departure_bucket, origin_coord, dest_coord,"
            " duration_seconds, source, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (origin_id, dest_id, bucket, origin_coord, dest_coord, duration, source, now)
                for origin_id, dest_id, bucket, origin_coord, dest_coord, duration in entries
            ],
        )
        self._conn.commit()

    def set_duration(
        self,
        origin_id: str,
        dest_id: str,
        departure_bucket: str,
        duration_seconds: float,
        *,
        origin_coord: str,
        dest_coord: str,
        source: str,
    ) -> None:
        """Store a single directed edge."""
        self.set_durations(
            [
                (
                    origin_id,
                    dest_id,
                    departure_bucket,
                    origin_coord,
                    dest_coord,
                    duration_seconds,
                )
            ],
            source=source,
        )

    def clear_matrix_cache(self) -> None:
        """Drop all cached travel-time edges (e.g. after a geocode correction)."""
        self._conn.execute("DELETE FROM matrix_cache")
        self._conn.commit()

    def _migrate_schema(self) -> None:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='matrix_cache'"
        ).fetchone()
        if row is None:
            return
        columns = {
            col["name"]
            for col in self._conn.execute("PRAGMA table_info(matrix_cache)").fetchall()
        }
        if "origin_coord" not in columns:
            self._conn.execute("DROP TABLE matrix_cache")
            self._conn.executescript(_SCHEMA)

    # -- lifecycle -----------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteCache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def coord_cache_key(lat: float, lng: float) -> str:
    """Stable cache key for a coordinate pair."""
    return f"{lat:.4f},{lng:.4f}"


def _geocode_key(name: str, region: str | None) -> str:
    """Build the primary key for a geocode lookup.

    Normalizing (lowercase, trimmed) means "Golden Gate Park " and
    "golden gate park" hit the same cache row. The region is part of the
    key because the same name can resolve differently in different regions.
    """
    normalized_name = name.strip().lower()
    normalized_region = (region or "").strip().lower()
    return f"{normalized_name}|{normalized_region}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
