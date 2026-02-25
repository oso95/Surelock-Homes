from types import SimpleNamespace
from unittest.mock import MagicMock

import agent.loop as loop_mod
from agent.loop import run_investigation
from agent.loop import _coerce_tool_payload
from agent.loop import _ensure_report_text
from agent.loop import _extract_inline_report
from agent.loop import _extract_metrics
from agent.loop import _extract_text
from agent.loop import _looks_like_final_report
from agent.loop import _normalize_report_output


def test_offline_investigation_returns_payload():
    result = run_investigation("Investigate Minnesota providers in ZIP 55401", offline=True, max_turns=3, save_output=False)
    assert result["mode"] == "offline"
    assert "narration" in result
    assert "tool_calls" in result
    assert result["status"] == "complete"
    assert "report_text" in result
    assert len(result["report_text"]) > 0


def test_offline_flags_physical_impossibility():
    result = run_investigation("Investigate Illinois providers in ZIP 60608", offline=True, max_turns=5, save_output=False)
    assert result["mode"] == "offline"
    assert isinstance(result["flagged"], list)
    assert len(result["flagged"]) >= 1


def test_tool_payload_summary_handles_list_results():
    payload = _coerce_tool_payload([{"status": "found", "business_name": "Windy City Care"}])
    assert payload["status"] == "found"
    assert payload["error"] is None


def test_tool_payload_summary_extracts_error_from_list_results():
    payload = _coerce_tool_payload(
        [
            {"status": "error", "error": "No records"},
            {"status": "found", "business_name": "Fallback"},
        ]
    )
    assert payload["status"] == "error"
    assert payload["error"] == "No records"


def test_extract_inline_report_finds_report_section():
    blocks = [
        "I'll start by looking up providers in this ZIP code.",
        "Let me check the property data for this address.",
        "# INVESTIGATION REPORT\n\n## 1. INVESTIGATION NARRATIVE\nWe found 3 providers.",
        "## 2. PROVIDER DOSSIERS\n\n### Provider A\nCapacity: 50",
    ]
    result = _extract_inline_report(blocks)
    assert "INVESTIGATION REPORT" in result
    assert "PROVIDER DOSSIERS" in result
    # Should NOT include the earlier investigation chatter
    assert "I'll start by looking up" not in result
    assert "Let me check" not in result


def test_extract_inline_report_returns_empty_when_no_markers():
    blocks = [
        "I'll investigate providers now.",
        "The property data shows a small residential lot.",
    ]
    result = _extract_inline_report(blocks)
    assert result == ""


def test_extract_inline_report_handles_surelock_homes_marker():
    blocks = [
        "Checking licensing status...",
        "# Surelock Homes Investigation Report\n\nProvider analysis follows.",
        "## Findings\nAll clear.",
    ]
    result = _extract_inline_report(blocks)
    assert "Surelock Homes" in result
    assert "Findings" in result
    assert "Checking licensing" not in result


def test_extract_inline_report_skips_investigation_initiated_preamble():
    blocks = [
        "# Surelock Homes — Investigation Initiated\n\nTurn updates...",
        "More investigation narration.",
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n## 1. INVESTIGATION NARRATIVE\nFinal narrative.",
    ]
    result = _extract_inline_report(blocks)
    assert result.startswith("# SURELOCK HOMES INVESTIGATION REPORT")
    assert "Investigation Initiated" not in result


def test_extract_text_handles_structured_content():
    content = [
        {"type": "text", "text": "First chunk"},
        {"type": "text", "text": "Second chunk"},
    ]
    assert _extract_text(content) == "First chunk\nSecond chunk"


def test_looks_like_final_report_requires_report_structure():
    good = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "## 1. INVESTIGATION NARRATIVE\n...\n"
        "## 2. PROVIDER DOSSIERS\n...\n"
        "## 3. PATTERN ANALYSIS\n...\n"
        "## 4. CONFIDENCE CALIBRATION\n..."
    )
    bad = "To begin this investigation, I need to understand the landscape first."
    assert _looks_like_final_report(good) is True
    assert _looks_like_final_report(bad) is False


