"""Environment-driven configuration defaults."""

from __future__ import annotations

import os
import re

DEFAULT_CACHE_DB = "~/.tripcluster/cache.db"
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
NOMINATIM_REQUEST_INTERVAL_SECONDS = 1.0
NOMINATIM_MAX_RETRIES = 3
DEFAULT_USER_AGENT = "TripCluster/0.1.0 (personal trip planning tool)"

# If the second result's importance is within this fraction of the top result,
# we warn that the place name may be ambiguous.
AMBIGUITY_IMPORTANCE_RATIO = 0.85

# Nominatim blocks common placeholder contact strings with HTTP 403.
_BLOCKED_USER_AGENT_PATTERNS = (
    re.compile(r"your-email@example\.com", re.IGNORECASE),
    re.compile(r"you@example\.com", re.IGNORECASE),
    re.compile(r"test@example\.com", re.IGNORECASE),
    re.compile(r"@example\.com", re.IGNORECASE),
)


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
