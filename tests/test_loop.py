from agent.loop import run_investigation
from agent.loop import _coerce_tool_payload


def test_offline_investigation_returns_payload():
    result = run_investigation("Investigate Minnesota providers in ZIP 55401", offline=True, max_turns=3, save_output=False)
    assert result["mode"] == "offline"
    assert "narration" in result
    assert "tool_calls" in result
    assert result["status"] == "complete"


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
