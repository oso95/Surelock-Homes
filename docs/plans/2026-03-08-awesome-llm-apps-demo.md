# Surelock Homes — awesome-llm-apps Demo Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a self-contained Streamlit demo of Surelock Homes for inclusion in awesome-llm-apps under `advanced_ai_agents/single_agent_apps/ai_fraud_investigation_agent/`.

**Architecture:** Single-file agno agent with 7 custom tool functions, OpenRouter as LLM provider, Streamlit for UI with streaming narration. Tools extracted and simplified from the full Surelock codebase. Full system prompt preserved. Context trimming included.

**Tech Stack:** Python, agno, OpenRouter, Streamlit, requests, beautifulsoup4

---

### Task 1: Create project directory and requirements.txt

**Files:**
- Create: `demo/ai_fraud_investigation_agent/requirements.txt`

**Step 1: Create the directory structure**

```bash
mkdir -p demo/ai_fraud_investigation_agent
```

**Step 2: Write requirements.txt**

```
agno
openai
streamlit
requests
beautifulsoup4
```

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/requirements.txt
git commit -m "chore: scaffold demo directory for awesome-llm-apps submission"
```

---

### Task 2: Build the fraud_investigation_agent.py — imports, config, and system prompt

**Files:**
- Create: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Write the file skeleton with imports, constants, and the full system prompt**

The file starts with:
- Imports: `streamlit`, `agno`, `requests`, `beautifulsoup4`, `json`, `base64`, `re`, `os`
- System prompt: the full content from `prompts/system-prompt.md` embedded as a triple-quoted string constant `SYSTEM_PROMPT`
- Replace `{dynamic_date}` with a runtime `datetime.now().strftime("%Y-%m-%d")`
- Config constants: `CONTEXT_BUDGET_CHARS = 800_000`, `MAX_PROVIDER_CAP = 10`

Source reference: `prompts/system-prompt.md` (copy verbatim, all 319 lines)

**Step 2: Verify the file loads without errors**

```bash
cd demo/ai_fraud_investigation_agent && python -c "import fraud_investigation_agent" && cd ../..
```

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add demo skeleton with system prompt and imports"
```

---

### Task 3: Implement tool functions — search_childcare_providers

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add the `search_childcare_providers` function**

This tool queries the Illinois DCFS provider lookup page. Extracted from `tools/providers.py:277-314` (`_load_il_live_records`) and the `search_childcare_providers` entry point in `tools/providers.py`.

The function should:
1. POST to `https://sunshine.dcfs.illinois.gov/Content/Licensing/Daycare/ProviderLookup.aspx` with VIEWSTATE form fields
2. Parse the HTML response table for provider rows
3. Filter by ZIP code if provided
4. Return a list of dicts with: `name`, `address`, `city`, `zip`, `capacity`, `license_type`, `status`, `state`

Key implementation detail from source: the DCFS page uses ASP.NET viewstate. The function must first GET the page to extract `__VIEWSTATE` and `__EVENTVALIDATION`, then POST with `__EVENTTARGET=ctl00$ContentPlaceHolderContent$ASPxSearch`.

Docstring format for agno tool registration:
```python
def search_childcare_providers(zip_code: str, state: str = "IL") -> str:
    """Search for licensed childcare providers in a target ZIP code area.

    Args:
        zip_code: 5-digit ZIP code to search
        state: State abbreviation (currently supports IL)
    """
```

Return `json.dumps(result)` — agno tools return strings.

**Step 2: Test the function manually**

```bash
cd demo/ai_fraud_investigation_agent && python -c "
from fraud_investigation_agent import search_childcare_providers
import json
result = json.loads(search_childcare_providers('60612'))
print(f'Found {len(result.get(\"providers\", []))} providers')
" && cd ../..
```

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add search_childcare_providers tool (IL DCFS)"
```

---

### Task 4: Implement tool functions — get_property_data

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add the `get_property_data` function**

Simplified from `tools/property.py`. For the demo, only Cook County (IL) is supported via Socrata Open Data APIs.

The function should:
1. Query Cook County address endpoint: `https://datacatalog.cookcountyil.gov/resource/3723-97qp.json` with `$where=UPPER(addr) LIKE '%{street}%'`
2. Use the returned PIN to query residential chars: `https://datacatalog.cookcountyil.gov/resource/x54s-btds.json`
3. If no residential match, try commercial: `https://datacatalog.cookcountyil.gov/resource/csik-bsws.json`
4. Return: `building_sqft`, `lot_size`, `zoning`, `property_class`, `year_built`, `county`, `state`

