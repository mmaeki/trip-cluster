from trip_cluster.models import DayPlan, Itinerary
from trip_cluster.output.json_export import (
    itinerary_to_dict,
    itinerary_to_json,
    write_itinerary_json,
)
from trip_cluster.output.map_html import write_itinerary_map
from trip_cluster.output.text import format_itinerary_text


def build_itinerary(
    *,
    region: str | None,
    day_plans: list[DayPlan],
    warnings: list[str],
    matrix_source: str,
) -> Itinerary:
    """Assemble the final itinerary model from upstream pipeline results."""
    return Itinerary(
        region=region,
        days=day_plans,
        warnings=warnings,
        matrix_source=matrix_source,
    )


__all__ = [
    "build_itinerary",
    "format_itinerary_text",
    "itinerary_to_dict",
    "itinerary_to_json",
    "write_itinerary_json",
    "write_itinerary_map",
]
