# Surelock Homes

Surelock Homes is an open-source investigation dashboard for childcare-provider anomaly research.

It combines:
- a FastAPI backend
- a browser UI with streaming progress
- tool-driven investigations (online or offline)
- exportable run artifacts and static report pages

## Why this exists

The goal is to speed up lead generation from public data.  
This project helps surface inconsistencies; it does **not** make legal or fraud determinations.

## Features

- Online mode (LLM + tools)
- Offline mode (deterministic, local-data workflow)
- Streaming investigation updates in UI
- Saved run artifacts in `output/<run_id>/`
- Static report data for GitHub Pages in `docs/data/`
- OpenRouter support (default) and Anthropic support

## Current setup notes

- Backend/UI run from FastAPI + docs site workflow (no Streamlit app).
- System prompt file is `prompts/system-prompt.md`.
- Final report generation prompt is in `agent/loop.py`.
- LLM context trimming is controlled by `LLM_MAX_CONTEXT_CHARS` in `.env`.

## Quick Start

```bash
git clone <your-fork-or-repo-url>
cd Surelock-Homes
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend_api:app --reload
```

Open:
- Dashboard: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Health: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

## Configuration

### LLM provider

`.env.example` defaults to OpenRouter:

```bash
LLM_PROVIDER=openrouter
MODEL=anthropic/claude-opus-4.6
OPENROUTER_API_KEY=
LLM_MAX_CONTEXT_CHARS=1000000
```

Anthropic option:

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
MODEL=claude-opus-4-6-20250514
```

`LLM_MAX_CONTEXT_CHARS` controls message-history trimming before each LLM call:
- `1000000` works well for 1M-context models
- `0` disables trimming entirely

### Prompt files

- System prompt: `prompts/system-prompt.md`
- Final report prompt template: `agent/loop.py` (`_REPORT_GENERATION_PROMPT_TEMPLATE`)

### Google Maps

```bash
GOOGLE_MAPS_API_KEY=
```

Used by geocoding, places, street view, and satellite tools.

## Running investigations

### UI

Use the dashboard for most workflows:
- prompt
- online/offline toggle
- max turns
- live progress stream
- report and investigation tabs

### CLI

```bash
python3 run.py "Investigate Illinois providers in ZIP 60612" --max-turns 8
python3 run.py "Investigate Minnesota providers in ZIP 55401" --offline --max-turns 8
```

## API

- `GET /api/health`
- `GET /api/tool-definitions`
- `POST /api/investigate`
- `POST /api/investigate/stream`

Stream example:

```bash
curl -N -X POST http://127.0.0.1:8000/api/investigate/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"Investigate Illinois providers in ZIP 60612","max_turns":12,"offline":false}'
```

## Output and GitHub Pages flow

Each run writes:
- `output/<run_id>/result.json`
- `output/<run_id>/narration.md`
- `output/<run_id>/tool_calls.json`

After saving a run, the app refreshes static report data:
- `docs/data/runs.json`
- `docs/data/runs/<run_id>.json`

GitHub Pages serves `docs/`, so make sure you commit and push `docs/data/*` (and `output/*` if you want run artifacts versioned).

Manual rebuild (optional):

```bash
python3 scripts/build_pages.py
```

## Repository layout

```text
agent/         Investigation orchestration
tools/         Data and evidence tools
frontend/      Main app UI
docs/          Static site for published reports
scripts/       Data/build utilities
prompts/       System and investigation prompts
output/        Saved run artifacts
tests/         Test suite
```

## Testing

```bash
PYTHONPATH=. pytest -q
```

## Contributing

Contributions are welcome.

Please:
1. Fork and create a feature branch.
2. Keep changes scoped and include tests for behavior changes.
3. Run the test suite before opening a PR.
4. Update docs when config, behavior, or outputs change.
5. In your PR, include:
   - what changed
   - why it changed
   - how you validated it

Contribution expectations:
- Do not commit secrets (`.env`, real API keys).
- Avoid committing runtime-only cache artifacts.
- Treat outputs as investigative leads, not final determinations.

## Notes

- This project relies on public/external datasets that can be incomplete or temporarily unavailable.
- Offline mode is useful for testing pipeline behavior when live services are down.