Source reference: `tools/property.py:42-47` for Socrata URLs, `tools/property_live_cook.py` for the query logic.

```python
def get_property_data(address: str, county: str = "Cook", state: str = "IL") -> str:
    """Get building and parcel data for a specific address from county GIS records.

    Args:
        address: Full street address
        county: County name (default: Cook)
        state: State abbreviation (default: IL)
    """
```

**Step 2: Test manually**

```bash
cd demo/ai_fraud_investigation_agent && python -c "
from fraud_investigation_agent import get_property_data
import json
result = json.loads(get_property_data('123 N State St, Chicago, IL'))
print(json.dumps(result, indent=2))
" && cd ../..
```

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add get_property_data tool (Cook County Socrata)"
```

---

### Task 5: Implement tool functions — calculate_max_capacity

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add the `calculate_max_capacity` function**

Direct port from `tools/capacity.py` (it's only 50 lines). Pure math, no external dependencies.

```python
def calculate_max_capacity(building_sqft: float, state: str = "IL", usable_ratio: float = 0.65) -> str:
    """Calculate the maximum legal childcare capacity for a building based on square footage and state building code requirements.

    Args:
        building_sqft: Total building square footage
        state: State abbreviation (IL or MN)
        usable_ratio: Estimated ratio of usable childcare space to total building sqft (default: 0.65)
    """
```

Returns JSON with: `building_sqft`, `usable_ratio`, `usable_sqft`, `sqft_per_child_required`, `max_legal_capacity`, `regulation`, `calculation`.

**Step 2: Test**

```bash
cd demo/ai_fraud_investigation_agent && python -c "
from fraud_investigation_agent import calculate_max_capacity
print(calculate_max_capacity(1200, 'IL'))
" && cd ../..
```

Expected output should show `max_legal_capacity: 22` (1200 * 0.65 / 35 = 22).

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add calculate_max_capacity tool"
```

---

### Task 6: Implement tool functions — geocode_address, get_street_view, get_places_info

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add `geocode_address`**

Simplified from `tools/geocoding.py`. Calls Google Maps Geocoding API. Requires `GOOGLE_MAPS_API_KEY` from Streamlit session state.

```python
def geocode_address(address: str) -> str:
    """Convert a street address to geographic coordinates (latitude/longitude).

    Args:
        address: Full street address to geocode
    """
```

**Step 2: Add `get_street_view`**

Simplified from `tools/street_view.py`. Fetches Street View images from Google. Returns base64-encoded JPEGs.

```python
def get_street_view(address: str, headings: list = None) -> str:
    """Capture Google Street View images of a location from multiple angles.

    Args:
        address: Street address to photograph
        headings: Camera headings in degrees (default: [0, 90, 180, 270])
    """
```

Note: images returned as base64 strings in the JSON response. The agent can analyze these visually through agno's multimodal support if the model supports it, otherwise the metadata (capture_date, status) provides context.

**Step 3: Add `get_places_info`**

Simplified from `tools/places.py`. Uses Google Places API (Find Place + Place Details).

```python
def get_places_info(address: str, name: str = "") -> str:
    """Get Google Places data for an address including business type, operating status, rating, and reviews.

    Args:
        address: Street address to look up
        name: Business or provider name to search for (improves match accuracy)
    """
```

Key logic to preserve from source:
- The `_find_place_candidates` query plan: search by name first, then childcare keywords, then raw address
- Address house number validation (reject mismatched results)
- Fallback when no Google API key is provided

**Step 4: Test each tool**

