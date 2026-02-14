# Surelock Homes — Technical Spec
### *"If it doesn't fit, it doesn't sit."*

**Hackathon:** Anthropic "Built with Opus 4.6" — Claude Code Hackathon
**Dates:** February 10–16, 2026
**Submission:** Online (recorded video + repo)
**Team:** Solo
**Model:** Claude Opus 4.6 with Extended Thinking

---

## 1. One-Sentence Pitch

An autonomous AI investigator that discovers childcare fraud by reasoning across public data sources — not by following rules, but by noticing things that don't add up.

---

## 2. Why This Exists

### The Problem
- Minnesota lost $250M+ to CCAP childcare fraud (federal investigation ongoing)
- Federal government froze $10B+ in childcare funding across 5 states (Jan 2026), alleging "extensive and systematic fraud" but providing no evidence
- Current approach: 150 temp employees manually auditing providers, taking weeks per county
- A YouTuber (Nick Shirley, Dec 2025) found fraud patterns with a camera and public records

### The Insight
Every childcare facility must have 35 sq ft of usable indoor space per child. A 900 sq ft house cannot legally serve 75 children. This is math, not opinion — and it's verifiable using only public data.

### What Opus 4.6 Uniquely Enables
This project is NOT a database query or a rule engine. It is an autonomous investigator that uses Opus 4.6's three strongest capabilities:

1. **Extended Thinking / Reasoning** — The agent conducts deep multi-step reasoning within each turn. It cross-references data across providers, notices patterns nobody told it to look for, and follows leads autonomously. This is the primary showcase.

2. **Vision** — The agent analyzes Google Street View imagery to assess whether a facility looks like a childcare center. This adds a physical verification layer that no existing government tool provides.

3. **Agentic Tool Use** — The agent decides what tools to call, in what order, based on what it's finding. It is not following a script — it is making investigative decisions.

### What This Is NOT
- Not a statistical anomaly detector (OIG has done that since 2016)
- Not a dashboard showing pre-computed results
- Not a rule engine that checks predefined signals
- Not a replacement for human investigators — it's an accelerator that operates on public data only

### Honest Scope Limitation
Surelock Homes detects **physical impossibility** (buildings too small for licensed capacity) and **visual inconsistency** (addresses that don't look like childcare facilities). It does NOT detect **attendance fraud** (billing for children who don't show up), which is the most common CCAP fraud mechanism. Attendance fraud requires access to CCAP billing records and service authorizations, which are not public.

CCAP pays providers based on per-child attendance (hours × rate), not capacity. A provider with a legitimate building size could still commit fraud by reporting ghost children. Surelock Homes catches cases where the license itself is physically impossible — the most egregious and most indisputable cases.

---

## 3. Architecture

### 3.1 Core Design Philosophy

**The AI is an investigator, not a rule executor.**

Surelock Homes has no fixed investigation pipeline. The agent receives domain knowledge (building codes, fraud patterns), tools (APIs for data access), and guardrails (ethical/language constraints) — then conducts an autonomous investigation using its own judgment.

The agent decides:
- What to investigate first
- When to follow a lead vs continue scanning
- How to weigh combinations of evidence
- When a cross-provider pattern is worth pursuing
- What constitutes a genuine anomaly vs noise

This design showcases Opus 4.6's reasoning capability. A fixed pipeline would demonstrate engineering skill. An autonomous investigator demonstrates AI intelligence.

### 3.2 Extended Thinking Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SURELOCK HOMES                         │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              OPUS 4.6 + EXTENDED THINKING              │ │
│  │                                                        │ │
│  │  [Extended Thinking]         [Response]                 │ │
│  │  Deep reasoning              Investigation narration    │ │
│  │  Pattern detection           "Wait — I notice..."      │ │
│  │  Cross-referencing           "Let me check..."         │ │
│  │  Lead prioritization         "This changes things..."  │ │
│  │  Evidence synthesis          + Tool calls               │ │
│  │                                                        │ │
│  │  ← The real intelligence     ← What the audience sees  │ │
│  └───────────────┬────────────────────────────────────────┘ │
│                  │                                           │
│                  │ Tool Calls (function calling)              │
│                  │ The agent decides which tools, what order  │
│  ┌───────────────▼────────────────────────────────────────┐ │
│  │                    TOOL LAYER                          │ │
│  │                                                        │ │
│  │  search_childcare_providers()  → Provider databases    │ │
│  │  get_property_data()           → County GIS APIs       │ │
│  │  get_street_view()             → Google Street View    │ │
│  │  get_places_info()             → Google Places         │ │
│  │  check_licensing_status()      → State DHS records     │ │
│  │  check_business_registration() → Secretary of State    │ │
│  │  calculate_max_capacity()      → Local computation     │ │
│  │  geocode_address()             → Google Geocoding      │ │
│  └────────────────────────────────────────────────────────┘ │
│                  │                                           │
│  ┌───────────────▼────────────────────────────────────────┐ │
│  │                     OUTPUTS                            │ │
│  │                                                        │ │
│  │  1. Investigation Narrative (the story)                │ │
│  │  2. Provider Dossiers (per-provider evidence)          │ │
│  │  3. Pattern Analysis (cross-provider connections)      │ │
│  │  4. Confidence Calibration (what the agent is sure of) │ │
│  │  5. Exposure Estimate (potential $ at risk)            │ │
│  │  6. Referral Drafts (actionable letters to IG)        │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Two-Layer Thinking Model

