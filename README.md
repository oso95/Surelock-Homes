# Surelock Homes

## Overview

This repository implements a complete prototype of **Surelock Homes** from the supplied specification.

It includes:

- Python backend with a FastAPI API.
- An investigation loop scaffolded for Anthropic Opus tool-use (with a deterministic offline fallback).
- All eight tool modules from the spec with CSV/JSON fallbacks.
- Data download/scrape/cache helper scripts.
- A small browser frontend to submit investigation queries and display outputs.
- Test suite for backend logic and UI/API integration.

## Project structure

```
README.md
requirements.txt
.env.example
run.py
backend_api.py
agent/
  __init__.py
  loop.py
  prompt.py
  narration.py
tools/
  __init__.py
  definitions.py
  providers.py
  property.py
  street_view.py
  places.py
  licensing.py
  business_reg.py
  capacity.py
  geocoding.py
scripts/
  download_mn_data.py
  scrape_il_providers.py
  download_parcels.py
  cache_street_view.py
data/
  mn_providers.csv
  il_providers.csv
  hennepin_parcels.csv
  cook_parcels.csv
  business_registration.csv
  mn_licensing.csv
  il_licensing.csv
  ccap_rates.json
  cached_street_view/
frontend/
  index.html
  app.js
  style.css
tests/
  test_capacity.py
  test_tools.py
  test_loop.py
  test_api.py
output/
  .gitkeep
```

## Quickstart

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables (optional for live APIs):

```bash
cp .env.example .env
```

Set `LLM_PROVIDER` to `anthropic` or `openrouter`.
When using OpenRouter:

```bash
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
MODEL=anthropic/claude-opus-4-6
```

4. Start the API:

```bash
uvicorn backend_api:app --reload
```

5. Open `http://127.0.0.1:8000`.

6. Run tests:

```bash
pytest
```

## API

- `GET /api/health`
- `GET /api/tool-definitions`
- `POST /api/investigate`

Request body:

```json
{
  "query": "Investigate Illinois providers in ZIP 60612",
  "max_turns": 6,
  "offline": true
}
```

`offline` is recommended for deterministic local runs in CI.

## Running scripts

- `python scripts/download_mn_data.py`
- `python scripts/scrape_il_providers.py`
- `python scripts/download_parcels.py`
- `python scripts/cache_street_view.py`

These scripts are defensive and will create/refresh local cache files, using the bundled sample data when external sources are unavailable.

## Notes

- The implementation is fully functional without external API keys by using local fallback datasets.
- When keys are provided, tool wrappers can call real Google/Anthropic endpoints.
- This is a functional MVP matching the provided spec and includes all required modules for extension.
