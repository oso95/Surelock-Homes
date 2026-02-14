from agent.loop import run_investigation


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