def test_normalize_report_output_strips_prompt_echo_preamble():
    raw = (
        "Do NOT use introductory text. Just write the report.\n"
        "Write the final report. Do NOT use any tools.\n"
        "Start the output immediately with:\n"
        "\"\n"
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Body."
    )
    out = _normalize_report_output(raw)
    assert out.startswith("# SURELOCK HOMES INVESTIGATION REPORT")
    assert "Do NOT use introductory text" not in out


def test_normalize_report_output_trims_investigation_narration_preamble():
    raw = (
        "# Surelock Homes — Investigation Initiated\n\n"
        "Interim narration before report.\n\n"
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Body."
    )
    out = _normalize_report_output(raw)
    assert out.startswith("# SURELOCK HOMES INVESTIGATION REPORT")
    assert "Investigation Initiated" not in out


def test_ensure_report_text_synthesizes_when_missing():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": "Provider A", "address": "100 Main St", "capacity": 80},
            ],
        },
        {
            "tool": "get_property_data",
            "arguments": {"address": "100 Main St"},
            "status": "ok",
            "result": {"building_sqft": 1200},
        },
        {
            "tool": "calculate_max_capacity",
            "arguments": {"building_sqft": 1200},
            "status": "ok",
            "result": {"max_legal_capacity": 22},
        },
    ]
    raw_turns = [{"turn": 1, "assistant": "Investigating providers...", "tool_results": []}]

    report = _ensure_report_text(
        mode="agent",
        query="Investigate Illinois providers in ZIP 60612",
        report_text="",
        assistant_text=["Investigating providers..."],
        raw_turns=raw_turns,
        tool_calls=tool_calls,
    )

    assert "SURELOCK HOMES INVESTIGATION REPORT" in report
    assert "INVESTIGATION NARRATIVE" in report
    assert "PROVIDER DOSSIERS" in report


def test_ensure_report_text_falls_back_on_total_provider_mismatch():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": f"Provider {i}", "address": f"{i} Main St", "capacity": 10}
                for i in range(5)
            ],
        }
    ]

    mismatched_report = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "SURELOCK_METRICS: {\"provider_count\": 3, \"flagged_count\": 0}\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "The investigation began with a search returning **3 providers** in total.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "No major outliers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "No strong clusters.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Moderate confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Limited exposure.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Follow up.\n\n"
        "SURELOCK_FINDINGS_JSON_START\n"
        "[]\n"
        "SURELOCK_FINDINGS_JSON_END"
    )

    report = _ensure_report_text(
        mode="agent",
        query="Investigate Illinois providers in Champaign County",
        report_text=mismatched_report,
        assistant_text=[],
        raw_turns=[{"turn": 1, "assistant": "Investigating providers...", "tool_results": []}],
        tool_calls=tool_calls,
    )

    assert "Providers identified in primary search: 5." in report
    assert "returning **3 providers** in total" not in report


def test_ensure_report_text_keeps_matching_total_provider_count():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": f"Provider {i}", "address": f"{i} Main St", "capacity": 10}
                for i in range(5)
            ],
        }
    ]

    matching_report = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "SURELOCK_METRICS: {\"provider_count\": 5, \"flagged_count\": 0}\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "The investigation began with a search returning **5 providers** in total.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "No major outliers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "No strong clusters.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Moderate confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Limited exposure.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Follow up.\n\n"
        "SURELOCK_FINDINGS_JSON_START\n"
        "[]\n"
        "SURELOCK_FINDINGS_JSON_END"
    )

    report = _ensure_report_text(
        mode="agent",
        query="Investigate Illinois providers in Champaign County",
        report_text=matching_report,
        assistant_text=[],
        raw_turns=[{"turn": 1, "assistant": "Investigating providers...", "tool_results": []}],
        tool_calls=tool_calls,
    )

    assert "returning **5 providers** in total" in report
    assert "SURELOCK_METRICS" not in report
    assert "SURELOCK_FINDINGS_JSON_START" not in report