The investigation uses Opus 4.6's Extended Thinking feature, creating two distinct layers:

**Layer 1: Extended Thinking (internal, not visible to user)**
- Deep multi-step reasoning
- Cross-referencing all accumulated data
- Pattern detection across providers
- Deciding what to investigate next and why
- Weighing evidence, considering innocent explanations
- This is where the real intelligence lives

**Layer 2: Investigation Narration (visible to user)**
- Key findings and observations as they happen
- "Wait — this owner name appeared before..."
- "Let me cross-reference this..."
- "Stepping back, I'm seeing a pattern..."
- Tool call decisions with reasoning
- This is the **product** — the audience watches the agent think

Both layers matter: Extended Thinking gives depth and accuracy. Narration gives drama and transparency. Together, they make the agent feel like a real investigator, not a black box.

### 3.4 Agent Loop

```python
import anthropic

client = anthropic.Client()

system_prompt = load("surelock-homes-system-prompt.md")
tools = define_tools()  # 8 tool definitions

messages = [
    {"role": "user", "content": investigation_request}
]

while True:
    response = client.messages.create(
        model="claude-opus-4-6-20250514",
        max_tokens=16000,
        thinking={
            "type": "enabled",
            "budget_tokens": 10000  # generous thinking budget per turn
        },
        system=system_prompt,
        tools=tools,
        messages=messages
    )

    for block in response.content:
        if block.type == "thinking":
            log_thinking(block.thinking)     # save for analysis
        elif block.type == "text":
            display_narration(block.text)     # show to user
        elif block.type == "tool_use":
            result = execute_tool(block)
            messages.append(tool_result(result))

    if response.stop_reason == "end_turn":
        break

    messages.append({"role": "assistant", "content": response.content})
```

### 3.5 Conversation Flow Example

This illustrates what an actual investigation looks like — the agent driving autonomously:

```
Turn 1:
  [thinking] A ZIP code to investigate. Start by finding all providers,
  then decide where to focus based on what stands out...

  [narration] "Starting investigation of Chicago ZIP 60612. Let me pull
  all licensed childcare providers in this area."

  [tool_call] search_childcare_providers(zip="60612", state="IL")

Turn 2:
  [tool_result] 47 providers returned

  [thinking] 47 providers. Capacities range from 6 to 150. Three over 80
  — unusual density. Two providers share 1847 W Roosevelt. Worth tracking.
  Pull property data for high-capacity ones first...

  [narration] "47 providers found. A few things jump out: three providers
  with capacity over 80 in one ZIP, and two sharing the address 1847 W
  Roosevelt. Checking building data for the high-capacity ones first."

  [tool_call] get_property_data(address="2301 S California Ave", state="IL")

Turn 3:
  [tool_result] 1,100 sq ft, residential zoning, single-family home

  [thinking] 1,100 × 0.65 = 715 usable ÷ 35 = 20 max. Licensed for 85.
  That's 4.2x over. Clear physical impossibility. Note provider name and
  check business registration for cross-referencing later...

  [narration] "This is significant. 2301 S California is a 1,100 sq ft
  single-family home. Maximum legal capacity: 20 children. Licensed
  capacity: 85. That's 4.2 times the physical maximum — 85 children
  would have 8.4 sq ft each. Less than a desk.

  Let me check who owns this and when it was established."

  [tool_call] check_business_registration(name="Bright Future Learning
  Center", state="IL")

  ... [several turns of investigation] ...

Turn 7:
  [tool_result] Second provider's registered agent: "Michelle Davis"

  [thinking] Wait. Michelle Davis again. She was the agent for Bright
  Future at 2301 S California (85 kids, 1,100 sq ft). Now she's also
  the agent for Little Stars Academy at 1847 W Roosevelt — the address
  with TWO providers. This could be a coordinated operation, not
  isolated buildings with problems. Must pursue this immediately...

  [narration] "Wait — I need to stop here. The registered agent for
  this provider is Michelle Davis. That's the same person registered
  for Bright Future Learning Center, the 1,100 sq ft house licensed
  for 85 children.

  And this address — 1847 W Roosevelt — is where I saw two providers
  at the same location. Let me check if Michelle Davis is connected
  to any other providers in this ZIP."

  [tool_call] check_business_registration(name="Michelle Davis",
  state="IL", search_type="agent")
```

