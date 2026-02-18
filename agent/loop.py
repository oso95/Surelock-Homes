from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple

import json
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

try:
    import anthropic
except Exception:  # pragma: no cover - optional dependency path
    anthropic = None

try:
    import requests
except Exception:  # pragma: no cover - optional dependency path
    requests = None

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


_OPENROUTER_MAX_CONTEXT_CHARS = 180000
_OPENROUTER_TOOL_PAYLOAD_CHARS = 60000   # must fit 200 providers × ~250 chars each after compaction
_OPENROUTER_MAX_MEDIA_ITEMS = 6          # images, reviews, features — bulky, rarely need all
_OPENROUTER_MAX_LIST_ITEMS = 200         # provider search results — LLM must see all to triage


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


def _coerce_tool_payload(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        return {
            "status": result.get("status"),
            "error": result.get("error"),
        }
    if isinstance(result, list):
        if any(isinstance(item, dict) and item.get("status") for item in result):
            status = next(
                (item.get("status") for item in result if isinstance(item, dict) and item.get("status")),
                "ok",
            )
            if status == "error":
                first_error = next(
                    (item.get("error") for item in result if isinstance(item, dict) and item.get("error")),
                    "Unknown error",
                )
                return {"status": status, "error": first_error}
            return {"status": status, "error": None}
        return {"status": "ok", "error": None}
    return {"status": "ok", "error": str(result) if result is not None and not isinstance(result, str) else None}


def _compact_scalar(value: str, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def _summarize_for_model(value: Any, max_depth: int = 2) -> Any:
    if max_depth <= 0:
        if isinstance(value, str):
            return _compact_scalar(value, 200)
        return str(value)[:200]

    if isinstance(value, dict):
        compact: Dict[str, Any] = {}
        for key, item in value.items():
            if key in {"images", "recent_reviews", "features"} and isinstance(item, list):
                compact[key] = {
                    "count": len(item),
                    "sample": [
                        _summarize_for_model(entry, max_depth=max_depth - 1)
                        for entry in item[:_OPENROUTER_MAX_MEDIA_ITEMS]
                    ],
                }
            elif isinstance(item, list):
                compact[key] = _summarize_for_model(item, max_depth=max_depth - 1)
            elif isinstance(item, dict):
                compact[key] = _summarize_for_model(item, max_depth=max_depth - 1)
            elif isinstance(item, str):
                compact[key] = _compact_scalar(item, 220)
            else:
                compact[key] = item
        return compact

    if isinstance(value, list):
        compact_items = [
            _summarize_for_model(item, max_depth=max_depth - 1)
            for item in value[:_OPENROUTER_MAX_LIST_ITEMS]
        ]
        result: Dict[str, Any] = {"count": len(value)}
        if len(value) > _OPENROUTER_MAX_LIST_ITEMS:
            result["truncated"] = True
        result["items"] = compact_items
        return result

    if isinstance(value, str):
        return _compact_scalar(value, 320)
    return value


def _infer_state_and_zip(query: str) -> Tuple[str, str | None]:
    zip_match = re.search(r"\b\d{5}\b", query)
    # Use word-boundary matching to avoid false positives (e.g. "building" matching "il")
    if re.search(r"\billinois\b", query, re.IGNORECASE) or re.search(r"\bIL\b", query):
        state = "IL"
    elif re.search(r"\bminnesota\b", query, re.IGNORECASE) or re.search(r"\bMN\b", query):
        state = "MN"
    elif zip_match:
        # Infer state from ZIP code prefix when no explicit state is mentioned
        zip_prefix = zip_match.group(0)[:3]
        if zip_prefix in ("600", "601", "602", "603", "604", "605", "606", "607", "608", "609",
                          "610", "611", "612", "613", "614", "615", "616", "617", "618", "619",
                          "620", "622", "623", "624", "625", "626", "627", "628", "629"):
            state = "IL"
        elif zip_prefix in ("550", "551", "553", "554", "555", "556", "557", "558", "559",
                            "560", "561", "562", "563", "564", "565", "566", "567"):
            state = "MN"
        else:
            state = "IL"  # Default to IL if ZIP doesn't match known ranges
    else:
        state = "IL"  # Default to IL rather than MN
    return state, zip_match.group(0) if zip_match else None


def _compact_tool_result(value: Any) -> Any:
    compact = _summarize_for_model(value)
    text = json.dumps(compact, ensure_ascii=False)
    if len(text) <= _OPENROUTER_TOOL_PAYLOAD_CHARS:
        return compact
    fallback = {"payload": _compact_scalar(text, _OPENROUTER_TOOL_PAYLOAD_CHARS)}
    fallback["truncated_length"] = len(text)
    return fallback


def _sanitize_error(exc: Exception) -> str:
    logger.warning("Tool execution error: %s", exc, exc_info=True)
    raw = str(exc)
    raw = re.sub(r"(/[^\s:]+){2,}", "<path>", raw)
    raw = re.sub(r"[A-Za-z0-9_\-]{40,}", "<token>", raw)
    if len(raw) > 200:
        raw = raw[:200] + "..."
    return raw


def _normalize_addr(addr: str) -> str:
    """Normalize address for matching: strip city/state/zip, standardize abbreviations."""
    a = str(addr).upper().strip()
    a = a.split(",")[0].strip()  # Remove city, state, zip
    for full, abbr in [
        ("STREET", "ST"), ("AVENUE", "AVE"), ("ROAD", "RD"), ("DRIVE", "DR"),
        ("BOULEVARD", "BLVD"), ("PLACE", "PL"), ("COURT", "CT"), ("LANE", "LN"),
        ("WEST", "W"), ("EAST", "E"), ("NORTH", "N"), ("SOUTH", "S"),
    ]:
        a = re.sub(r"\b" + full + r"\b", abbr, a)
    return re.sub(r"\s+", " ", a).strip()


def _extract_metrics(tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract provider_count and flagged list from accumulated tool call results."""
    # 1. Provider count: only from the FIRST search call (target area)
    provider_count = 0
    first_search_seen = False

    # 2. Build provider capacity from ALL search results (for flag matching)
    search_providers: Dict[str, Dict[str, Any]] = {}  # normalized_addr -> {name, capacity}

    # 3. Property data: addr_arg -> sqft
    property_sqft: Dict[str, float] = {}

    # 4. Capacity calcs: sqft -> max_legal_capacity
    max_caps: Dict[float, int] = {}

    # 5. Licensing overrides: addr_arg -> capacity
    licensing_cap: Dict[str, Dict[str, Any]] = {}

    for tc in tool_calls:
        tool = tc.get("tool", "")
        result = tc.get("result")
        args = tc.get("arguments", {})

        if tool == "search_childcare_providers" and isinstance(result, list):
            if not first_search_seen:
                provider_count = len(result)
                first_search_seen = True
            for p in result:
                norm = _normalize_addr(p.get("address", ""))
                if norm:
                    search_providers[norm] = {
                        "name": p.get("name", ""),
                        "capacity": int(p.get("capacity", 0) or 0),
                    }

        elif tool == "get_property_data" and isinstance(result, dict):
            addr = args.get("address", "")
            sqft = result.get("building_sqft", 0)
            if addr and sqft:
                property_sqft[addr] = float(sqft)

        elif tool == "calculate_max_capacity" and isinstance(result, dict):
            sqft = args.get("building_sqft", 0)
            max_cap = result.get("max_legal_capacity", 0)
            if sqft and max_cap:
                max_caps[float(sqft)] = int(max_cap)

        elif tool == "check_licensing_status" and isinstance(result, dict):
            if result.get("status") == "found":
                cap = int(result.get("capacity", 0) or 0)
                addr = args.get("address", "")
                name = args.get("provider_name", "")
                if cap and (addr or name):
                    licensing_cap[addr or name] = {"name": name, "capacity": cap}

    # Build flags: for each property with a capacity calc, check if licensed > max
    flagged: List[Dict[str, Any]] = []
    seen_flags: set = set()

    for addr_arg, sqft in property_sqft.items():
        # Find the max legal capacity for this building's sqft
        max_cap = max_caps.get(sqft)
        if not max_cap:
            for calc_sqft, calc_cap in max_caps.items():
                if abs(calc_sqft - sqft) < 1.0:
                    max_cap = calc_cap
                    break
        if not max_cap:
            continue

        # Find the licensed capacity — try licensing data first, then search results
        licensed_cap = 0
        provider_name = ""

        # Try licensing results (keyed by addr_arg or provider_name)
        if addr_arg in licensing_cap:
            licensed_cap = licensing_cap[addr_arg]["capacity"]
            provider_name = licensing_cap[addr_arg]["name"]

        # Fall back to search results (match by normalized address)
        if not licensed_cap:
            norm = _normalize_addr(addr_arg)
            if norm in search_providers:
                licensed_cap = search_providers[norm]["capacity"]
                provider_name = search_providers[norm]["name"]

        if not provider_name:
            norm = _normalize_addr(addr_arg)
            if norm in search_providers:
                provider_name = search_providers[norm]["name"]

        if licensed_cap > max_cap and (provider_name, addr_arg) not in seen_flags:
            seen_flags.add((provider_name, addr_arg))
            flagged.append({
                "provider_name": provider_name or "Unknown",
                "address": addr_arg,
                "licensed_capacity": licensed_cap,
                "max_legal_capacity": max_cap,
                "excess_capacity": licensed_cap - max_cap,
                "building_sqft": sqft,
                "flag": "licensed capacity exceeds physical maximum",
            })

    return {"provider_count": provider_count, "flagged": flagged}


_MAX_CONTINUATION_NUDGES = 3


_REPORT_MARKERS = (
    "INVESTIGATION REPORT",
    "PROVIDER DOSSIERS",
    "EXPOSURE ESTIMATE",
    "PATTERN ANALYSIS",
    "CONFIDENCE CALIBRATION",
    "Investigation complete",
)


def _report_already_written(assistant_text: List[str]) -> bool:
    """Return True if the assistant has already produced a final investigation report."""
    combined = " ".join(assistant_text)
    marker_hits = sum(1 for m in _REPORT_MARKERS if m in combined)
    return marker_hits >= 3


def _continuation_nudge(
    tool_calls: List[Dict[str, Any]],
    current_turn: int,
    max_turns: int,
    *,
    target_state: str = "",
    target_zip: str = "",
    assistant_text: List[str] | None = None,
) -> str | None:
    """Return a nudge message if the LLM stopped early with providers left to investigate."""
    if current_turn >= max_turns:
        return None

    # Count how many times we've already nudged (avoid infinite loops)
    nudge_count = sum(1 for tc in tool_calls if tc.get("tool") == "_nudge")
    if nudge_count >= _MAX_CONTINUATION_NUDGES:
        return None

    # Count total providers from first search and how many have been investigated
    total_providers = 0
    first_search_seen = False
    investigated_addrs: set = set()

    for tc in tool_calls:
        tool = tc.get("tool", "")
        if tool == "search_childcare_providers" and isinstance(tc.get("result"), list) and not first_search_seen:
            total_providers = len(tc["result"])
            first_search_seen = True
        elif tool == "get_property_data":
            addr = tc.get("arguments", {}).get("address", "")
            if addr:
                investigated_addrs.add(addr)

    if not total_providers:
        return None

    investigated = len(investigated_addrs)
    remaining = total_providers - investigated
    turns_left = max_turns - current_turn
    report_written = bool(assistant_text and _report_already_written(assistant_text))

    # If report is already written AND coverage is sufficient, stop cleanly
    if report_written and (remaining < 5 or investigated >= total_providers * 0.7):
        return None

    # If report is written but coverage is poor, nudge to continue + update report
    if report_written:
        tool_calls.append({"tool": "_nudge", "arguments": {}, "status": "ok", "result": {}})
        return (
            f"You wrote the report but have only investigated {investigated} out of "
            f"{total_providers} providers ({remaining} remaining). You still have "
            f"{turns_left} turns left. Continue investigating the unchecked providers — "
            f"pull property data and calculate max capacity for the ones you missed. "
            f"Then write a brief ADDENDUM with any new findings at the end."
        )

    # No report yet — only nudge if significant providers remain uninvestigated
    if remaining < 5 or investigated >= total_providers * 0.7:
        return None

    # Mark the nudge so we can count it
    tool_calls.append({"tool": "_nudge", "arguments": {}, "status": "ok", "result": {}})

    # Build scope reminder to prevent geographic drift
    scope_reminder = ""
    if target_state and target_zip:
        scope_reminder = (
            f" IMPORTANT: Stay focused on the original investigation area: "
            f"state={target_state}, ZIP={target_zip}. Do not search providers in other states "
            f"unless you have found a specific, documented cross-state connection "
            f"(e.g., same registered agent operating in both states)."
        )
    elif target_state:
        scope_reminder = (
            f" IMPORTANT: Stay focused on the original investigation area: "
            f"state={target_state}. Do not search providers in other states."
        )

    return (
        f"You have investigated {investigated} out of {total_providers} providers and still have "
        f"{turns_left} turns remaining. "
        f"DO NOT write the final report yet — continue investigating remaining providers first. "
        f"Writing the report now would waste remaining turns and leave the investigation incomplete. "
        f"Focus on the ones you haven't checked yet — pull property data "
        f"and calculate max capacity to check for physical impossibility. "
        f"Save the report for your final "
        f"turn.{scope_reminder}"
    )


def _enforce_context_budget(messages: List[Dict[str, Any]], max_chars: int = _OPENROUTER_MAX_CONTEXT_CHARS) -> None:
    if max_chars <= 0:
        return
    keep_tail = 4
    while len(json.dumps(messages, ensure_ascii=False)) > max_chars and len(messages) > (1 + keep_tail + 1):
        dropped = len(messages) - 1 - keep_tail
        messages[1:1 + dropped] = [
            {"role": "user", "content": f"[{dropped} earlier messages removed to fit context budget]"}
        ]
    # After trimming, drop any orphaned "tool" messages that appear right after
    # the budget placeholder (index 1).  Their parent assistant message was
    # trimmed, so sending them would violate the tool-result protocol and cause
    # a 400 error from providers that expect each tool result to follow the
    # assistant turn that requested it.
    while len(messages) > 2 and messages[2].get("role") == "tool":
        messages.pop(2)


def _to_openrouter_tools(tool_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for tool in tool_defs:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            }
        )
    return converted


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
        return "error", {"status": "error", "error": f"Tool {name} is not available"}
    try:
        result = handler_map[name](**args) if isinstance(args, dict) else handler_map[name]()
        if isinstance(result, dict) and result.get("status") == "error":
            return "error", result
        return "ok", result
    except Exception as exc:
        return "error", {"status": "error", "error": _sanitize_error(exc)}


def _run_openrouter_investigation(
    query: str,
    max_turns: int,
    model: str,
    settings: Any,
) -> Dict[str, Any]:
    if requests is None:
        raise RuntimeError("requests is required for OpenRouter calls.")

    target_state, target_zip = _infer_state_and_zip(query)
    url = urljoin(settings.openrouter_base_url.rstrip("/") + "/", "chat/completions")
    tool_defs = get_tool_definitions()
    openrouter_tools = _to_openrouter_tools(tool_defs)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": load_system_prompt(target_state=target_state, target_zip=target_zip, max_turns=max_turns)},
        {"role": "user", "content": query},
    ]
    tool_calls: List[Dict[str, Any]] = []
    raw_turns: List[Dict[str, Any]] = []
    thinking_blocks: List[str] = []
    narration = InvestigationNarration(query=query)
    assistant_text: List[str] = []

    for turn in range(1, max_turns + 1):
        _enforce_context_budget(messages)
        request_payload = {
            "model": model,
            "messages": messages,
            "tools": openrouter_tools,
            "tool_choice": "auto",
            "max_tokens": settings.max_tokens,
        }
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_site_url,
                "X-Title": settings.openrouter_app_name,
            },
            json=request_payload,
            timeout=settings.tool_timeout_seconds,
        )
        if not resp.ok:
            logger.warning("OpenRouter request failed: %s %s", resp.status_code, resp.text)
            error_body = resp.text[:500] if resp.text else "no response body"
            raise RuntimeError(f"OpenRouter request failed: {resp.status_code} — {error_body}")

        completion = resp.json()
        choice = completion.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")
        assistant_text_block = message.get("content", "")
        tool_calls_block = message.get("tool_calls", [])

        turn_summary = {"turn": turn, "assistant": "", "tool_results": []}
        if assistant_text_block:
            turn_summary["assistant"] = str(assistant_text_block).strip()
            narration.add_narration(str(assistant_text_block))
            narration.add_assistant_text(str(assistant_text_block))
            assistant_text.append(str(assistant_text_block))

        assistant_history_entry = {"role": "assistant", "content": assistant_text_block or ""}
        if tool_calls_block:
            assistant_history_entry["tool_calls"] = tool_calls_block
        messages.append(assistant_history_entry)

        if not tool_calls_block:
            # Check if the LLM stopped early with providers left to investigate
            nudge = _continuation_nudge(
                tool_calls, turn, max_turns,
                target_state=target_state, target_zip=target_zip or "",
                assistant_text=assistant_text,
            )
            if nudge:
                raw_turns.append(turn_summary)
                messages.append({"role": "user", "content": nudge})
                continue
            raw_turns.append(turn_summary)
            break

        for tool_call in tool_calls_block:
            tool_name = (tool_call.get("function") or {}).get("name")
            raw_arguments = (tool_call.get("function") or {}).get("arguments", "{}")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    arguments = {}
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                arguments = {}
            if not tool_name:
                continue
            tool_status, result = _call_tool(tool_name, arguments)
            tool_calls.append({"tool": tool_name, "arguments": arguments, "status": tool_status, "result": result})
            narration.add_tool_call(tool_name, arguments, result)
            thinking_blocks.append(f"tool:{tool_name}")
            turn_summary["tool_results"].append({"tool": tool_name, "result": result, "status": tool_status})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": tool_name,
                    "content": json.dumps(_compact_tool_result(result)),
                }
            )

        raw_turns.append(turn_summary)

        if finish_reason in {"stop", "tool_calls"} and not tool_calls_block:
            break

        if finish_reason == "stop" and not any(tc.get("function") for tc in tool_calls_block):
            break

    metrics = _extract_metrics(tool_calls)
    return {
        "query": query,
        "mode": "agent",
        "status": "complete",
        "turns": len(raw_turns),
        "provider_count": metrics["provider_count"],
        "flagged": metrics["flagged"],
        "narration": narration.to_markdown(),
        "assistant_text": "\n".join(assistant_text) or "Investigation complete.",
        "tool_calls": tool_calls,
        "thinking": thinking_blocks,
        "raw_turns": raw_turns,
    }


def _run_openrouter_investigation_stream(
    query: str,
    max_turns: int,
    model: str,
    settings: Any,
) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
    if requests is None:
        raise RuntimeError("requests is required for OpenRouter calls.")

    target_state, target_zip = _infer_state_and_zip(query)
    yield {
        "event": "start",
        "query": query,
        "state": target_state,
        "zip": target_zip,
        "provider": "openrouter",
        "max_turns": max_turns,
    }

    url = urljoin(settings.openrouter_base_url.rstrip("/") + "/", "chat/completions")
    tool_defs = get_tool_definitions()
    openrouter_tools = _to_openrouter_tools(tool_defs)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": load_system_prompt(target_state=target_state, target_zip=target_zip, max_turns=max_turns)},
        {"role": "user", "content": query},
    ]
    tool_calls: List[Dict[str, Any]] = []
    raw_turns: List[Dict[str, Any]] = []
    thinking_blocks: List[str] = []
    narration = InvestigationNarration(query=query)
    assistant_text: List[str] = []

    try:
        for turn in range(1, max_turns + 1):
            _enforce_context_budget(messages)
            yield {"event": "turn_start", "turn": turn, "max_turns": max_turns}

            request_payload = {
                "model": model,
                "messages": messages,
                "tools": openrouter_tools,
                "tool_choice": "auto",
                "max_tokens": settings.max_tokens,
            }
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": settings.openrouter_site_url,
                    "X-Title": settings.openrouter_app_name,
                },
                json=request_payload,
                timeout=settings.tool_timeout_seconds,
            )
            if not resp.ok:
                logger.warning("OpenRouter request failed: %s %s", resp.status_code, resp.text)
                error_body = resp.text[:500] if resp.text else "no response body"
                raise RuntimeError(f"OpenRouter request failed: {resp.status_code} — {error_body}")

            completion = resp.json()
            choice = completion.get("choices", [{}])[0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason")
            assistant_text_block = message.get("content", "")
            tool_calls_block = message.get("tool_calls", [])

            turn_summary = {"turn": turn, "assistant": "", "tool_results": []}
            if assistant_text_block:
                assistant_text_block = str(assistant_text_block).strip()
                turn_summary["assistant"] = assistant_text_block
                narration.add_narration(assistant_text_block)
                narration.add_assistant_text(assistant_text_block)
                assistant_text.append(assistant_text_block)
                yield {
                    "event": "assistant_text",
                    "turn": turn,
                    "text": assistant_text_block,
                }

            assistant_history_entry = {"role": "assistant", "content": assistant_text_block or ""}
            if tool_calls_block:
                assistant_history_entry["tool_calls"] = tool_calls_block
            messages.append(assistant_history_entry)

            if not tool_calls_block:
                nudge = _continuation_nudge(
                    tool_calls, turn, max_turns,
                    target_state=target_state, target_zip=target_zip or "",
                    assistant_text=assistant_text,
                )
                if nudge:
                    raw_turns.append(turn_summary)
                    messages.append({"role": "user", "content": nudge})
                    yield {"event": "nudge", "turn": turn, "message": nudge}
                    continue
                raw_turns.append(turn_summary)
                break

            for tool_call in tool_calls_block:
                tool_name = (tool_call.get("function") or {}).get("name")
                raw_arguments = (tool_call.get("function") or {}).get("arguments", "{}")
                if isinstance(raw_arguments, str):
                    try:
                        arguments = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                elif isinstance(raw_arguments, dict):
                    arguments = raw_arguments
                else:
                    arguments = {}
                if not tool_name:
                    continue

                yield {
                    "event": "tool_call",
                    "turn": turn,
                    "tool": tool_name,
                    "arguments": arguments,
                }

                tool_status, result = _call_tool(tool_name, arguments)
                if tool_status == "error":
                    yield {
                        "event": "tool_error",
                        "turn": turn,
                        "tool": tool_name,
                        "error": _coerce_tool_payload(result).get("error") or "Unknown error",
                    }
                else:
                    yield {
                        "event": "tool_result",
                        "turn": turn,
                        "tool": tool_name,
                        "status": tool_status,
                    }

                tool_calls.append({"tool": tool_name, "arguments": arguments, "status": tool_status, "result": result})
                narration.add_tool_call(tool_name, arguments, result)
                thinking_blocks.append(f"tool:{tool_name}")
                turn_summary["tool_results"].append({"tool": tool_name, "result": result, "status": tool_status})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": tool_name,
                        "content": json.dumps(_compact_tool_result(result)),
                    }
                )

                yield {
                    "event": "tool_payload",
                    "turn": turn,
                    "tool": tool_name,
                    "status": tool_status,
                    "result": _coerce_tool_payload(result),
                }

            raw_turns.append(turn_summary)
            yield {"event": "turn_done", "turn": turn, "tools": [item["tool"] for item in turn_summary["tool_results"]]}

            if finish_reason in {"stop", "tool_calls"} and not tool_calls_block:
                break

            if finish_reason == "stop" and not any(tc.get("function") for tc in tool_calls_block):
                break

        metrics = _extract_metrics(tool_calls)
        result_payload = {
            "query": query,
            "mode": "agent",
            "status": "complete",
            "turns": len(raw_turns),
            "provider_count": metrics["provider_count"],
            "flagged": metrics["flagged"],
            "narration": narration.to_markdown(),
            "assistant_text": "\n".join(assistant_text) or "Investigation complete.",
            "tool_calls": tool_calls,
            "thinking": thinking_blocks,
            "raw_turns": raw_turns,
        }
        yield {"event": "complete", "payload": result_payload}
        return result_payload

    except Exception as exc:
        logger.warning("Streaming OpenRouter investigation failed for query %s: %s", query, exc, exc_info=True)
        yield {
            "event": "error",
            "error": _sanitize_error(exc),
            "query": query,
        }
        metrics = _extract_metrics(tool_calls)
        result_payload = {
            "query": query,
            "mode": "agent",
            "status": "error",
            "turns": len(raw_turns),
            "provider_count": metrics["provider_count"],
            "flagged": metrics["flagged"],
            "narration": narration.to_markdown(),
            "assistant_text": "\n".join(assistant_text) or "Investigation failed.",
            "tool_calls": tool_calls,
            "thinking": thinking_blocks,
            "raw_turns": raw_turns,
            "error": _sanitize_error(exc),
        }
        yield {"event": "complete", "payload": result_payload}
        return result_payload


def _offline_investigation(query: str, max_turns: int = 8) -> Dict[str, Any]:
    state, zip_code = _infer_state_and_zip(query)

    narration = InvestigationNarration(query=query)
    providers = search_childcare_providers(state=state, zip=zip_code, offline=True)

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
        property_data = get_property_data(addr, state=state, offline=True)
        sqft = float(property_data.get("building_sqft", 0) or 0)
        calc = calculate_max_capacity(sqft, state=state, usable_ratio=0.65)
        places = get_places_info(addr, name=provider.get("name", ""))
        licensing = check_licensing_status(provider.get("name", ""), state=state, address=addr)
        reg = check_business_registration(provider.get("name", ""), state=state, search_type="business")

        turn_tools = []
        turn_tools.append({"tool": "get_property_data", "input": {"address": addr, "state": state}, "result": property_data})
        turn_tools.append({"tool": "calculate_max_capacity", "input": {"building_sqft": sqft, "state": state}, "result": calc})
        turn_tools.append({"tool": "get_places_info", "input": {"address": addr, "name": provider.get("name", "")}, "result": places})
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


def _offline_investigation_stream(query: str, max_turns: int = 8):
    """Generator yielding SSE-friendly dicts as the investigation progresses."""
    state, zip_code = _infer_state_and_zip(query)

    yield {"event": "start", "query": query, "state": state, "zip": zip_code}

    narration = InvestigationNarration(query=query)
    providers = search_childcare_providers(state=state, zip=zip_code, offline=True)

    yield {"event": "providers_loaded", "count": len(providers)}

    if not providers:
        narration.add_narration("No providers were returned for the requested area with local fallback data.")
        yield {
            "event": "complete",
            "payload": {
                "query": query, "mode": "offline", "status": "complete",
                "provider_count": 0, "flagged": [], "turns": 1,
                "narration": narration.to_markdown(),
                "assistant_text": "No providers found in fallback dataset.",
                "tool_calls": [], "thinking": [], "raw_turns": [
                    {"turn": 1, "assistant": "No providers found in area.", "tools": []}
                ],
            },
        }
        return

    flagged = []
    raw_turns = []
    tool_calls = []
    total = min(len(providers), max_turns)

    for idx, provider in enumerate(providers[:max_turns], start=1):
        name = provider.get("name", "Provider")
        addr = provider.get("address", "")
        capacity = int(provider.get("capacity", 0))

        yield {"event": "provider_start", "turn": idx, "total": total, "name": name, "address": addr}

        try:
            property_data = get_property_data(addr, state=state, offline=True)
        except Exception as exc:
            logger.warning("get_property_data failed for %s: %s", addr, exc)
            property_data = {"building_sqft": 0, "status": "error", "error": str(type(exc).__name__)}
            yield {"event": "tool_error", "turn": idx, "tool": "get_property_data", "error": type(exc).__name__}
        sqft = float(property_data.get("building_sqft", 0) or 0)
        yield {"event": "tool_result", "turn": idx, "tool": "get_property_data", "sqft": sqft}

        calc = calculate_max_capacity(sqft, state=state, usable_ratio=0.65)
        yield {"event": "tool_result", "turn": idx, "tool": "calculate_max_capacity", "max_legal": calc["max_legal_capacity"]}

        try:
            places = get_places_info(addr, name=name)
        except Exception as exc:
            logger.warning("get_places_info failed for %s: %s", addr, exc)
            places = {"status": "error", "error": str(type(exc).__name__)}
            yield {"event": "tool_error", "turn": idx, "tool": "get_places_info", "error": type(exc).__name__}
        else:
            yield {"event": "tool_result", "turn": idx, "tool": "get_places_info"}

        try:
            licensing = check_licensing_status(name, state=state, address=addr)
        except Exception as exc:
            logger.warning("check_licensing_status failed for %s: %s", name, exc)
            licensing = {"status": "error", "error": str(type(exc).__name__)}
            yield {"event": "tool_error", "turn": idx, "tool": "check_licensing_status", "error": type(exc).__name__}
        else:
            yield {"event": "tool_result", "turn": idx, "tool": "check_licensing_status"}

        try:
            reg = check_business_registration(name, state=state, search_type="business")
        except Exception as exc:
            logger.warning("check_business_registration failed for %s: %s", name, exc)
            reg = {"status": "error", "error": str(type(exc).__name__)}
            yield {"event": "tool_error", "turn": idx, "tool": "check_business_registration", "error": type(exc).__name__}
        else:
            yield {"event": "tool_result", "turn": idx, "tool": "check_business_registration"}

        turn_tools = [
            {"tool": "get_property_data", "input": {"address": addr, "state": state}, "result": property_data},
            {"tool": "calculate_max_capacity", "input": {"building_sqft": sqft, "state": state}, "result": calc},
            {"tool": "get_places_info", "input": {"address": addr, "name": name}, "result": places},
            {"tool": "check_licensing_status", "input": {"provider_name": name, "state": state, "address": addr}, "result": licensing},
            {"tool": "check_business_registration", "input": {"name": name, "state": state, "search_type": "business"}, "result": reg},
        ]
        tool_calls.extend(turn_tools)

        diff = capacity - calc["max_legal_capacity"]
        is_flagged = diff > 0
        if is_flagged:
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
                f"{name} at {addr} shows suspicious capacity math: "
                f"licensed {capacity} > max legal {calc['max_legal_capacity']}."
            )

        raw_turns.append({
            "turn": idx,
            "provider": name,
            "tools": turn_tools,
            "flagged": is_flagged,
        })

        yield {
            "event": "provider_done",
            "turn": idx,
            "total": total,
            "name": name,
            "flagged": is_flagged,
            "licensed": capacity,
            "max_legal": calc["max_legal_capacity"],
            "total_flags": len(flagged),
        }

    summary_lines = [
        f"Investigated {len(providers)} provider records for state {state}.",
        f"Potential physical anomalies: {len(flagged)}",
    ]
    if flagged:
        summary_lines.append("The most likely issues involve capacity versus building size.")
    summary = " ".join(summary_lines)

    yield {
        "event": "complete",
        "payload": {
            "query": query,
            "mode": "offline",
            "status": "complete",
            "provider_count": len(providers),
            "flagged": flagged,
            "turns": total,
            "narration": narration.to_markdown(),
            "assistant_text": summary,
            "tool_calls": tool_calls,
            "thinking": ["Offline deterministic reasoning mode used for stable results."],
            "raw_turns": raw_turns,
        },
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

    if offline:
        result = _offline_investigation(query, max_turns=max_turns)
        if save_output:
            _persist_investigation(run_id, result, output_dir=output_dir)
        return result

    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter.")
        result = _run_openrouter_investigation(
            query,
            max_turns=max_turns,
            model=model or settings.model,
            settings=settings,
        )
    elif settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key or anthropic is None:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic.")
        target_state_anthropic, target_zip_anthropic = _infer_state_and_zip(query)
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
                system=load_system_prompt(target_state=target_state_anthropic, target_zip=target_zip_anthropic, max_turns=max_turns),
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

        metrics = _extract_metrics(tool_calls)
        result = {
            "query": query,
            "mode": "agent",
            "status": "complete",
            "turns": len(raw_turns),
            "provider_count": metrics["provider_count"],
            "flagged": metrics["flagged"],
            "narration": narration.to_markdown(),
            "assistant_text": "\n".join(assistant_text) or "Investigation complete.",
            "tool_calls": tool_calls,
            "thinking": thinking_blocks,
            "raw_turns": raw_turns,
        }
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Set LLM_PROVIDER=anthropic or openrouter.")

    if save_output:
        _persist_investigation(run_id, result, output_dir=output_dir)
    return result


def run_investigation_stream(
    query: str,
    max_turns: int = 8,
    offline: bool = False,
    model: str | None = None,
) -> Generator[Dict[str, Any], None, None]:
    settings = load_settings()

    if offline:
        yield from _offline_investigation_stream(query, max_turns=max_turns)
        return

    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter.")
        yield from _run_openrouter_investigation_stream(
            query,
            max_turns=max_turns,
            model=model or settings.model,
            settings=settings,
        )
        return

    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key or anthropic is None:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic.")
        # No fine-grained streaming with Anthropic in this path; provide a single completion event.
        yield {"event": "start", "query": query, "provider": "anthropic", "max_turns": max_turns}
        try:
            result = run_investigation(query, max_turns=max_turns, offline=False, model=model, save_output=False)
            yield {"event": "complete", "payload": result}
        except Exception as exc:
            yield {"event": "error", "error": _sanitize_error(exc), "query": query}
            result = {"query": query, "status": "error", "error": _sanitize_error(exc), "mode": "agent"}
            yield {"event": "complete", "payload": result}
        return
    raise RuntimeError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Set LLM_PROVIDER=anthropic or openrouter.")


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
