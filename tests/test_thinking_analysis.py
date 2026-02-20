from agent.thinking_analysis import build_thinking_analysis


def test_build_thinking_analysis_captures_coverage_and_missing_followups():
    tool_calls = [
        {
            "tool": "search_childcare_providers",
            "arguments": {"state": "MN", "zip": "55407"},
            "result": [
                {"name": "Provider A", "address": "1 Main St, Minneapolis, MN"},
                {"name": "Provider B", "address": "2 Main St, Minneapolis, MN"},
            ],
        },
        {
            "tool": "get_property_data",
            "arguments": {"address": "1 Main St, Minneapolis, MN"},
            "result": {"building_sqft": 1200},
        },
        {
            "tool": "get_street_view",
            "arguments": {"address": "2 Main St, Minneapolis, MN"},
            "result": {"status": "ok"},
        },
    ]

    analysis = build_thinking_analysis(
        query="Investigate Minnesota providers in ZIP 55407",
        report_text="Final write-up only referenced Provider A.",
        narration_text="Provider A had concerning signals.",
        thinking=["tool:search_childcare_providers", "Validate property evidence first."],
        tool_calls=tool_calls,
    )

    assert analysis["explicit_thought_steps"] == 1
    assert analysis["tool_reasoning_steps"] == 3
    assert analysis["coverage"]["provider_search_count"] == 2
    assert analysis["coverage"]["investigated_address_count"] == 2
    assert analysis["coverage"]["uninvestigated_provider_estimate"] == 0

    unsurfaced = analysis["unsurfaced_leads"]
    assert any("2 Main St" in lead["subject"] for lead in unsurfaced)

    dropped = analysis["dropped_paths"]
    assert any(
        "calculate_max_capacity" in item["missing_followups"]
        for item in dropped
        if "1 Main St" in item["subject"]
    )
    assert any(
        "get_places_info" in item["missing_followups"]
        for item in dropped
        if "2 Main St" in item["subject"]
    )