**Turn 7 is the key moment.** The agent discovered a cross-provider connection that was not in any predefined rule. It stopped its normal flow to pursue a lead. This is the demo's centerpiece.

---

## 4. Tool Specifications

### 4.1 Tool Definitions

```python
tools = [
    {
        "name": "search_childcare_providers",
        "description": "Search for licensed childcare providers in a target area. Returns all providers with their name, address, licensed capacity, license type, and license status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
                "state": {"type": "string", "enum": ["MN", "IL"]},
                "zip": {"type": "string", "description": "5-digit ZIP code"},
                "radius_miles": {"type": "number", "default": 5}
            },
            "required": ["state"]
        }
    },
    {
        "name": "get_property_data",
        "description": "Get building and parcel data for a specific address from county GIS records. Returns building square footage, lot size, zoning classification, property class, and year built.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Full street address"},
                "county": {"type": "string", "description": "County name (optional, helps with lookup)"},
                "state": {"type": "string"}
            },
            "required": ["address", "state"]
        }
    },
    {
        "name": "get_street_view",
        "description": "Capture Google Street View images of a location from multiple angles. Returns JPEG images that can be analyzed visually.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "headings": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 360},
                    "default": [0, 90, 180, 270],
                    "description": "Camera headings in degrees (0=north, 90=east)"
                },
                "size": {"type": "string", "default": "640x480"}
            },
            "required": ["address"]
        }
    },
    {
        "name": "get_places_info",
        "description": "Get Google Places data for an address. Returns current business type, operating status, rating, review count, and recent reviews if available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"}
            },
            "required": ["address"]
        }
    },
    {
        "name": "check_licensing_status",
        "description": "Look up detailed licensing information for a childcare provider from state DHS records. Returns license dates, capacity, violation history, conditions, and inspection records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "provider_name": {"type": "string"},
                "state": {"type": "string", "enum": ["MN", "IL"]},
                "address": {"type": "string", "description": "For disambiguation if multiple matches"}
            },
            "required": ["provider_name", "state"]
        }
    },
    {
        "name": "check_business_registration",
        "description": "Look up business entity registration with Secretary of State. Returns incorporation date, registered agent name, entity type, status, and registered address. Can also search by agent name to find all entities associated with a person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Business name OR person name (for agent search)"},
                "state": {"type": "string"},
                "search_type": {
                    "type": "string",
                    "enum": ["business", "agent"],
                    "default": "business",
                    "description": "Search by business name or by registered agent name"
                }
            },
            "required": ["name", "state"]
        }
    },
    {
        "name": "calculate_max_capacity",
        "description": "Calculate the maximum legal childcare capacity for a building based on square footage and state building code requirements. Shows full calculation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "building_sqft": {"type": "number"},
                "state": {"type": "string", "enum": ["MN", "IL"]},
                "usable_ratio": {
                    "type": "number",
                    "default": 0.65,
                    "description": "Estimated ratio of usable childcare space to total building sqft"
                }
            },
            "required": ["building_sqft", "state"]
        }
    },
    {
        "name": "geocode_address",
        "description": "Validate and standardize an address. Returns coordinates, formatted address, and whether the address is valid.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"}
            },
            "required": ["address"]
        }
    }
]
```

### 4.2 Tool Implementation Strategy

Each tool has a **primary implementation** (real API) and a **fallback** (cached/pre-downloaded data).

| Tool | Primary Source | Fallback | Notes |
|------|---------------|----------|-------|
| search_childcare_providers | ChildCare.gov / DCFS Sunshine scrape / MN Geospatial Commons CSV | Pre-downloaded CSV for target ZIPs | MN has CSV download; IL requires scraping |
| get_property_data | Cook County CookViewer API / Hennepin County GIS API | Pre-downloaded parcel data | Cook County supports CSV export |
| get_street_view | Google Street View Static API | Pre-cached images for demo addresses | $7/1000 requests |
| get_places_info | Google Places API | Pre-cached for demo addresses | $17/1000 requests |
| check_licensing_status | DHS Licensing Lookup scrape / DCFS Sunshine scrape | Pre-scraped for target providers | May need Selenium for dynamic pages |
| check_business_registration | MN SOS / IL SOS search | Pre-downloaded SOS data | MN offers bulk CSV for researchers |
| calculate_max_capacity | Local computation (no API) | N/A | Pure math: sqft × ratio ÷ 35 |
| geocode_address | Google Geocoding API | Pre-cached for demo addresses | $5/1000 requests |

