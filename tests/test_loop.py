from agent.loop import run_investigation
from agent.loop import _coerce_tool_payload
from agent.loop import _extract_inline_report


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
