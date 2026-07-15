# TripCluster

Multi-day travel itinerary planner.

Routing uses the free OSRM Table API by default (no API key). Traffic-aware routing via TomTom is optional: set `TRIPCLUSTER_USE_TRAFFIC=true` and `TOMTOM_API_KEY` (or pass `--traffic`).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
trip-cluster --input tests/fixtures/sample_input.txt --days 2
```

## Input file format

Create a plain-text file with one place per line. Optional first line sets geocoding context:

```text
# region: San Francisco, CA
Golden Gate Park
Lands End
Mt. Tam @ 6:00am
Sutro Baths @ 12:30 PM
```

- `# region: ...` — helps Nominatim resolve ambiguous names
- `@ HH:MM` — soft time preference (only affects routing when `--traffic` is on)
- Lines starting with `#` (except the region header) are comments
- Duplicate place lines are skipped with a warning

## CLI flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | — | Path to your places file |
| `--days` | No | `ceil(n/5)` | Number of trip days |
| `--output-map` | No | — | Write a folium HTML map to this path |
| `--output-json` | No | — | Write itinerary JSON to this path |
| `--max-per-day` | No | unlimited | Maximum attractions per day |
| `--day-start` | No | `09:00` | Departure time each day (`HH:MM`) |
| `--trip-date` | No | today | Trip date (`YYYY-MM-DD`) |
| `--cache-db` | No | `~/.tripcluster/cache.db` | SQLite cache path |
| `--traffic` | No | off | Use TomTom traffic-aware routing (needs `TOMTOM_API_KEY`) |
| `--skip-failures` | No | off | Skip failed geocodes instead of aborting |
| `--cluster-method` | No | `agglomerative` | Clustering algorithm (only `agglomerative` in v1) |

### Example with outputs

```bash
trip-cluster --input my_places.txt \
  --days 3 \
  --day-start 06:00 \
  --trip-date 2026-07-15 \
  --output-json itinerary.json \
  --output-map itinerary.html
```

The text summary is always printed to the terminal. JSON and HTML are only written when you pass `--output-json` and `--output-map`.

## Viewing the HTML map

The map is not shown in the terminal — it is a standalone HTML file you choose with `--output-map`:

```bash
trip-cluster --input my_places.txt --days 2 --output-map itinerary.html
open itinerary.html          # macOS
# xdg-open itinerary.html    # Linux
```

The file is written relative to your current working directory (e.g. `trip_cluster/itinerary.html` if you run the command from the project root). Open it in any web browser. No server is required.

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `TRIPCLUSTER_USE_TRAFFIC` | No | `true` to enable TomTom traffic routing (default: off) |
| `TOMTOM_API_KEY` | No | TomTom API key (required only with `--traffic`) |
| `NOMINATIM_USER_AGENT` | Recommended | Contact email for Nominatim usage policy |
| `TRIPCLUSTER_CACHE_DB` | No | Override default cache path |

Copy `.env.example` to `.env` for local secrets (gitignored).

## Testing your own data

```bash
trip-cluster --input /path/to/my_places.txt --days 2 --output-map map.html
```

First run geocodes each place via Nominatim (about 1 request/second) and fetches driving times from OSRM. Results are cached in `~/.tripcluster/cache.db`, so reruns are much faster.

**Tips:**
- Set `# region: Your City, ST` for better geocoding
- Use `--day-start` earlier than any `@time` tags (e.g. `--day-start 06:00` for a `Mt. Tam @ 6:00am` tag)
- `@time` tags only change travel times when `--traffic` is enabled; otherwise you will see a warning
