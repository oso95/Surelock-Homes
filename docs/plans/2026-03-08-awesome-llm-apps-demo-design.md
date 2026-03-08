# Surelock Homes Demo for awesome-llm-apps

**Date:** 2026-03-08
**Goal:** Create a self-contained demo of Surelock Homes suitable for inclusion in [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) under `advanced_ai_agents/single_agent_apps/ai_fraud_investigation_agent/`.

## Context

- awesome-llm-apps has 18k+ stars and no fraud detection / public records investigation agent
- Closest projects: AI Legal Agent Team, AI VC Due Diligence Agent Team — none do autonomous physical-evidence fraud investigation
- The repo's dominant pattern: single Python file + Streamlit UI + agno framework + requirements.txt + README.md

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Target state | Illinois | DCFS provider lookup is API-based (no local CSV files needed) |
| LLM provider | OpenRouter | OpenAI-compatible SDK, broad model access, matches repo conventions |
| Google APIs | Included | Street View + Places are core to the investigation "wow factor" |
| UI framework | Streamlit | What everyone else in the repo uses |
| Agent framework | agno | Dominant framework in the repo |
| Streaming | Real-time narration | Core Surelock experience — agent narrates its thinking as it investigates |
| File structure | Single file | Matches most examples in the repo |

## File Structure

```
ai_fraud_investigation_agent/
├── fraud_investigation_agent.py  (~300 lines)
├── requirements.txt
└── README.md
```

## Architecture

### Agent Setup

- **Framework:** agno with `OpenRouter(id="anthropic/claude-sonnet-4-20250514")`
- **Custom tools:** 7 Python functions registered via agno's `tools=[]`
- **System prompt:** Full Surelock investigation prompt embedded as `description` + `instructions`
- **Streaming:** `agent.run(stream=True)` piped into Streamlit chat container

### Tools (7)

1. **`search_childcare_providers(zip_code, state)`** — Illinois DCFS API lookup, returns provider list with name, address, capacity, license type
2. **`get_property_data(address, county, state)`** — Cook County GIS for building sqft, zoning, lot size, year built
3. **`calculate_max_capacity(building_sqft, state)`** — Pure math: `(sqft * 0.65) / 35`, returns max legal capacity with calculation shown
4. **`get_street_view(address)`** — Google Street View image (base64 JPEG)
5. **`get_places_info(address, name)`** — Google Places business type, status, rating, reviews
6. **`geocode_address(address)`** — Google Maps geocoding, returns lat/lng + formatted address
7. **`check_business_registration(name, state)`** — Secretary of State entity lookup, returns incorporation date, registered agent, status

### Streamlit UI

- **Sidebar:**
  - OpenRouter API key (password input)
  - Google Maps API key (password input)
  - State selector (Illinois pre-selected, expandable later)
  - ZIP code text input
  - "Investigate" button
- **Main area:**
  - Streaming narration in chat-style container
  - Agent's investigation unfolds in real-time
- **Footer:**
  - Link to full Surelock Homes repo

### Data Flow

1. User enters ZIP code (e.g., `60612`) + hits "Investigate"
2. Agent calls `search_childcare_providers` → gets provider list
3. For each provider (capped at first 10 in ZIP):
   - Property data → capacity calculation → street view → places info
   - Business registration cross-referencing when patterns emerge
4. Agent narrates findings, flags anomalies, discovers cross-provider patterns
5. Final summary with flagged providers and confidence levels

### Kept from Full Surelock

- Full system prompt (battle-tested, drives investigation quality)
- All 7 core investigation tools
- Context trimming logic (prevents context window overflow on large ZIPs)
- Streaming narration with investigation-style thinking
- Guardrails (never says "fraud", presents findings as leads)

### Removed from Full Surelock (justified)

| Removed | Why |
|---------|-----|
| Minnesota support | Requires CSV data files, not self-contained |
| Offline mode | Demo is always online |
| Satellite view tool | Street view sufficient for demo |
| FastAPI backend | Streamlit replaces it |
| Output file saving | Not needed for demo |
| Frontend (HTML/JS/CSS) | Streamlit replaces it |
| GitHub Pages publishing | Not applicable |
| Multi-county property modules | Cook County only for Illinois demo |

## Requirements

```
agno
openai
streamlit
requests
beautifulsoup4
```

## README Structure

Following the repo's convention (see journalist_agent README):

1. Title with emoji: `## 🔍 AI Fraud Investigation Agent`
2. Description (2-3 sentences)
3. Features (bullet list)
4. How to get Started (clone, install, API keys, run)
5. How it Works (3-4 component descriptions)
