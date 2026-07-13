"""Geocoding helpers for query building and candidate ranking."""

from __future__ import annotations

import re

from trip_cluster.geocoding.aliases import expand_place_alias
from trip_cluster.geocoding.base import GeocodeCandidate
from trip_cluster.matrix.haversine import haversine_km

# Reject geocodes implausibly far from places already resolved in this trip.
MAX_DISTANCE_FROM_ANCHOR_KM = 250.0


def build_query(name: str, region: str | None) -> str:
    if region:
        return f"{name}, {region}"
    return name


def build_fallback_queries(name: str, region: str | None) -> list[str]:
    """Ordered queries to try when the primary regional query returns nothing."""
    expanded = expand_place_alias(name)
    queries: list[str] = []
    seen: set[str] = set()

    def add(query: str) -> None:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            queries.append(normalized)

    if region:
        parts = [part.strip() for part in region.split(",") if part.strip()]
        state = parts[-1] if parts else None
        if state:
            add(f"{name}, {state}")
            add(f"{expanded}, {state}")
        add(f"{expanded}, {region}")
        if state and len(state) == 2 and state.isalpha():
            # Expand "CA" -> "California" for better Nominatim hits on landmarks.
            full_state = _US_STATE_NAMES.get(state.upper())
            if full_state:
                add(f"{expanded}, {full_state}")

    add(expanded)
    # Bare name last — often ambiguous (e.g. "Mt. Tam" -> Australia).
    add(name)
    return queries


def pick_best_candidate(
    candidates: list[GeocodeCandidate],
    *,
    region: str | None,
    anchor_points: list[tuple[float, float]],
) -> GeocodeCandidate:
    """Choose the best geocode, preferring candidates near the trip."""
    if not candidates:
        raise ValueError("candidates must not be empty")

    if anchor_points:
        centroid_lat = sum(lat for lat, _ in anchor_points) / len(anchor_points)
        centroid_lng = sum(lng for _, lng in anchor_points) / len(anchor_points)

        nearby = [
            c
            for c in candidates
            if haversine_km(centroid_lat, centroid_lng, c.lat, c.lng) <= MAX_DISTANCE_FROM_ANCHOR_KM
        ]
        if nearby:
            return min(
                nearby,
                key=lambda c: haversine_km(centroid_lat, centroid_lng, c.lat, c.lng),
            )
        # All candidates are far away — still pick closest to trip, but caller may warn.
        return min(
            candidates,
            key=lambda c: haversine_km(centroid_lat, centroid_lng, c.lat, c.lng),
        )

    if region:
        region_tokens = {token.lower() for token in re.split(r"[\s,]+", region) if token}
        regional = [
            c
            for c in candidates
            if any(token in c.formatted_address.lower() for token in region_tokens)
        ]
        if regional:
            return max(regional, key=lambda c: c.importance)

    return max(candidates, key=lambda c: c.importance)


_US_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
