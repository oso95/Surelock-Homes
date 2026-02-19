# Surelock Homes

Surelock Homes is a FastAPI + browser dashboard for investigating childcare provider anomalies using tool-driven analysis, live streaming progress, and fallback datasets.

It is built for practical workflows:
- Run fully offline with deterministic local data.
- Run live with an LLM provider (`openrouter` or `anthropic`) and external APIs.
- Review evidence, tool calls, and narration in one UI.

✅ Works offline without paid APIs.  
⚠️ Live results depend on external service availability and data quality.

## What This Project Does

Surelock Homes investigates provider records and related evidence to surface potential anomalies such as:
- licensing/type/capacity inconsistencies
- missing business/listing footprint
- suspicious address or geocode mismatches
- capacity estimates vs. parcel/property constraints

The app combines:
- a tool-using investigation loop (`agent/loop.py`)
- eight domain tools (`tools/`)
- streaming API events (`/api/investigate/stream`)
- a frontend timeline with activity logs and history (`frontend/`)

## Key Capabilities

- Dual execution modes:
  - `online` (LLM orchestrates tool calls)
  - `offline` (deterministic local pipeline)
- Two LLM backends:
  - OpenRouter (default in `.env.example`)
  - Anthropic (optional)
- Real-time stream UX:
  - turn starts, tool calls, tool results, errors, completion payload
- Evidence-rich output:
  - narration markdown, raw tool call records, thinking trace, flags
- Fallback strategy:
  - local CSV/JSON data used when GIS/Google/live endpoints fail or timeout

## Architecture

1. Frontend sends query to API.
2. API chooses online or offline path.
3. Investigation loop runs tools and builds narrative.
4. Stream endpoint emits progress events to UI.
5. Final payload is rendered and optionally persisted under `output/<run_id>/`.

Main runtime files:
- `backend_api.py`: FastAPI routes + SSE wrapper + rate limiting
- `agent/loop.py`: orchestration logic (OpenRouter, Anthropic, offline)
- `agent/narration.py`: narrative builder
- `tools/*.py`: domain tool implementations
- `frontend/index.html`, `frontend/app.js`, `frontend/style.css`: dashboard UI

## LLM Provider Configuration

### Default behavior

- `.env.example` is configured for OpenRouter by default:
  - `LLM_PROVIDER=openrouter`
  - `MODEL=anthropic/claude-opus-4.6`
- Code-level fallback in `config.py` is `anthropic` if `LLM_PROVIDER` is completely missing.

Recommended: always set `LLM_PROVIDER` explicitly in `.env`.

### OpenRouter (recommended default)

```bash
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_SITE_URL=http://localhost:8000
OPENROUTER_APP_NAME=Surelock Homes
MODEL=anthropic/claude-opus-4.6
```

### Anthropic

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_anthropic_key
MODEL=claude-opus-4-6-20250514
```

### Offline mode (no LLM key required)

Set `offline: true` in request payload (or use the UI toggle). This bypasses both OpenRouter and Anthropic.

## Google Maps API Configuration

Google Maps is used by live tool calls for:
- geocoding (`geocode_address`)
- Places lookup (`get_places_info`)
- Street View capture (`get_street_view`)

Set this in `.env`:

```bash
GOOGLE_MAPS_API_KEY=your_google_maps_key
```

Recommended Google Cloud APIs to enable:
- `Geocoding API`
- `Places API`
- `Street View Static API`

If `GOOGLE_MAPS_API_KEY` is missing or invalid:
- the app still runs
- Google-powered tools return fallback/error-style responses
- investigations rely more heavily on local CSV/cache data

## Requirements

- Python 3.11+
- `pip`
- Optional API keys:
  - `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`
  - `GOOGLE_MAPS_API_KEY` for Places/Geocoding/Street View live calls

Install dependencies:

```bash
pip install -r requirements.txt
```

## Quick Start

1. Clone and enter repo.
2. Create virtual environment.
3. Install dependencies.
4. Configure env.
5. Start API.
6. Open dashboard.

```bash
cd /path/to/Surelock-Homes
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend_api:app --reload
```

Dashboard:
- `http://127.0.0.1:8000`

Health check:

```bash
curl http://127.0.0.1:8000/api/health
```

## API Endpoints

- `GET /api/health`
- `GET /api/tool-definitions`
- `POST /api/investigate`
- `POST /api/investigate/stream`
- `GET /` (frontend)

### `POST /api/investigate`

Request:

```json
{
  "query": "Investigate Illinois providers in ZIP 60612",
  "max_turns": 12,
  "offline": false
}
```

Notes:
- `max_turns` API bounds are `1..50`.
- non-stream route returns a single final payload.

### `POST /api/investigate/stream` (SSE)

Use for best UX:

```bash
curl -N -X POST http://127.0.0.1:8000/api/investigate/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"Investigate Illinois providers in ZIP 60612","max_turns":12,"offline":false}'
```

Common SSE events:
- `start`
- `turn_start`
- `assistant_text`
- `tool_call`
- `tool_result`
- `tool_payload`
- `tool_error`
- `providers_loaded` / `provider_start` / `provider_done` (offline path)
- `error`
- `complete`

## CLI Usage

Run single investigation from terminal:

```bash
python run.py "Investigate Illinois providers in ZIP 60612" --max-turns 8
python run.py "Investigate Illinois providers in ZIP 60612" --offline --max-turns 8
```

## Output Format

Final payload typically includes:
- `query`
- `mode` (`agent` or `offline`)
- `status` (`complete` or `error`)
- `turns`
- `provider_count`
- `flagged` (list)
- `narration` (markdown)
- `assistant_text`
- `tool_calls`
- `thinking`
- `raw_turns`
- `error` (if failure)

When saving is enabled in loop execution, results are written to:
- `output/<UTC_RUN_ID>/result.json`
- `output/<UTC_RUN_ID>/narration.md`
- `output/<UTC_RUN_ID>/tool_calls.json`

## Tooling Surface

`tools/definitions.py` exposes 8 tools:

1. `search_childcare_providers`
2. `get_property_data`
3. `get_street_view`
4. `get_places_info`
5. `check_licensing_status`
6. `check_business_registration`
7. `calculate_max_capacity`
8. `geocode_address`

Implementation notes:
- Many tools attempt live lookup first, then fallback to local data.
- Some tools return structured lists (not only dicts), and stream payload handling is normalized in `agent/loop.py`.

## Data and Cache

Primary local data directory:
- `data/mn_providers.csv`
- `data/il_providers.csv`
- `data/mn_licensing.csv`
- `data/il_licensing.csv`
- `data/hennepin_parcels.csv`
- `data/cook_parcels.csv`
- `data/business_registration.csv`
- `data/ccap_rates.json`
- `data/cached_street_view/*.json`

Live-augmented cache files may also be present:
- `data/mn_providers_live.csv`
- `data/il_providers_live.csv`

## Utility Scripts

```bash
python scripts/download_mn_data.py
python scripts/scrape_il_providers.py
python scripts/download_parcels.py
python scripts/cache_street_view.py
```

These scripts refresh local artifacts and are designed to degrade gracefully if sources are partially unavailable.

## Frontend UX Notes

The dashboard includes:
- online/offline toggle
- streaming activity log
- report/investigation tabs
- metrics strip + flagged providers list
- tool call evidence cards
- local history with replay (stored in browser localStorage)

## Environment Variables

Core:
- `LLM_PROVIDER` (`openrouter` or `anthropic`)
- `MODEL`
- `OPENROUTER_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_MAPS_API_KEY`

Operational:
- `THINKING_BUDGET_TOKENS`
- `MAX_TOKENS`
- `TOOL_TIMEOUT_SECONDS`
- `GIS_TIMEOUT_SECONDS`
- `GOOGLE_API_TIMEOUT_SECONDS`
- `SOCRATA_TIMEOUT_SECONDS`
- `PROBE_TIMEOUT_SECONDS`
- `CACHE_MAX_AGE_HOURS`
- `RATE_LIMIT_MAX`
- `RATE_LIMIT_WINDOW`

## Testing

Run test suite:

```bash
python -m pytest
```

If tests fail due to missing packages, reinstall dependencies:

```bash
pip install -r requirements.txt
```

## Troubleshooting

### `Investigation failed. Check network/backend.`

- Check API server is running.
- Verify `/api/health` response.
- Validate `.env` keys.
- Try `offline: true` to isolate provider/network issues.

### Google/Places/Street View mismatches

- Address geocoding can resolve to nearby canonical addresses.
- A missing Google Business listing is not proof the provider is fake.
- Use licensing + registration + parcel context before drawing conclusions.

### GIS endpoint timeouts

- County GIS endpoints can be intermittent.
- App is designed to fallback to local parcel CSV data when live GIS fails.

### HTTP 429 rate limit

- In-memory limiter is enabled in API.
- Default values come from `RATE_LIMIT_MAX` and `RATE_LIMIT_WINDOW`.

## Limitations and Interpretation

- This is an investigative assist tool, not a fraud adjudication engine.
- Public data can be stale, incomplete, or inconsistent across systems.
- External API outages/timeouts can reduce confidence for individual checks.
- Treat output as leads requiring human verification.

## Project Structure

```
README.md
requirements.txt
.env.example
run.py
backend_api.py
agent/
tools/
scripts/
data/
frontend/
tests/
output/
```

## Security and Ops Notes

- Do not commit real API keys.
- Keep `.env` local.
- Review generated outputs before sharing externally.
- Consider adding server-side auth if deployed beyond local/dev usage.