def test_ensure_report_bundle_filters_findings_without_provider_evidence():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {
                    "name": "Real Provider",
                    "address": "100 Main St, Chicago, IL 60612",
                    "capacity": 40,
                    "license_type": "Day Care Center",
                    "status": "Active",
                    "state": "IL",
                }
            ],
        }
    ]

    report_with_unmatched_finding = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "SURELOCK_METRICS: {\"provider_count\": 1, \"flagged_count\": 2}\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Narrative.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "Dossiers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "Patterns.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Estimate.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Recommendations.\n\n"
        "SURELOCK_FINDINGS_JSON_START\n"
        "[\n"
        "  {\"provider_name\": \"Real Provider\", \"address\": \"100 Main St, Chicago, IL 60612\", \"flag_type\": \"model_anomaly\", \"flag\": \"Test\"},\n"
        "  {\"provider_name\": \"Superior Kids Learning Center\", \"address\": \"3847 W Chicago Ave, Chicago, IL 60651\", \"flag_type\": \"model_anomaly\", \"flag\": \"Unexpected\"}\n"
        "]\n"
        "SURELOCK_FINDINGS_JSON_END"
    )

    report, findings = loop_mod._ensure_report_bundle(
        mode="agent",
        query="Investigate Illinois providers in ZIP 60612",
        report_text=report_with_unmatched_finding,
        assistant_text=[],
        raw_turns=[{"turn": 1, "assistant": "Investigating providers...", "tool_results": []}],
        tool_calls=tool_calls,
    )

    assert "SURELOCK HOMES INVESTIGATION REPORT" in report
    assert "Providers identified in primary search: 1." in report
    assert len(findings) == 0


def test_ensure_report_text_falls_back_when_findings_block_missing():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": f"Provider {i}", "address": f"{i} Main St", "capacity": 10}
                for i in range(5)
            ],
        }
    ]

    no_findings_block_report = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "SURELOCK_METRICS: {\"provider_count\": 5, \"flagged_count\": 0}\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "The investigation began with a search returning **5 providers** in total.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "No major outliers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "No strong clusters.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Moderate confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Limited exposure.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Follow up."
    )

    report = _ensure_report_text(
        mode="agent",
        query="Investigate Illinois providers in Champaign County",
        report_text=no_findings_block_report,
        assistant_text=[],
        raw_turns=[{"turn": 1, "assistant": "Investigating providers...", "tool_results": []}],
        tool_calls=tool_calls,
    )

    assert "Providers identified in primary search: 5." in report


def test_ensure_report_text_falls_back_when_metadata_missing():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": f"Provider {i}", "address": f"{i} Main St", "capacity": 10}
                for i in range(5)
            ],
        }
    ]

    no_metadata_report = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "The investigation began with a search returning **5 providers** in total.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "No major outliers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "No strong clusters.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Moderate confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Limited exposure.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Follow up."
    )

    report = _ensure_report_text(
        mode="agent",
        query="Investigate Illinois providers in Champaign County",
        report_text=no_metadata_report,
        assistant_text=[],
        raw_turns=[{"turn": 1, "assistant": "Investigating providers...", "tool_results": []}],
        tool_calls=tool_calls,
    )

    assert "Providers identified in primary search: 5." in report