```bash
cd demo/ai_fraud_investigation_agent && python -c "
from fraud_investigation_agent import geocode_address, get_places_info
import json, os
# These will return fallback results without API key
print(json.loads(geocode_address('123 N State St, Chicago, IL'))['status'])
print(json.loads(get_places_info('123 N State St, Chicago, IL'))['status'])
" && cd ../..
```

**Step 5: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add geocode, street_view, and places_info tools"
```

---

### Task 7: Implement tool functions — check_business_registration

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add `check_business_registration`**

Simplified from `tools/business_reg.py`. For IL, probes the CyberDriveIllinois API.

```python
def check_business_registration(name: str, state: str = "IL", search_type: str = "business") -> str:
    """Look up business entity registration with Secretary of State.

    Args:
        name: Business name or person name (for agent search)
        state: State abbreviation
        search_type: Search by 'business' name or by registered 'agent' name
    """
```

The IL SOS API (`cyberdriveillinois.com/corpservices/api/entitysearch`) may return 403 (CDN firewall). The tool should handle this gracefully and return a note about limited availability — this matches the current Surelock behavior (see `tools/business_reg.py:158-176`).

**Step 2: Test**

```bash
cd demo/ai_fraud_investigation_agent && python -c "
from fraud_investigation_agent import check_business_registration
import json
result = json.loads(check_business_registration('Test Corp', 'IL'))
print(result.get('status'))
" && cd ../..
```

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add check_business_registration tool"
```

---

### Task 8: Build the agent and context trimming logic

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add context trimming helper**

Port `_enforce_context_budget` from `agent/loop.py:1313-1328`:

```python
def _enforce_context_budget(messages: list, max_chars: int = 800_000) -> None:
    """Drop older messages to stay within context budget."""
    import json as _json
    if max_chars <= 0:
        return
    keep_tail = 4
    while len(_json.dumps(messages, ensure_ascii=False)) > max_chars and len(messages) > (1 + keep_tail + 1):
        dropped = len(messages) - 1 - keep_tail
        messages[1:1 + dropped] = [
            {"role": "user", "content": f"[{dropped} earlier messages removed to fit context budget]"}
        ]
    while len(messages) > 2 and messages[2].get("role") == "tool":
        messages.pop(2)
```

**Step 2: Build the agno Agent**

Create the agent using agno's `Agent` class with `OpenRouter` model and all 7 tools:

```python
from agno.agent import Agent
from agno.models.openrouter import OpenRouter

agent = Agent(
    model=OpenRouter(id=model_id, api_key=openrouter_key),
    tools=[
        search_childcare_providers,
        get_property_data,
        calculate_max_capacity,
        geocode_address,
        get_street_view,
        get_places_info,
        check_business_registration,
    ],
    description=SYSTEM_PROMPT,
    instructions=[
        "Investigate ALL providers in the ZIP code, not just the first few.",
        "For each provider: check property data, calculate capacity, get street view and places info.",
        "Cross-reference business registrations when you notice patterns (shared owners, agents).",
        "Narrate your thinking as you investigate — the narration IS the product.",
        "Never say 'fraud' — use 'anomaly', 'requires further investigation', 'flags'.",
    ],
    markdown=True,
    show_tool_calls=True,
)
```

Note: agno handles the tool-calling loop internally. However, we need to determine whether agno's built-in loop handles context trimming or if we need to hook into it. If agno doesn't expose message history for trimming, we may need to use the raw OpenAI client instead and manage the loop ourselves (like the full Surelock does in `_run_openai_investigation`).

**Decision point:** If agno's agent loop doesn't support context trimming mid-conversation, fall back to a manual loop using `openai.OpenAI` with OpenRouter base URL — this matches `agent/loop.py:1682-1850` and gives us full control. The agno Agent class would still be listed in requirements for framework consistency, but the actual loop would be manual.

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add agent setup and context trimming"
```

---

### Task 9: Build the Streamlit UI

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: Add the Streamlit UI at the bottom of the file**

```python
# ── Streamlit App ──────────────────────────────────────────────────

st.set_page_config(page_title="Surelock Homes — AI Fraud Investigation Agent", page_icon="🔍", layout="wide")

