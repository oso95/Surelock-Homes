from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import json

try:
    import anthropic
except Exception:  # pragma: no cover - optional dependency path
    anthropic = None

from config import OUTPUT_DIR, load_settings
from agent.narration import InvestigationNarration
from agent.prompt import load_system_prompt
from tools.definitions import get_tool_definitions
from tools.providers import search_childcare_providers
from tools.property import get_property_data
from tools.street_view import get_street_view
from tools.places import get_places_info
from tools.licensing import check_licensing_status
from tools.business_reg import check_business_registration
from tools.capacity import calculate_max_capacity
from tools.geocoding import geocode_address


def _normalize_blocks(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, list):
        normalized: List[Dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict):
                normalized.append(block)
            else:
                block_type = getattr(block, "type", None)
                if block_type is None:
                    continue
                payload = {"type": block_type}
                if hasattr(block, "text"):
                    payload["text"] = getattr(block, "text")
                if hasattr(block, "thinking"):
                    payload["thinking"] = getattr(block, "thinking")
                if hasattr(block, "name"):
                    payload["name"] = getattr(block, "name")
                    payload["input"] = getattr(block, "input", {})
                    payload["id"] = getattr(block, "id", None)
                normalized.append(payload)
        return normalized
    return []


def _call_tool(name: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    handler_map = {
        "search_childcare_providers": search_childcare_providers,
        "get_property_data": get_property_data,
        "get_street_view": get_street_view,
        "get_places_info": get_places_info,
        "check_licensing_status": check_licensing_status,
        "check_business_registration": check_business_registration,
        "calculate_max_capacity": calculate_max_capacity,
        "geocode_address": geocode_address,
    }

    if name not in handler_map:
        return "error", {"error": f"Tool {name} is not available"}
    try:
        result = handler_map[name](**args) if isinstance(args, dict) else handler_map[name]()
        return "ok", result
    except Exception as exc:
        return "error", {"error": str(exc)}


def _offline_investigation(query: str, max_turns: int = 8) -> Dict[str, Any]:
    lower = query.lower()
    state = "IL" if "il" in lower or "illinois" in lower else "MN"
    state = "MN" if "mn" in lower or "minnesota" in lower else state
    zip_code = None
    import re

    zip_match = re.search(r"\b\d{5}\b", query)
    if zip_match:
        zip_code = zip_match.group(0)

    narration = InvestigationNarration(query=query)
    providers = search_childcare_providers(state=state, zip=zip_code)

    if not providers:
        narration.add_narration("No providers were returned for the requested area with local fallback data.")
        result = {
            "query": query,
            "mode": "offline",
            "status": "complete",
            "provider_count": 0,
            "flagged": [],
            "turns": 1,
            "narration": narration.to_markdown(),
            "assistant_text": "No providers found in fallback dataset.",
            "tool_calls": [],
            "thinking": [],
            "raw_turns": [
                {
                    "turn": 1,
                    "assistant": "No providers found in area.",
                    "tools": [],
                }
            ],
        }
        return result

    flagged = []
    raw_turns = []
    tool_calls = []
    for idx, provider in enumerate(providers[:max_turns], start=1):
        addr = provider.get("address", "")
        capacity = int(provider.get("capacity", 0))
        property_data = get_property_data(addr, state=state)
        sqft = float(property_data.get("building_sqft", 0) or 0)
        calc = calculate_max_capacity(sqft, state=state, usable_ratio=0.65)
        places = get_places_info(addr)
        licensing = check_licensing_status(provider.get("name", ""), state=state, address=addr)
        reg = check_business_registration(provider.get("name", ""), state=state, search_type="business")

        turn_tools = []
        turn_tools.append({"tool": "get_property_data", "input": {"address": addr, "state": state}, "result": property_data})
        turn_tools.append({"tool": "calculate_max_capacity", "input": {"building_sqft": sqft, "state": state}, "result": calc})
        turn_tools.append({"tool": "get_places_info", "input": {"address": addr}, "result": places})
        turn_tools.append({"tool": "check_licensing_status", "input": {"provider_name": provider.get("name", ""), "state": state, "address": addr}, "result": licensing})
        turn_tools.append({"tool": "check_business_registration", "input": {"name": provider.get("name", ""), "state": state, "search_type": "business"}, "result": reg})
        tool_calls.extend(turn_tools)

        diff = capacity - calc["max_legal_capacity"]
        if diff > 0:
            note = {
                "provider": provider,
                "licensed_capacity": capacity,
                "max_legal_capacity": calc["max_legal_capacity"],
                "excess_capacity": diff,
                "building_sqft": sqft,
                "property_data": property_data,
                "places": places,
                "licensing": licensing,
                "business_registration": reg,
                "flags": [
                    "licensed capacity exceeds physical maximum",
                    "visually inconsistent if place data has low confidence score",
                ],
            }
            flagged.append(note)
            narration.add_narration(
                f"{provider.get('name', 'Provider')} at {addr} shows suspicious capacity math: "
                f"licensed {capacity} > max legal {calc['max_legal_capacity']}."
            )
        raw_turns.append(
            {
                "turn": idx,
                "provider": provider.get("name"),
                "tools": turn_tools,
                "flagged": any(i["provider"]["name"] == provider.get("name", "") for i in flagged),
            }
        )

    summary_lines = [
        f"Investigated {len(providers)} provider records for state {state}.",
        f"Potential physical anomalies: {len(flagged)}",
    ]
    if flagged:
        summary_lines.append("The most likely issues involve capacity versus building size.")
    summary = " ".join(summary_lines)
    return {
        "query": query,
        "mode": "offline",
        "status": "complete",
        "provider_count": len(providers),
        "flagged": flagged,
        "turns": min(len(providers), max_turns),
        "narration": narration.to_markdown(),
        "assistant_text": summary,
        "tool_calls": tool_calls,
        "thinking": ["Offline deterministic reasoning mode used for stable results."],
        "raw_turns": raw_turns,
    }


def _persist_investigation(run_id: str, payload: Dict[str, Any], output_dir: Path | None = None) -> None:
    if output_dir is None:
        return
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (run_dir / "narration.md").write_text(payload.get("narration", ""), encoding="utf-8")
    (run_dir / "tool_calls.json").write_text(json.dumps(payload.get("tool_calls", []), indent=2), encoding="utf-8")


def run_investigation(
    query: str,
    *,
    max_turns: int = 8,
    offline: bool = False,
    output_dir: Path | None = OUTPUT_DIR,
    model: str | None = None,
    save_output: bool = True,
) -> Dict[str, Any]:
    settings = load_settings()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if offline or not settings.anthropic_api_key or anthropic is None:
        result = _offline_investigation(query, max_turns=max_turns)
        if save_output:
            _persist_investigation(run_id, result, output_dir=output_dir)
        return result

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    narration = InvestigationNarration(query=query)
    messages = [{"role": "user", "content": query}]
    tool_defs = get_tool_definitions()
    tool_calls = []
    raw_turns = []
    assistant_text = []
    thinking_blocks: List[str] = []

    for turn in range(1, max_turns + 1):
        response = client.messages.create(
            model=model or settings.model,
            max_tokens=settings.max_tokens,
            thinking={"type": "enabled", "budget_tokens": settings.thinking_budget_tokens},
            system=load_system_prompt(),
            tools=tool_defs,
            messages=messages,
        )
        content_blocks = _normalize_blocks(response.content)
        assistant_payload: List[Dict[str, Any]] = []
        turn_tool_results = []
        turn_summary = {"turn": turn, "assistant": "", "tool_results": []}

        for block in content_blocks:
            block_type = block.get("type")
            if block_type == "thinking":
                thought = block.get("thinking", "")
                narration.add_thinking(thought)
                thinking_blocks.append(thought)
            elif block_type == "text":
                text = block.get("text", "")
                assistant_payload.append(block)
                narration.add_narration(text)
                narration.add_assistant_text(text)
                assistant_text.append(text)
                turn_summary["assistant"] = (turn_summary["assistant"] + " " + text).strip()
            elif block_type == "tool_use":
                assistant_payload.append(block)
                tool_name = block.get("name")
                arguments = block.get("input", {})
                tool_status, result = _call_tool(tool_name, arguments)
                tool_calls.append({"tool": tool_name, "arguments": arguments, "status": tool_status, "result": result})
                narration.add_tool_call(tool_name, arguments, result)
                turn_tool_results.append({"tool": tool_name, "result": result, "status": tool_status})
                messages.append(
                    {
                        "role": "tool",
                        "tool_use_id": block.get("id"),
                        "content": json.dumps(result),
                    }
                )

        messages.append({"role": "assistant", "content": assistant_payload})
        raw_turns.append(turn_summary)
        if getattr(response, "stop_reason", None) == "end_turn":
            break

    result = {
        "query": query,
        "mode": "agent",
        "status": "complete",
        "turns": len(raw_turns),
        "provider_count": 0,
        "flagged": [],
        "narration": narration.to_markdown(),
        "assistant_text": "\n".join(assistant_text) or "Investigation complete.",
        "tool_calls": tool_calls,
        "thinking": thinking_blocks,
        "raw_turns": raw_turns,
    }
    if save_output:
        _persist_investigation(run_id, result, output_dir=output_dir)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Surelock Homes investigation.")
    parser.add_argument("query")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    output = run_investigation(args.query, offline=args.offline, max_turns=args.max_turns, save_output=not args.no_save)
    print(json.dumps(output, indent=2))