**Critical implementation note:** `check_business_registration` with `search_type="agent"` is the key enabler for pattern discovery. This reverse-lookup by agent name is what allows the agent to find that one person controls multiple providers. The implementation must support this mode.

### 4.3 Tool Implementation Details

#### search_childcare_providers — MN

```python
# MN: Use pre-downloaded Geospatial Commons CSV
# Download: https://gisdata.mn.gov/dataset/health-child-care-providers
# ~10,000 records with: name, address, city, zip, capacity, license_type, status, lat, lng

import pandas as pd

def search_mn_providers(city=None, zip=None, radius_miles=5):
    df = pd.read_csv("data/mn_providers.csv")
    if zip:
        df = df[df["zip"] == zip]
    elif city:
        df = df[df["city"].str.contains(city, case=False)]
    return df[["name", "address", "city", "zip", "capacity",
               "license_type", "status"]].to_dict("records")
```

#### search_childcare_providers — IL

```python
# IL: Scrape DCFS Sunshine or ExceleRate Illinois
# DCFS Sunshine: https://sunshine.dcfs.illinois.gov
# ExceleRate: https://www.excelerateillinois.com/find-a-program
#
# Both are search interfaces — no bulk download available
# Options:
#   1. Selenium scraper for live queries
#   2. Pre-scrape target ZIP codes before hackathon starts
#   3. Use ChildCare.gov as backup
#
# Recommended: Pre-scrape target ZIPs + live scrape as primary
```

#### get_property_data — Cook County (IL)

```python
# Cook County CookViewer provides parcel data
# URL: https://maps.cookcountyil.gov/cookviewer/
#
# Access methods:
#   1. ArcGIS REST API (underlying CookViewer) — discover endpoint from page source
#   2. Cook County Open Data Portal: https://datacatalog.cookcountyil.gov/
#   3. Manual CSV export from CookViewer for target areas
#
# Key fields: PIN, address, building_sqft, land_sqft, property_class,
#             assessed_value, building_age, zoning
#
# Engineering note: Address matching between provider records and parcel
# records is non-trivial. Provider says "1847 W Roosevelt Rd", parcel says
# "1847 WEST ROOSEVELT ROAD". Geocoding both and matching by coordinates
# is more reliable than string matching.
```

#### get_property_data — Hennepin County (MN)

```python
# Hennepin County GIS Open Data
# URL: https://gis.hennepin.us/
#
# Has ArcGIS REST API + downloadable shapefiles/CSV
# Key fields: address, building_sqft, land_area, property_type,
#             year_built, zoning_code
#
# This is the cleanest data source — well-documented, free, no auth required
```

#### get_street_view

```python
import requests
import base64

def get_street_view(address, headings=[0, 90, 180, 270], size="640x480"):
    images = []
    for heading in headings:
        url = "https://maps.googleapis.com/maps/api/streetview"
        params = {
            "location": address,
            "heading": heading,
            "size": size,
            "key": GOOGLE_API_KEY
        }
        response = requests.get(url, params=params)
        # Also fetch metadata for capture date
        meta_params = {**params, "return_error_codes": True}
        meta = requests.get(url.replace("/streetview", "/streetview/metadata"),
                          params=meta_params).json()
        images.append({
            "heading": heading,
            "image_base64": base64.b64encode(response.content).decode(),
            "capture_date": meta.get("date", "unknown"),
            "status": meta.get("status")
        })
    return images
```

Images are returned as base64, which Opus 4.6 Vision can analyze directly in the conversation.

#### calculate_max_capacity

```python
def calculate_max_capacity(building_sqft, state, usable_ratio=0.65):
    sqft_per_child = 35  # MN and IL both use 35
    usable_sqft = building_sqft * usable_ratio
    max_capacity = int(usable_sqft / sqft_per_child)
    return {
        "building_sqft": building_sqft,
        "usable_ratio": usable_ratio,
        "usable_sqft": usable_sqft,
        "sqft_per_child_required": sqft_per_child,
        "max_legal_capacity": max_capacity,
        "state": state,
        "regulation": "MN Rules 9503.0155" if state == "MN" else "IL DCFS Part 407",
        "calculation": f"{building_sqft} × {usable_ratio} = {usable_sqft} usable sqft ÷ {sqft_per_child} = {max_capacity} children max"
    }
```

