# TripCluster

Multi-day travel itinerary planner. See [scope.md](scope.md) for the technical design.

Routing uses the free OSRM Table API by default (no API key). Traffic-aware routing via TomTom is optional: set `TRIPCLUSTER_USE_TRAFFIC=true` and `TOMTOM_API_KEY` (or pass `--traffic`).
