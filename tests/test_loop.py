from types import SimpleNamespace
from unittest.mock import MagicMock

import agent.loop as loop_mod
from agent.loop import run_investigation
from agent.loop import _coerce_tool_payload
from agent.loop import _extract_inline_report
from agent.loop import _extract_metrics
from agent.loop import _extract_text


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


def test_extract_text_handles_structured_content():
    content = [
        {"type": "text", "text": "First chunk"},
        {"type": "text", "text": "Second chunk"},
    ]
    assert _extract_text(content) == "First chunk\nSecond chunk"


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
            content="Final report text",
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
    assert result["report_text"] == "Final report text"


def test_openrouter_stream_continues_truncated_turn(monkeypatch):
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
            content="Report body",
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
    assert payload["report_text"] == "Report body"


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