---

## 5. Data Sources — Complete Reference

### 5.1 Minnesota

| Source | URL | Data | Format | Auth |
|--------|-----|------|--------|------|
| MN Geospatial Commons | gisdata.mn.gov | ~10,000 providers with coordinates | CSV/Shapefile | None |
| DHS Licensing Lookup | licensinglookup.dhs.state.mn.us | Name, address, capacity, violations | HTML (scrape) | None |
| Hennepin County GIS | gis.hennepin.us | Building sqft, zoning, property class | CSV/API | None |
| MN Secretary of State | mblsportal.sos.state.mn.us | Business registration, agents | HTML + bulk CSV | None |
| Parent Aware | parentaware.org | Quality ratings, 12,000+ programs | HTML (search) | None |

### 5.2 Illinois

| Source | URL | Data | Format | Auth |
|--------|-----|------|--------|------|
| DCFS Sunshine | sunshine.dcfs.illinois.gov | Provider search: name, capacity, violations | HTML (scrape) | None |
| ExceleRate Illinois | excelerateillinois.com | 10,000+ programs | HTML (search) | None |
| Cook County GIS | maps.cookcountyil.gov/cookviewer | Building sqft, zoning, property class | CSV export + API | None |
| IL Secretary of State | cyberdriveillinois.com | Business registration | HTML (search) | None |
| ChildCare.gov | childcare.gov | Federal provider search | HTML/API | None |

### 5.3 Paid APIs

| API | Purpose | Cost | Auth |
|-----|---------|------|------|
| Google Street View Static | Facility imagery | $7/1000 requests | API key |
| Google Places | Business type, status | $17/1000 requests | API key |
| Google Geocoding | Address validation | $5/1000 requests | API key |
| Anthropic API (Opus 4.6) | Agent + Vision + Thinking | Per-token | API key |

**Estimated total API cost for full demo: $20-50**

### 5.4 CCAP Payment Rates (for Exposure Estimates)

Source: MN DCYF DHS-6441F (public PDF)

| Age Group | Center (monthly) | Family (monthly) |
|-----------|-----------------|------------------|
| Infant | ~$1,600 | ~$1,100 |
| Toddler | ~$1,300 | ~$1,000 |
| Preschool | ~$1,100 | ~$900 |
| School-age | ~$900 | ~$700 |

Hardcoded in system prompt for the agent to estimate exposure.

---

## 6. Demo Strategy

### 6.1 Submission Format

Online hackathon → Submit:
1. **GitHub repo** with full source code
2. **README.md** with setup instructions, architecture explanation
3. **Demo video** (~5 min) showing the investigation + key reasoning moments
4. Investigation output artifacts (reports, narration logs)

### 6.2 Demo Structure (Video, ~5 min)

**[0:00-0:30] The Problem**
"Minnesota lost $250M to childcare fraud. The federal government froze $10B across 5 states. A YouTuber found patterns the system missed for years. What if AI could do what he did — but at scale, in minutes, using only public data?"

**[0:30-1:30] Minnesota Calibration**
"First, proof that this works. Giving Surelock Homes the 9 addresses from Nick Shirley's viral investigation. The agent has never seen these before..."

*[Show: agent narration as it discovers physical impossibilities in known fraud cases]*
*[Key metric: X of 9 flagged — Y% detection rate]*

**[1:30-4:00] Illinois Discovery**
"Now the real test. The federal government claims Illinois has systemic fraud but won't show evidence. Letting the agent investigate a Chicago ZIP code..."

*[Show: agent narration as it investigates, discovers anomalies]*
*[KEY MOMENT: agent discovers cross-provider pattern on its own]*
*[Show: agent stops, says "Wait —", follows the lead, reveals a network]*

**[4:00-4:30] The Output**
*[Show: generated investigation report, exposure estimate, referral letter]*

**[4:30-5:00] Close**
"Building codes are physical laws — you either have 35 square feet per child or you don't. Surelock Homes didn't follow a script. It investigated, discovered patterns, and followed leads. The cross-provider network it found wasn't in any predefined rule. That's what Opus 4.6's reasoning enables — genuine investigative intelligence.

If it doesn't fit, it doesn't sit."

### 6.3 The Key Moment

The video MUST capture the moment when the agent discovers something unexpected — a cross-provider connection, a shared owner, a geographic cluster, or any pattern that emerges from reasoning rather than rules.

If this moment doesn't happen naturally in the first run, run investigations on multiple ZIP codes until a genuine discovery occurs. Chicago's high provider density increases probability. The agent's Extended Thinking + cross-referencing makes this likely but not guaranteed.