st.title("🔍 AI Fraud Investigation Agent")
st.caption(
    "Autonomous childcare provider fraud investigation using public records, "
    "property data, and Google Maps. Powered by Claude via OpenRouter."
)

# Sidebar
with st.sidebar:
    st.header("Configuration")
    openrouter_key = st.text_input("OpenRouter API Key", type="password", help="Get one at openrouter.ai")
    google_key = st.text_input("Google Maps API Key", type="password", help="Needs Geocoding, Places, and Street View APIs enabled")
    model_id = st.selectbox("Model", [
        "anthropic/claude-sonnet-4-20250514",
        "anthropic/claude-opus-4-6-20250514",
        "openai/gpt-4o",
    ], index=0)
    zip_code = st.text_input("ZIP Code", value="60612", help="Illinois ZIP code to investigate")
    max_turns = st.slider("Max Investigation Turns", 3, 15, 8)
    investigate = st.button("🔍 Investigate", type="primary", disabled=not openrouter_key)

    st.divider()
    st.markdown("Built with [Surelock Homes](https://github.com/osobodev/Surelock-Homes)")

# Main area
if investigate and openrouter_key:
    # Store API keys for tool functions to access
    st.session_state["google_maps_api_key"] = google_key or ""

    query = f"Investigate childcare providers in ZIP code {zip_code} in Illinois."

    with st.status("🔍 Investigating...", expanded=True) as status:
        # Run agent and stream narration
        response = agent.run(query, stream=True)
        narration_container = st.empty()
        full_narration = ""
        for chunk in response:
            if chunk.content:
                full_narration += chunk.content
                narration_container.markdown(full_narration)
        status.update(label="Investigation complete", state="complete")

    st.markdown("---")
    st.markdown(full_narration)
```

Note: The tool functions need access to the Google Maps API key. Since agno tools are plain functions, we use `st.session_state["google_maps_api_key"]` as the mechanism — each tool reads from session state (or `os.environ`).

**Step 2: Test the Streamlit app locally**

```bash
cd demo/ai_fraud_investigation_agent && streamlit run fraud_investigation_agent.py && cd ../..
```

Verify:
- Sidebar renders with all inputs
- Entering API keys + clicking Investigate starts the agent
- Narration streams in real-time
- Tool calls are visible (agno's `show_tool_calls=True`)

**Step 3: Commit**

```bash
git add demo/ai_fraud_investigation_agent/fraud_investigation_agent.py
git commit -m "feat: add Streamlit UI with streaming narration"
```

---

### Task 10: Write the README.md

**Files:**
- Create: `demo/ai_fraud_investigation_agent/README.md`

**Step 1: Write README following awesome-llm-apps convention**

Follow the format from `advanced_ai_agents/single_agent_apps/ai_journalist_agent/README.md`:

```markdown
## 🔍 AI Fraud Investigation Agent

An AI-powered autonomous fraud investigation agent that analyzes childcare provider licensing data against physical building records to detect anomalies. The agent uses public data sources — property records, Google Maps, business registrations, and state licensing databases — to identify facilities where physical evidence doesn't match the paperwork.

### Features
- Searches state licensing databases for childcare providers by ZIP code
- Cross-references licensed capacity against actual building square footage from county GIS records
- Analyzes Google Street View imagery to verify facility legitimacy
- Checks business registrations with Secretary of State databases
- Discovers cross-provider patterns (shared owners, address clusters, geographic anomalies)
- Narrates its investigation in real-time so you can follow the reasoning

### How to get Started?

1. Clone the GitHub repository
...
2. Install the required dependencies:
...
3. Get your OpenRouter API Key
...
4. Get your Google Maps API Key
...
5. Run the Streamlit App
...

### How it Works?

