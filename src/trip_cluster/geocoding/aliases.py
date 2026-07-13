"""Common place-name expansions for geocoding."""

from __future__ import annotations

# Keys are normalized: lowercase, collapsed whitespace.
_ALIASES: dict[str, str] = {
    "mt. tam": "Mount Tamalpais",
    "mt tam": "Mount Tamalpais",
    "mt. tamalpais": "Mount Tamalpais",
    "ggp": "Golden Gate Park",
}


def expand_place_alias(name: str) -> str:
    """Return a fuller name for known abbreviations, or the original name."""
    key = " ".join(name.strip().lower().split())
    return _ALIASES.get(key, name.strip())
