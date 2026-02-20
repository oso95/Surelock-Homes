from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any, Dict, List, Set


_DEEP_INVESTIGATION_TOOLS: Set[str] = {
    "get_property_data",
    "get_street_view",
    "get_places_info",
    "check_licensing_status",
    "check_business_registration",
    "calculate_max_capacity",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _subject_from_tool_call(tool_call: Dict[str, Any]) -> str:
    args = _safe_dict(tool_call.get("arguments") or tool_call.get("input"))
    for key in ("address", "provider_name", "name", "zip", "city"):
        val = str(args.get(key, "")).strip()
        if val:
            return val
    return ""


def _provider_search_count(tool_calls: List[Dict[str, Any]]) -> int | None:
    for call in tool_calls:
        if call.get("tool") != "search_childcare_providers":
            continue
        result = call.get("result")
        if isinstance(result, list):
            return len(result)
        if isinstance(result, dict) and isinstance(result.get("providers"), list):
            return len(result["providers"])
    return None


def _signal_label(tool_name: str) -> str:
    labels = {
        "search_childcare_providers": "provider_search",
        "get_property_data": "property_constraints",
        "get_street_view": "visual_verification",
        "get_places_info": "business_presence",
        "check_licensing_status": "licensing_validation",
        "check_business_registration": "entity_validation",
        "calculate_max_capacity": "capacity_math",
        "geocode_address": "location_validation",
    }
    return labels.get(tool_name, tool_name or "unknown")


def build_thinking_analysis(
    *,
    query: str,
    report_text: str,
    narration_text: str,
    thinking: List[Any],
    tool_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    report_plus_narration = f"{report_text or ''}\n{narration_text or ''}"
    normalized_report = _normalize(report_plus_narration)

    explicit_thoughts = [
        str(item).strip()
        for item in (thinking or [])
        if str(item).strip() and not str(item).startswith("tool:")
    ]

    signal_counts: Counter[str] = Counter()
    subject_to_tools: Dict[str, Set[str]] = defaultdict(set)
    unsurfaced_leads: List[Dict[str, Any]] = []
    seen_unsurfaced: Set[tuple[str, str]] = set()

    for call in tool_calls or []:
        tool_name = str(call.get("tool", "")).strip()
        if not tool_name:
            continue
        signal_counts[_signal_label(tool_name)] += 1

        subject = _subject_from_tool_call(call)
        if subject:
            subject_to_tools[subject].add(tool_name)

        if tool_name not in _DEEP_INVESTIGATION_TOOLS:
            continue
        if not subject:
            continue
        normalized_subject = _normalize(subject)
        if not normalized_subject:
            continue
        if normalized_subject in normalized_report:
            continue

        key = (tool_name, normalized_subject)
        if key in seen_unsurfaced:
            continue
        seen_unsurfaced.add(key)
        unsurfaced_leads.append(
            {
                "tool": tool_name,
                "subject": subject,
                "reason": "Investigated in tools but not referenced in final narrative/report text.",
            }
        )

    dropped_paths: List[Dict[str, Any]] = []
    for subject, tools in subject_to_tools.items():
        missing_followups: List[str] = []
        if "get_property_data" in tools and "calculate_max_capacity" not in tools:
            missing_followups.append("calculate_max_capacity")
        if "get_street_view" in tools and "get_places_info" not in tools:
            missing_followups.append("get_places_info")
        if ("check_business_registration" in tools or "get_places_info" in tools) and "check_licensing_status" not in tools:
            missing_followups.append("check_licensing_status")
        if not missing_followups:
            continue
        dropped_paths.append(
            {
                "subject": subject,
                "started_with": sorted(tools),
                "missing_followups": missing_followups,
            }
        )

    provider_total = _provider_search_count(tool_calls)
    investigated_subjects = len(subject_to_tools)
    investigated_addresses = len(
        [
            s
            for s in subject_to_tools
            if any(ch.isdigit() for ch in s) and any(ch.isalpha() for ch in s)
        ]
    )
    uninvestigated_estimate = None
    if provider_total is not None:
        uninvestigated_estimate = max(provider_total - investigated_addresses, 0)

    signals = [
        {"signal": signal, "count": count}
        for signal, count in signal_counts.most_common()
    ]

    notes: List[str] = []
    if not explicit_thoughts:
        notes.append(
            "No explicit model-thinking blocks were returned by the provider; analysis is reconstructed from tool sequence and coverage."
        )
    if provider_total is None:
        notes.append("Could not infer provider baseline count from tool calls.")

    summary_parts = [
        f"Captured {len(explicit_thoughts)} explicit thought step(s).",
        f"Observed {len(tool_calls or [])} tool-driven reasoning step(s).",
        f"Found {len(unsurfaced_leads)} unsurfaced lead(s) and {len(dropped_paths)} dropped path(s).",
    ]
    if provider_total is not None:
        summary_parts.append(
            f"Coverage estimate: investigated {investigated_addresses}/{provider_total} address-level targets."
        )

    return {
        "query": query,
        "summary": " ".join(summary_parts),
        "explicit_thought_steps": len(explicit_thoughts),
        "tool_reasoning_steps": len(tool_calls or []),
        "signals_considered": signals,
        "unsurfaced_leads": unsurfaced_leads[:12],
        "dropped_paths": dropped_paths[:12],
        "coverage": {
            "provider_search_count": provider_total,
            "investigated_subject_count": investigated_subjects,
            "investigated_address_count": investigated_addresses,
            "uninvestigated_provider_estimate": uninvestigated_estimate,
        },
        "notes": notes,
    }