The AI Fraud Investigation Agent uses 7 specialized investigation tools:
- **Provider Search**: Queries state licensing databases (Illinois DCFS) for all providers in a ZIP code
- **Property Analysis**: Pulls building square footage and zoning data from county GIS records (Cook County)
- **Capacity Calculation**: Applies state building code requirements to determine maximum legal childcare capacity
- **Visual Verification**: Captures Google Street View images to check if a facility visually matches its claimed purpose
- **Business Intelligence**: Queries Google Places for business type, operating status, and reviews
- **Registration Check**: Verifies business entity registration with Secretary of State
- **Geocoding**: Converts addresses to coordinates for spatial analysis

The agent autonomously investigates each provider, narrating its findings and flagging anomalies where licensed capacity exceeds what the physical building can legally support.
```

**Step 2: Commit**

```bash
git add demo/ai_fraud_investigation_agent/README.md
git commit -m "docs: add README for awesome-llm-apps submission"
```

---

### Task 11: Integration testing and polish

**Files:**
- Modify: `demo/ai_fraud_investigation_agent/fraud_investigation_agent.py`

**Step 1: End-to-end test with real API keys**

```bash
cd demo/ai_fraud_investigation_agent && streamlit run fraud_investigation_agent.py
```

Test checklist:
- [ ] App loads without errors
- [ ] Sidebar inputs work (API keys, ZIP code, model selector)
- [ ] Clicking Investigate starts the agent
- [ ] Provider search returns results for ZIP 60612
- [ ] Property data queries return building sqft
- [ ] Capacity calculations are correct
- [ ] Street View images are fetched (if Google key provided)
- [ ] Places info returns business data
- [ ] Business registration probes work (or gracefully handle 403)
- [ ] Narration streams in real-time
- [ ] Agent investigates multiple providers, not just the first one
- [ ] Context doesn't overflow on large provider lists
- [ ] No Python errors in terminal

**Step 2: Fix any issues found during testing**

**Step 3: Final commit**

```bash
git add demo/ai_fraud_investigation_agent/
git commit -m "feat: complete fraud investigation agent demo for awesome-llm-apps"
```

---

### Task 12: Prepare for awesome-llm-apps submission

**Files:** None (git operations only)

**Step 1: Fork awesome-llm-apps on GitHub**

```bash
gh repo fork Shubhamsaboo/awesome-llm-apps --clone=false
```

**Step 2: Clone the fork and copy demo files**

```bash
gh repo clone <your-username>/awesome-llm-apps /tmp/awesome-llm-apps
cp -r demo/ai_fraud_investigation_agent /tmp/awesome-llm-apps/advanced_ai_agents/single_agent_apps/ai_fraud_investigation_agent
```

**Step 3: Update the awesome-llm-apps README.md**

Add an entry under "Advanced AI Agents" section:
```markdown
*   [🔍 AI Fraud Investigation Agent](advanced_ai_agents/single_agent_apps/ai_fraud_investigation_agent/)
```

**Step 4: Create branch, commit, and open PR**

```bash
cd /tmp/awesome-llm-apps
git checkout -b add-fraud-investigation-agent
git add advanced_ai_agents/single_agent_apps/ai_fraud_investigation_agent/ README.md
git commit -m "feat: add AI Fraud Investigation Agent"
git push -u origin add-fraud-investigation-agent
gh pr create --title "Add AI Fraud Investigation Agent" --body "..."
```

---

## Notes for the implementer

1. **API key threading:** The tool functions need access to the Google Maps API key entered in the Streamlit sidebar. Use `st.session_state` or module-level variable. Do NOT use environment variables for this since the user enters keys in the UI.

2. **agno vs manual loop:** If agno's Agent class doesn't support mid-conversation context trimming, switch to a manual OpenAI client loop (matching `agent/loop.py:1682-1850`). The manual loop gives full control over message history. Keep agno in requirements regardless for consistency with the repo.

3. **IL DCFS scraping:** The DCFS provider lookup page uses ASP.NET viewstate. The scraper must handle this correctly. If the page structure changes, the tool should return a clear error message rather than crashing.

4. **Cook County Socrata:** These are open data APIs with no auth required. Rate limits are generous. The tool should handle 404s and empty results gracefully.

5. **Street View images:** These are large base64 strings. The context trimming logic is especially important when multiple providers have been investigated with street view.
