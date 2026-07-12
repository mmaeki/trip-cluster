"""Unit tests for the input parser."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from trip_cluster.exceptions import ParseError
from trip_cluster.input.parser import parse_input_file, parse_input_text
from trip_cluster.models import Place


class TestParseInputText:
    def test_parses_region_header(self) -> None:
        result = parse_input_text("# region: Bay Area, CA\nGolden Gate Park\n")

        assert result.region == "Bay Area, CA"
        assert len(result.places) == 1
        assert result.places[0].raw_name == "Golden Gate Park"

    def test_region_header_is_case_insensitive(self) -> None:
        result = parse_input_text("# REGION: Tokyo, Japan\nShibuya\n")

        assert result.region == "Tokyo, Japan"

    def test_parses_place_without_time_tag(self) -> None:
        result = parse_input_text("Golden Gate Park\n")

        place = result.places[0]
        assert place.raw_name == "Golden Gate Park"
        assert place.fixed_time is None
        assert place.line_number == 1

    def test_parses_12h_time_tag(self) -> None:
        result = parse_input_text("Mt. Tam @ 6:00am\n")

        assert result.places[0].raw_name == "Mt. Tam"
        assert result.places[0].fixed_time == time(6, 0)

    def test_parses_24h_time_tag(self) -> None:
        result = parse_input_text("Dinner @ 18:45\n")

        assert result.places[0].fixed_time == time(18, 45)

    def test_parses_pm_time_tag(self) -> None:
        result = parse_input_text("Lunch @ 12:30 PM\n")

        assert result.places[0].fixed_time == time(12, 30)

    def test_strips_inline_comments(self) -> None:
        result = parse_input_text("Golden Gate Park # my favorite\n")

        assert result.places[0].raw_name == "Golden Gate Park"

    def test_skips_blank_lines(self) -> None:
        result = parse_input_text("Golden Gate Park\n\nLands End\n")

        assert [place.raw_name for place in result.places] == ["Golden Gate Park", "Lands End"]
        assert result.places[1].line_number == 3

    def test_deduplicates_exact_duplicates(self) -> None:
        warnings: list[str] = []
        result = parse_input_text(
            "Golden Gate Park\nLands End\nGolden Gate Park\n",
            on_warning=warnings.append,
        )

        assert [place.raw_name for place in result.places] == ["Golden Gate Park", "Lands End"]
        assert warnings == ['Skipping duplicate on line 3: "Golden Gate Park"']
        assert result.warnings == warnings

    def test_keeps_same_name_with_different_time_tags(self) -> None:
        result = parse_input_text("Park @ 9:00am\nPark @ 5:00pm\n")

        assert len(result.places) == 2
        assert result.places[0].fixed_time == time(9, 0)
        assert result.places[1].fixed_time == time(17, 0)

    def test_raises_when_no_places(self) -> None:
        with pytest.raises(ParseError, match="No places found"):
            parse_input_text("# region: Bay Area, CA\n")

    def test_raises_on_invalid_time_tag(self) -> None:
        with pytest.raises(ParseError, match="Invalid time tag"):
            parse_input_text("Sunrise @ not-a-time\n")

    def test_raises_on_time_tag_without_place_name(self) -> None:
        with pytest.raises(ParseError, match="Missing place name"):
            parse_input_text("@ 9:00am\n")

    def test_preserves_original_line_numbers(self) -> None:
        result = parse_input_text(
            "# region: Bay Area, CA\n\nGolden Gate Park\nLands End @ 8:00am\n"
        )

        assert result.places[0].line_number == 3
        assert result.places[1].line_number == 4


class TestParseInputFile:
    def test_parses_fixture_file(self, sample_input_path: Path) -> None:
        warnings: list[str] = []
        result = parse_input_file(sample_input_path, on_warning=warnings.append)

        assert result.region == "Bay Area, CA"
        assert [place.raw_name for place in result.places] == [
            "Golden Gate Park",
            "Lands End",
            "Mt. Tam",
            "Baker Beach",
            "Sutro Baths",
        ]
        assert result.places[2].fixed_time == time(6, 0)
        assert result.places[4].fixed_time == time(12, 30)
        assert len(warnings) == 1
        assert "line 6" in warnings[0]

    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.txt"

        with pytest.raises(ParseError, match="Input file not found"):
            parse_input_file(missing)

    def test_raises_when_file_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")

        with pytest.raises(ParseError, match="No places found"):
            parse_input_file(empty)


class TestPlaceModel:
    def test_place_is_immutable(self) -> None:
        place = Place(raw_name="Test", fixed_time=None, line_number=1)

        with pytest.raises(AttributeError):
            place.raw_name = "Other"  # type: ignore[misc]