**This moment is the entire demo.** Everything else is setup and payoff.

---

## 7. Engineering Implementation Plan

### 7.1 Project Structure

```
surelock-homes/
├── README.md
├── .env.example
├── requirements.txt
├── config.py                   # API keys, paths, constants
│
├── agent/
│   ├── __init__.py
│   ├── loop.py                 # Main agent loop (thinking + tool calls)
│   ├── prompt.py               # System prompt loader
│   └── narration.py            # Narration capture and formatting
│
├── tools/
│   ├── __init__.py
│   ├── definitions.py          # All 8 tool JSON schemas
│   ├── providers.py            # search_childcare_providers
│   ├── property.py             # get_property_data
│   ├── street_view.py          # get_street_view
│   ├── places.py               # get_places_info
│   ├── licensing.py            # check_licensing_status
│   ├── business_reg.py         # check_business_registration
│   ├── capacity.py             # calculate_max_capacity
│   └── geocoding.py            # geocode_address
│
├── data/
│   ├── mn_providers.csv        # Pre-downloaded MN Geospatial Commons
│   ├── il_providers/           # Pre-scraped IL provider data by ZIP
│   ├── hennepin_parcels.csv    # Pre-downloaded Hennepin County GIS
│   ├── cook_parcels/           # Pre-downloaded Cook County parcels
│   ├── cached_street_view/     # Cached Street View images
│   └── ccap_rates.json         # CCAP payment rates for exposure calc
│
├── output/
│   ├── investigations/         # Saved investigation outputs
│   └── narration_logs/         # Full narration logs per run
│
├── scripts/
│   ├── download_mn_data.py     # Download MN Geospatial Commons CSV
│   ├── scrape_il_providers.py  # Scrape DCFS Sunshine for target ZIPs
│   ├── download_parcels.py     # Download parcel data for target areas
│   └── cache_street_view.py    # Pre-cache Street View for known addresses
│
└── run.py                      # Main entry point
```

### 7.2 Task Breakdown

#### TASK 1: Agent Loop
**Priority:** CRITICAL | **Est:** 3-4 hours | **File:** `agent/loop.py`

Implement the core agent loop using Anthropic SDK with Extended Thinking.

Requirements:
- Initialize conversation with system prompt + user investigation request
- Enable Extended Thinking with generous budget (10,000+ tokens per turn)
- Handle response content blocks: thinking, text, tool_use
- Execute tool calls and feed results back as tool_result messages
- Capture full narration (text blocks) and thinking (thinking blocks) separately
- Loop until stop_reason == "end_turn"
- Save complete investigation output (narration + thinking + tool call log)

Key API parameters:
```python
model="claude-opus-4-6-20250514"
max_tokens=16000
thinking={"type": "enabled", "budget_tokens": 10000}
```

Edge cases to handle:
- Tool call fails → return error message as tool_result, let the agent decide how to recover
- Very long investigation (30+ turns) → may need to summarize earlier context to stay within limits
- Multiple tool calls in single response → execute all, return all results

#### TASK 2: Tool Definitions
**Priority:** CRITICAL | **Est:** 1 hour | **File:** `tools/definitions.py`

Define all 8 tool JSON schemas exactly as specified in Section 4.1. Straightforward — just schema definitions.

#### TASK 3: Provider Search Tool
**Priority:** CRITICAL | **Est:** 2-3 hours | **Files:** `tools/providers.py`, `scripts/download_mn_data.py`, `scripts/scrape_il_providers.py`

MN implementation:
- Download MN Geospatial Commons CSV (~10,000 records)
- Load into pandas, filter by ZIP/city
- Return structured provider list

IL implementation:
- Option A: Selenium scraper for DCFS Sunshine (impressive but fragile)
- Option B: Pre-scrape target ZIP codes into CSV (reliable)
- Build both; use pre-scraped as fallback

Target IL ZIP codes to pre-scrape:
60612, 60621, 60623, 60624, 60629, 60636, 60637, 60644, 60649
(High provider density areas in Chicago)

#### TASK 4: Property Data Tool
**Priority:** CRITICAL | **Est:** 3-4 hours | **Files:** `tools/property.py`, `scripts/download_parcels.py`

Most technically challenging tool — county GIS APIs vary in structure.

Hennepin County (MN):
- Find ArcGIS REST endpoint from gis.hennepin.us
- Query by address → return parcel record
- Key fields: building_sqft, land_area, property_type, year_built, zoning

Cook County (IL):
- Find ArcGIS REST endpoint from CookViewer page source (look for FeatureServer URLs)
- OR use Cook County Open Data Portal
- Query by address → return parcel record
- Key fields: building_sqft, land_sqft, property_class, assessed_value, zoning

