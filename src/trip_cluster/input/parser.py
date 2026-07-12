"""Parse plain-text input files into Place objects."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import time
from pathlib import Path

from dateutil import parser as date_parser

from trip_cluster.exceptions import ParseError
from trip_cluster.models import ParsedInput, Place

REGION_HEADER_PATTERN = re.compile(r"^\s*#\s*region\s*:\s*(.+?)\s*$", re.IGNORECASE)
TIME_TAG_PATTERN = re.compile(r"\s+@\s+(.+?)\s*$", re.IGNORECASE)
ONLY_TIME_TAG_PATTERN = re.compile(r"^\s*@\s+", re.IGNORECASE)
INLINE_COMMENT_PATTERN = re.compile(r"\s#.*$")


def parse_input_file(
    path: str | Path,
    *,
    on_warning: Callable[[str], None] | None = None,
) -> ParsedInput:
    """Read and parse a TripCluster input file.

    Args:
        path: Path to the input file.
        on_warning: Optional callback for non-fatal warnings (defaults to stderr).

    Returns:
        ParsedInput with region, deduplicated places, and any warnings.

    Raises:
        ParseError: If the file is empty, unreadable, or contains no places.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ParseError(f"Input file not found: {file_path}")

    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"Could not read input file: {file_path}") from exc

    return parse_input_text(text, source=str(file_path), on_warning=on_warning)


def parse_input_text(
    text: str,
    *,
    source: str = "<input>",
    on_warning: Callable[[str], None] | None = None,
) -> ParsedInput:
    """Parse TripCluster input from a string."""
    warn = on_warning if on_warning is not None else _default_warning_handler

    region: str | None = None
    places: list[Place] = []
    warnings: list[str] = []
    seen_keys: set[tuple[str, time | None]] = set()

    lines = text.splitlines()
    if not lines:
        raise ParseError(f"No places found in {source}")

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        region_match = REGION_HEADER_PATTERN.match(line)
        if region_match:
            region = region_match.group(1).strip()
            continue

        place_line = INLINE_COMMENT_PATTERN.sub("", line).strip()
        if not place_line:
            continue

        raw_name, fixed_time = _split_place_and_time(place_line, line_number, source)

        dedup_key = (raw_name.lower().strip(), fixed_time)
        if dedup_key in seen_keys:
            message = f'Skipping duplicate on line {line_number}: "{raw_name}"'
            warnings.append(message)
            warn(message)
            continue

        seen_keys.add(dedup_key)
        places.append(
            Place(
                raw_name=raw_name,
                fixed_time=fixed_time,
                line_number=line_number,
            )
        )

    if not places:
        raise ParseError(f"No places found in {source}")

    return ParsedInput(region=region, places=places, warnings=warnings)


def _split_place_and_time(
    place_line: str, line_number: int, source: str
) -> tuple[str, time | None]:
    if ONLY_TIME_TAG_PATTERN.match(place_line):
        raise ParseError(
            f"Missing place name before time tag on line {line_number} in {source}: {place_line!r}"
        )

    time_match = TIME_TAG_PATTERN.search(place_line)
    if not time_match:
        return place_line.strip(), None

    time_text = time_match.group(1).strip()
    raw_name = place_line[: time_match.start()].strip()
    if not raw_name:
        raise ParseError(
            f"Missing place name before time tag on line {line_number} in {source}: {place_line!r}"
        )

    try:
        fixed_time = _parse_time_tag(time_text)
    except ValueError as exc:
        raise ParseError(
            f"Invalid time tag on line {line_number} in {source}: {time_text!r}"
        ) from exc

    return raw_name, fixed_time


def _parse_time_tag(value: str) -> time:
    """Parse flexible 12h/24h time strings such as '6:00am' or '12:30 PM'."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("empty time value")

    parsed = date_parser.parse(normalized, default=date_parser.parse("2000-01-01"))
    return parsed.time()


def _default_warning_handler(message: str) -> None:
    print(message, file=sys.stderr)
