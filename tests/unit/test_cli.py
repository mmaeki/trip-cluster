"""Unit tests for the CLI."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from trip_cluster.cli import _parse_day_start, _parse_trip_date, app, run_pipeline
from trip_cluster.exceptions import TripClusterError
from trip_cluster.geocoding.service import GeocodingResult
from trip_cluster.models import (
    ClusterResult,
    DayPlan,
    GeocodedPlace,
    ParsedInput,
    Place,
    TravelTimeMatrix,
)


def _geocoded(name: str, line: int, fixed: time | None = None) -> GeocodedPlace:
    return GeocodedPlace(
        place=Place(raw_name=name, fixed_time=fixed, line_number=line),
        lat=37.7,
        lng=-122.4,
        formatted_address=name,
    )


class TestCliParsing:
    def test_parse_day_start(self) -> None:
        assert _parse_day_start("09:00") == time(9, 0)

    def test_parse_trip_date(self) -> None:
        assert _parse_trip_date("2026-07-15") == date(2026, 7, 15)

    def test_invalid_day_start_raises(self) -> None:
        with pytest.raises(TripClusterError, match="Invalid --day-start"):
            _parse_day_start("not-a-time")


class TestRunPipeline:
    def test_rejects_unsupported_cluster_method(self, tmp_path: Path) -> None:
        input_path = tmp_path / "places.txt"
        input_path.write_text("Golden Gate Park\n", encoding="utf-8")

        with pytest.raises(TripClusterError, match="Unsupported --cluster-method"):
            run_pipeline(
                input_path=input_path,
                cluster_method="medoids",
            )

    @patch("trip_cluster.cli.write_itinerary_map")
    @patch("trip_cluster.cli.write_itinerary_json")
    @patch("trip_cluster.cli.build_day_plans")
    @patch("trip_cluster.cli.cluster_places")
    @patch("trip_cluster.cli.build_travel_time_matrix")
    @patch("trip_cluster.cli.geocode_places")
    @patch("trip_cluster.cli.parse_input_file")
    @patch("trip_cluster.cli.SQLiteCache")
    def test_run_pipeline_orchestrates_modules(
        self,
        mock_cache_cls: MagicMock,
        mock_parse: MagicMock,
        mock_geocode: MagicMock,
        mock_matrix: MagicMock,
        mock_cluster: MagicMock,
        mock_build_day_plans: MagicMock,
        mock_write_json: MagicMock,
        mock_write_map: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        input_path = tmp_path / "places.txt"
        input_path.write_text("Golden Gate Park\n", encoding="utf-8")
        place = _geocoded("Golden Gate Park", 1)
        mock_parse.return_value = ParsedInput(region="San Francisco, CA", places=[place.place])
        mock_geocode.return_value = GeocodingResult(places=[place], warnings=[])
        mock_matrix.return_value = TravelTimeMatrix(
            durations=[[0.0]],
            place_ids=["line_1"],
            primary_source="osrm",
            departure_bucket="2026-07-15T09:00",
        )
        mock_cluster.return_value = ClusterResult(day_assignments=[[0]], num_days=1)
        mock_build_day_plans.return_value = [
            DayPlan(day=1, places=[place], total_travel_seconds=0, route_order=[0])
        ]
        mock_cache_cls.return_value.__enter__.return_value = MagicMock()

        warnings: list[str] = []
        itinerary = run_pipeline(
            input_path=input_path,
            days=1,
            trip_date=date(2026, 7, 15),
            day_start=time(9, 0),
            use_traffic=False,
            on_warning=warnings.append,
        )

        assert itinerary.region == "San Francisco, CA"
        assert itinerary.matrix_source == "osrm"
        mock_geocode.assert_called_once()
        mock_matrix.assert_called_once()
        mock_cluster.assert_called_once()
        mock_build_day_plans.assert_called_once()
        captured = capsys.readouterr()
        assert "TripCluster Itinerary" in captured.out

    @patch("trip_cluster.cli.build_day_plans")
    @patch("trip_cluster.cli.cluster_places")
    @patch("trip_cluster.cli.build_travel_time_matrix")
    @patch("trip_cluster.cli.geocode_places")
    @patch("trip_cluster.cli.parse_input_file")
    @patch("trip_cluster.cli.SQLiteCache")
    def test_warns_for_time_tags_without_traffic(
        self,
        mock_cache_cls: MagicMock,
        mock_parse: MagicMock,
        mock_geocode: MagicMock,
        mock_matrix: MagicMock,
        mock_cluster: MagicMock,
        mock_build_day_plans: MagicMock,
        tmp_path: Path,
    ) -> None:
        input_path = tmp_path / "places.txt"
        input_path.write_text("Mt. Tam @ 6:00am\n", encoding="utf-8")
        place = _geocoded("Mt. Tam", 1, fixed=time(6, 0))
        mock_parse.return_value = ParsedInput(region="San Francisco, CA", places=[place.place])
        mock_geocode.return_value = GeocodingResult(places=[place], warnings=[])
        mock_matrix.return_value = TravelTimeMatrix(
            durations=[[0.0]],
            place_ids=["line_1"],
            primary_source="osrm",
            departure_bucket="2026-07-15T09:00",
        )
        mock_cluster.return_value = ClusterResult(day_assignments=[[0]], num_days=1)
        mock_build_day_plans.return_value = [
            DayPlan(day=1, places=[place], total_travel_seconds=0, route_order=[0])
        ]
        mock_cache_cls.return_value.__enter__.return_value = MagicMock()

        warnings: list[str] = []
        itinerary = run_pipeline(
            input_path=input_path,
            days=1,
            on_warning=warnings.append,
            use_traffic=False,
        )

        assert any("no effect without --traffic" in warning for warning in warnings)
        assert any("no effect without --traffic" in warning for warning in itinerary.warnings)


class TestCliApp:
    def test_exits_nonzero_on_pipeline_error(self, tmp_path: Path) -> None:
        input_path = tmp_path / "places.txt"
        input_path.write_text("Golden Gate Park\n", encoding="utf-8")

        with patch(
            "trip_cluster.cli.run_pipeline",
            side_effect=TripClusterError("geocode failed"),
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["--input", str(input_path)])

        assert result.exit_code == 1
        assert "geocode failed" in result.stderr
