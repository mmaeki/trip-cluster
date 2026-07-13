"""Environment-driven configuration defaults."""

from __future__ import annotations

import os
import re
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (or cwd) before reading any env vars.
load_dotenv()

DEFAULT_CACHE_DB = "~/.tripcluster/cache.db"
DEFAULT_DAY_START = time(9, 0)
DEFAULT_PLACES_PER_DAY = 5
ASSUMED_SPEED_KPH = 40.0

NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
NOMINATIM_REQUEST_INTERVAL_SECONDS = 1.0
NOMINATIM_MAX_RETRIES = 3
DEFAULT_USER_AGENT = "TripCluster/0.1.0 (personal trip planning tool)"

TOMTOM_MATRIX_URL = "https://api.tomtom.com/routing/matrix/2"
TOMTOM_MAX_RETRIES = 3

OSRM_BASE_URL = "https://router.project-osrm.org"
OSRM_MAX_RETRIES = 3

TWO_OPT_MAX_ITERATIONS = 100
# Soft time-tag penalty: 30 minutes arrival deviation ~= 10 minutes driving time.
TIME_DEVIATION_TARGET_SECONDS = 30 * 60
TIME_DEVIATION_DRIVE_EQUIVALENT_SECONDS = 10 * 60
TIME_DEVIATION_PENALTY_LAMBDA = (
    TIME_DEVIATION_DRIVE_EQUIVALENT_SECONDS / TIME_DEVIATION_TARGET_SECONDS
)
TIME_REFINEMENT_MAX_SWAPS = 50

# If the second result's importance is within this fraction of the top result,
# we warn that the place name may be ambiguous.
AMBIGUITY_IMPORTANCE_RATIO = 0.85

_BLOCKED_USER_AGENT_PATTERNS = (
    re.compile(r"your-email@example\.com", re.IGNORECASE),
    re.compile(r"you@example\.com", re.IGNORECASE),
    re.compile(r"test@example\.com", re.IGNORECASE),
    re.compile(r"@example\.com", re.IGNORECASE),
)

_BLOCKED_API_KEY_VALUES = frozenset({"", "your_key_here", "changeme", "xxx"})


def validate_user_agent(user_agent: str) -> str | None:
    """Return an error message if the User-Agent will likely be rejected by Nominatim."""
    for pattern in _BLOCKED_USER_AGENT_PATTERNS:
        if pattern.search(user_agent):
            return (
                "NOMINATIM_USER_AGENT contains a placeholder email address. "
                "Nominatim rejects these with HTTP 403. "
                "Either unset the variable to use the built-in default, or set it to "
                "a real contact email, e.g. "
                "'TripCluster/0.1.0 (you@gmail.com)'."
            )
    return None


def get_user_agent() -> str:
    configured = os.environ.get("NOMINATIM_USER_AGENT", DEFAULT_USER_AGENT)
    if validate_user_agent(configured):
        return DEFAULT_USER_AGENT
    return configured


def configured_user_agent_issue() -> str | None:
    """Return a warning if NOMINATIM_USER_AGENT is set to a blocked placeholder."""
    configured = os.environ.get("NOMINATIM_USER_AGENT")
    if not configured:
        return None
    return validate_user_agent(configured)


def get_tomtom_api_key() -> str | None:
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if key.lower() in _BLOCKED_API_KEY_VALUES:
        return None
    return key or None


def is_traffic_routing_enabled() -> bool:
    """Return True when traffic-aware TomTom routing is explicitly enabled."""
    value = os.environ.get("TRIPCLUSTER_USE_TRAFFIC", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_cache_db_path() -> Path:
    return Path(os.environ.get("TRIPCLUSTER_CACHE_DB", DEFAULT_CACHE_DB)).expanduser()