Fallback: Pre-download parcel CSV for target areas, do local address matching.

**Engineering note:** Address matching between data sources is non-trivial. "1847 W Roosevelt Rd" vs "1847 WEST ROOSEVELT ROAD". Geocoding both addresses and matching by lat/lng proximity is more reliable than string matching.

#### TASK 5: Street View Tool
**Priority:** HIGH | **Est:** 1-2 hours | **File:** `tools/street_view.py`

Google Street View Static API wrapper. Return base64-encoded images + metadata (capture date). See Section 4.3 for implementation code.

Important: fetch metadata endpoint separately to get image capture date.

#### TASK 6: Business Registration Tool
**Priority:** HIGH | **Est:** 2-3 hours | **File:** `tools/business_reg.py`

**This tool is critical for pattern discovery.** Must support two search modes:
1. Search by business name → return registered agent, incorporation date, status
2. Search by agent name → return ALL businesses registered to that person

Mode 2 enables the agent to discover ownership networks — the "Wait —" moment in the demo.

MN: Secretary of State Business Filing Search (mblsportal.sos.state.mn.us)
IL: Cyberdrive Illinois Business Entity Search (cyberdriveillinois.com)

Both are HTML search interfaces requiring scraping or Selenium.

#### TASK 7: Google Places Tool
**Priority:** MEDIUM | **Est:** 1 hour | **File:** `tools/places.py`

Google Places API wrapper. Key value: if Places shows the address as "nail salon" but DHS says it's a daycare, that's a strong signal.

#### TASK 8: Licensing Status Tool
**Priority:** MEDIUM | **Est:** 2-3 hours | **File:** `tools/licensing.py`

Scrape state licensing lookup sites for violation history and detailed license info. MN: DHS Licensing Lookup. IL: DCFS Sunshine. May require Selenium. Pre-scrape as fallback.

#### TASK 9: Capacity Calculator
**Priority:** LOW | **Est:** 15 min | **File:** `tools/capacity.py`

Pure math, no API needed. See Section 4.3 for implementation code.

#### TASK 10: Geocoding Tool
**Priority:** LOW | **Est:** 30 min | **File:** `tools/geocoding.py`

Google Geocoding API wrapper. Useful for address validation and coordinate-based matching between data sources.

#### TASK 11: Data Pre-Download Scripts
**Priority:** HIGH | **Est:** 2-3 hours | **Files:** `scripts/*.py`

Pre-download and cache data for target areas. Ensures the demo works even if external APIs are slow or unavailable.

Scripts needed:
- `download_mn_data.py` — MN Geospatial Commons CSV
- `scrape_il_providers.py` — DCFS Sunshine for target ZIP codes
- `download_parcels.py` — Hennepin County + Cook County parcel data
- `cache_street_view.py` — Street View images for known addresses (Shirley cases + demo ZIPs)

#### TASK 12: Narration Capture & Output Formatting
**Priority:** MEDIUM | **Est:** 2 hours | **Files:** `agent/narration.py`