def _make_mock_response(content, tool_calls=None, finish_reason="stop"):
    """Build a MagicMock that mimics an OpenAI ChatCompletion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    response = MagicMock()
    response.choices = [choice]
    return response


def test_openrouter_investigation_continues_truncated_turn(monkeypatch):
    final_report_raw = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "SURELOCK_METRICS: {\"provider_count\": 0, \"flagged_count\": 1}\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Narrative.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "Dossiers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "Patterns.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Estimate.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Recommendations.\n\n"
        "SURELOCK_FINDINGS_JSON_START\n"
        "[{\"provider_name\":\"Provider A\",\"address\":\"100 Main St\",\"flag_type\":\"model_anomaly\",\"flag\":\"Test flag\"}]\n"
        "SURELOCK_FINDINGS_JSON_END"
    )
    final_report_expected = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Narrative.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "Dossiers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "Patterns.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Estimate.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Recommendations."
    )
    responses = [
        _make_mock_response(
            content="Chunk A",
            tool_calls=None,
            finish_reason="length",
        ),
        _make_mock_response(
            content="Chunk B",
            tool_calls=None,
            finish_reason="stop",
        ),
        _make_mock_response(
            content=final_report_raw,
            tool_calls=None,
            finish_reason="stop",
        ),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    monkeypatch.setattr(loop_mod, "_create_openai_client", lambda settings: mock_client)
    monkeypatch.setattr(loop_mod, "get_tool_definitions", lambda: [])

    settings = SimpleNamespace(
        openrouter_api_key="test-key",
        openrouter_base_url="https://example.invalid/v1",
        openrouter_site_url="http://localhost",
        openrouter_app_name="Surelock Homes Test",
        max_tokens=2048,
        tool_timeout_seconds=5,
    )

    result = loop_mod._run_openai_investigation(
        query="Investigate Illinois providers in ZIP 60612",
        max_turns=1,
        model="test-model",
        settings=settings,
    )

    assert result["raw_turns"][0]["assistant"] == "Chunk A\n\nChunk B"
    assert result["report_text"] == final_report_expected
    assert len(result["flagged"]) == 1
    assert result["flagged"][0]["provider_name"] == "Provider A"


def test_openrouter_stream_continues_truncated_turn(monkeypatch):
    final_report_raw = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
        "SURELOCK_METRICS: {\"provider_count\": 0, \"flagged_count\": 1}\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Narrative.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "Dossiers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "Patterns.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Estimate.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Recommendations.\n\n"
        "SURELOCK_FINDINGS_JSON_START\n"
        "[{\"provider_name\":\"Provider A\",\"address\":\"100 Main St\",\"flag_type\":\"model_anomaly\",\"flag\":\"Test flag\"}]\n"
        "SURELOCK_FINDINGS_JSON_END"
    )
    final_report_expected = (
        "# SURELOCK HOMES INVESTIGATION REPORT\n\n\n"
        "## 1. INVESTIGATION NARRATIVE\n"
        "Narrative.\n\n"
        "## 2. PROVIDER DOSSIERS\n"
        "Dossiers.\n\n"
        "## 3. PATTERN ANALYSIS\n"
        "Patterns.\n\n"
        "## 4. CONFIDENCE CALIBRATION\n"
        "Confidence.\n\n"
        "## 5. EXPOSURE ESTIMATE\n"
        "Estimate.\n\n"
        "## 6. RECOMMENDATIONS\n"
        "Recommendations."
    )
    responses = [
        _make_mock_response(
            content="Part 1",
            tool_calls=None,
            finish_reason="length",
        ),
        _make_mock_response(
            content="Part 2",
            tool_calls=None,
            finish_reason="stop",
        ),
        _make_mock_response(
            content=final_report_raw,
            tool_calls=None,
            finish_reason="stop",
        ),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    monkeypatch.setattr(loop_mod, "_create_openai_client", lambda settings: mock_client)
    monkeypatch.setattr(loop_mod, "get_tool_definitions", lambda: [])

    settings = SimpleNamespace(
        openrouter_api_key="test-key",
        openrouter_base_url="https://example.invalid/v1",
        openrouter_site_url="http://localhost",
        openrouter_app_name="Surelock Homes Test",
        max_tokens=2048,
        tool_timeout_seconds=5,
    )

    events = list(
        loop_mod._run_openai_investigation_stream(
            query="Investigate Illinois providers in ZIP 60612",
            max_turns=1,
            model="test-model",
            settings=settings,
        )
    )

    complete_event = next(e for e in events if e.get("event") == "complete")
    payload = complete_event["payload"]
    assert payload["raw_turns"][0]["assistant"] == "Part 1\n\nPart 2"
    assert payload["report_text"] == final_report_expected
    assert len(payload["flagged"]) == 1
    assert payload["flagged"][0]["provider_name"] == "Provider A"


# ── _extract_metrics sequence tracking tests ──


def test_extract_metrics_links_ai_sqft_when_property_returns_zero():
    """When get_property_data returns sqft=0, a subsequent calculate_max_capacity
    should link its sqft argument to that address for flagging."""
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": "Test Provider", "address": "123 Oak St, Brooklyn Park, MN", "capacity": 80},
            ],
        },
        {
            "tool": "get_property_data",
            "arguments": {"address": "123 Oak St, Brooklyn Park, MN", "state": "MN"},
            "status": "ok",
            "result": {"status": "found", "building_sqft": 0.0},
        },
        {
            "tool": "calculate_max_capacity",
            "arguments": {"building_sqft": 1200, "state": "MN"},
            "status": "ok",
            "result": {"max_legal_capacity": 22},
        },
        {
            "tool": "check_licensing_status",
            "arguments": {"provider_name": "Test Provider", "state": "MN", "address": "123 Oak St, Brooklyn Park, MN"},
            "status": "ok",
            "result": {"status": "found", "capacity": 80},
        },
    ]
    metrics = _extract_metrics(tool_calls)
    assert metrics["provider_count"] == 1
    assert len(metrics["flagged"]) == 1
    flag = metrics["flagged"][0]
    assert flag["licensed_capacity"] == 80
    assert flag["max_legal_capacity"] == 22
    assert flag["building_sqft"] == 1200


def test_extract_metrics_does_not_overwrite_real_sqft():
    """When get_property_data returns non-zero sqft, a subsequent
    calculate_max_capacity should NOT overwrite it."""
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {"name": "Real Provider", "address": "456 Elm St", "capacity": 50},
            ],
        },
        {
            "tool": "get_property_data",
            "arguments": {"address": "456 Elm St", "state": "IL"},
            "status": "ok",
            "result": {"status": "found", "building_sqft": 2000.0},
        },
        {
            "tool": "calculate_max_capacity",
            "arguments": {"building_sqft": 2000, "state": "IL"},
            "status": "ok",
            "result": {"max_legal_capacity": 37},
        },
        {
            "tool": "check_licensing_status",
            "arguments": {"provider_name": "Real Provider", "state": "IL", "address": "456 Elm St"},
            "status": "ok",
            "result": {"status": "found", "capacity": 50},
        },
    ]
    metrics = _extract_metrics(tool_calls)
    assert len(metrics["flagged"]) == 1
    flag = metrics["flagged"][0]
    assert flag["building_sqft"] == 2000.0  # original sqft, not overwritten


def test_extract_metrics_collects_non_physical_anomaly_flags():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {},
            "status": "ok",
            "result": [
                {
                    "name": "Windy City Care",
                    "address": "606 Southfield St, Chicago, IL 60612",
                    "capacity": 60,
                    "license_type": "Group Day Care Home",
                    "status": "Active",
                    "state": "IL",
                },
                {
                    "name": "Erie Teamsters",
                    "address": "1634 W Van Buren St, Chicago, IL 60612",
                    "capacity": 0,
                    "license_type": "Day Care Center",
                    "status": "License issued",
                    "state": "IL",
                },
                {
                    "name": "iLearn of Grand LLC",
                    "address": "2200 W Grand Ave, Chicago, IL 60612",
                    "capacity": 35,
                    "license_type": "Day Care Center",
                    "status": "Permit issued",
                    "state": "IL",
                },
                {
                    "name": "Rose Key",
                    "address": "3006 W Polk St, Chicago, IL 60612",
                    "capacity": 7,
                    "license_type": "Day Care Home",
                    "status": "Active",
                    "state": "IL",
                },
                {
                    "name": "Giovonna Johnson",
                    "address": "3006 W Polk St, Chicago, IL 60612",
                    "capacity": 7,
                    "license_type": "Day Care Home",
                    "status": "Active",
                    "state": "IL",
                },
            ],
        }
    ]
    metrics = _extract_metrics(tool_calls)
    assert metrics["provider_count"] == 5
    flag_types = {f.get("flag_type") for f in metrics["flagged"]}
    assert "license_type_capacity_mismatch" in flag_types
    assert "zero_capacity_active_license" in flag_types
    assert "permit_only_provider" in flag_types
    assert "shared_address_multiple_licenses" in flag_types