Capture the agent's output into readable formats:
- Full narration log (every text block from every turn)
- Thinking log (every thinking block — not shown in demo but valuable for analysis)
- Tool call log (every tool call with inputs and outputs)
- Final investigation report (the agent's synthesis output)

Output format: Markdown or HTML.

#### TASK 13: Demo Video Recording
**Priority:** HIGH | **Est:** 2-3 hours

Record the submission video showing:
- The investigation running (screen recording of terminal or simple UI)
- Key narration moments highlighted
- The "wow moment" where the agent discovers a pattern
- Final outputs (report, exposure estimate, referral letter)

Terminal with colored/formatted output is sufficient. Streamlit UI is nice-to-have.

### 7.3 Implementation Schedule

```
Day 1: Foundation
  TASK 2: Tool definitions (1h)
  TASK 9: Capacity calculator (15min)
  TASK 1: Agent loop (3-4h)
  → Milestone: Agent runs, calls tools, narrates (even with stub tools)

Day 2: Core Tools
  TASK 3: Provider search — MN + IL (2-3h)
  TASK 4: Property data — Hennepin + Cook County (3-4h)
  TASK 11: Data pre-download scripts (2-3h)
  → Milestone: Agent finds providers + checks building sizes

Day 3: Investigation Power
  TASK 5: Street View (1-2h)
  TASK 6: Business registration with agent reverse-lookup (2-3h)
  TASK 10: Geocoding (30min)
  → Milestone: Agent does visual verification + owner cross-reference

Day 4: Calibration + Discovery
  Run MN calibration (Shirley's 9 known cases)
  Tune system prompt based on results
  Run IL discovery on multiple ZIP codes
  Find the best "wow moment" for the demo
  → Milestone: At least one compelling investigation run with pattern discovery

Day 5: Polish + Record
  TASK 7: Places info (1h, if time)
  TASK 8: Licensing status (2-3h, if time)
  TASK 12: Narration capture + formatting (2h)
  TASK 13: Demo video (2-3h)
  Write README.md
  → Milestone: Demo-ready

Day 6-7: Buffer
  Bug fixes
  Re-run investigations if needed
  Submit with 3+ hours buffer
```

### 7.4 Scope Tiers

**MVP (Must have for submission):**
- [ ] Agent loop with Extended Thinking
- [ ] 4 core tools: provider search, property data, Street View, capacity calc
- [ ] System prompt (autonomous investigator style)
- [ ] MN calibration run (Shirley cases)
- [ ] At least 1 IL discovery run with genuine findings
- [ ] Demo video showing investigation + AI reasoning
- [ ] Narration log showing the agent's thought process

**Strong Submission (Should have):**
- [ ] Business registration tool with agent reverse-lookup
- [ ] Agent discovers cross-provider pattern autonomously
- [ ] Exposure estimate in output
- [ ] Confidence calibration in output
- [ ] Referral letter drafts
- [ ] Clean GitHub repo with README

**Award-Winning (Nice to have):**
- [ ] Streamlit UI with map + narration display
- [ ] Google Places verification layer
- [ ] Licensing violation history integration
- [ ] Multi-state demo (switch from IL to another state)
- [ ] Full thinking log analysis (show what the agent considered but didn't say)

---

## 8. Risk Mitigation

| Risk | Severity | Mitigation |
|------|----------|------------|
| County GIS API undocumented or broken | HIGH | Pre-download parcel CSV for target areas |
| Street View has no coverage for address | MEDIUM | Note as "no coverage" — absence is informative |
| IL provider data hard to scrape | HIGH | Pre-scrape target ZIPs before hackathon; ChildCare.gov as backup |
| Agent doesn't discover cross-provider pattern | MEDIUM | Run multiple ZIP codes; high-density Chicago areas increase probability |
| False positives — flagged provider is legitimate | HIGH | System prompt requires innocent explanations + "investigation leads only" language |
| Google API rate limits or costs | LOW | Cache aggressively; $50 budget is ample |
| Address matching between data sources fails | MEDIUM | Use geocoding to normalize; match by coordinates not strings |
| Agent goes off-track | LOW | System prompt grounds in domain knowledge; adjustable thinking budget |
| MN calibration cases don't flag well | MEDIUM | Have backup known cases; IL is the primary showcase anyway |
| Extended Thinking takes too long | LOW | Online submission = no time pressure; budget_tokens controls per-turn cost |

---

## 9. Success Metrics

| Metric | Target | How Measured |
|--------|--------|-------------|
| MN detection rate | ≥8/9 Shirley cases flagged | Run calibration |
| IL findings | ≥3 providers flagged with evidence | Run discovery |
| Pattern discovery | ≥1 cross-provider connection found by the agent | Review narration log |
| False positive rate | <25% of flags are clearly legitimate | Manual review |
| Tool diversity | Agent uses ≥4 different tools per investigation | Review tool call log |
| Narration quality | Evaluator can follow reasoning without explanation | Watch demo video cold |

---

## 10. Environment Setup

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_MAPS_API_KEY=AIza...

# Python dependencies
pip install anthropic pandas requests beautifulsoup4 selenium

# Optional
pip install streamlit folium  # for UI
```

---

## 11. Why "Surelock Homes"

| Layer | Pun | Meaning |
|-------|-----|---------|
| Name | Sherlock Holmes → Surelock Homes | An investigator that examines homes and buildings |
| "Sure" | Sure + lock | Certainty — building codes are definitive, not probabilistic |
| "Lock" | Lock | Lock on target — flags with evidence |
| "Homes" | Holmes + homes | The investigation subject: physical buildings |
| Tagline | "If the glove doesn't fit" (O.J.) → "If it doesn't fit, it doesn't sit" | Can't fit 75 kids in 900 sq ft — they literally can't sit down |

---

## 12. Legal & Ethical Notes

- All data sources are publicly available — no FOIA or data requests required
- Building code calculations use conservative estimates (0.65 usable ratio)
- All output includes scope limitations and methodology disclosure
- Flagged providers are "investigation leads" — never "confirmed fraud"
- No individuals are named as suspected criminals in any output
- Physical impossibility detection is objective and demographics-neutral
- The tool identifies licensing system failures, not individual wrongdoing
