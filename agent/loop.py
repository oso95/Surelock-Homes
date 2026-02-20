from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Tuple

logger = logging.getLogger(__name__)

try:
    import anthropic
except Exception:  # pragma: no cover - optional dependency path
    anthropic = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency path
    OpenAI = None

from agent.narration import InvestigationNarration
from agent.prompt import load_system_prompt
from agent.thinking_analysis import build_thinking_analysis
from config import OUTPUT_DIR, load_settings
from tools.business_reg import check_business_registration
from tools.capacity import calculate_max_capacity
from tools.definitions import get_tool_definitions
from tools.geocoding import geocode_address
from tools.licensing import check_licensing_status
from tools.places import get_places_info
from tools.property import get_property_data
from tools.providers import search_childcare_providers
from tools.satellite_view import get_satellite_view
from tools.street_view import get_street_view


_LLM_MAX_CONTEXT_CHARS = 180000
_LLM_TOOL_PAYLOAD_CHARS = 60000   # must fit 200 providers × ~250 chars each after compaction
_LLM_MAX_MEDIA_ITEMS = 6          # images, reviews, features — bulky, rarely need all
_LLM_MAX_LIST_ITEMS = 200         # provider search results — LLM must see all to triage
_LLM_MAX_CONTINUATIONS = 3
_LLM_REPORT_TIMEOUT_SECONDS = 180  # report generation needs far more time than tool calls
_LLM_CONTINUE_PROMPT = (
    "Continue exactly where your previous response ended. "
    "Do not restart and do not repeat text."
)


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


def _extract_text(content: Any) -> str:
    """Extract textual content from OpenRouter message.content shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "output_text", "content"):
            value = content.get(key)
            if value is None:
                continue
            text = _extract_text(value)
            if text:
                return text
        return ""
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            text = _extract_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()

    text_attr = getattr(content, "text", None)
    if isinstance(text_attr, str):
        return text_attr
    return str(content) if content is not None else ""


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
                        for entry in item[:_LLM_MAX_MEDIA_ITEMS]
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
            for item in value[:_LLM_MAX_LIST_ITEMS]
        ]
        result: Dict[str, Any] = {"count": len(value)}
        if len(value) > _LLM_MAX_LIST_ITEMS:
            result["truncated"] = True
        result["items"] = compact_items
        return result

    if isinstance(value, str):
        return _compact_scalar(value, 320)
    return value


_ZIP_PREFIX_TO_STATE: Dict[str, str] = {
    **{str(p): "IL" for p in range(600, 630)},
    **{str(p): "MN" for p in range(550, 568)},
}

_STATE_NAMES: Dict[str, str] = {
    "illinois": "IL",
    "minnesota": "MN",
}

_STATE_ABBREVS = set(_STATE_NAMES.values())

_DEFAULT_STATE = "IL"


def _infer_state_and_zip(query: str) -> Tuple[str, str | None]:
    zip_match = re.search(r"\b\d{5}\b", query)

    # Check for full state names (case-insensitive)
    for name, code in _STATE_NAMES.items():
        if re.search(r"\b" + name + r"\b", query, re.IGNORECASE):
            return code, zip_match.group(0) if zip_match else None

    # Check for state abbreviations (case-sensitive to avoid false positives)
    for abbrev in _STATE_ABBREVS:
        if re.search(r"\b" + abbrev + r"\b", query):
            return abbrev, zip_match.group(0) if zip_match else None

    # Infer state from ZIP code prefix
    if zip_match:
        zip_prefix = zip_match.group(0)[:3]
        state = _ZIP_PREFIX_TO_STATE.get(zip_prefix, _DEFAULT_STATE)
        return state, zip_match.group(0)

    return _DEFAULT_STATE, None


def _compact_tool_result(value: Any) -> Any:
    compact = _summarize_for_model(value)
    text = json.dumps(compact, ensure_ascii=False)
    if len(text) <= _LLM_TOOL_PAYLOAD_CHARS:
        return compact
    return {
        "payload": _compact_scalar(text, _LLM_TOOL_PAYLOAD_CHARS),
        "truncated_length": len(text),
    }


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
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            if isinstance(value, (int, float)):
                return int(value)
            raw = str(value).replace(",", "").strip()
            if not raw:
                return default
            return int(float(raw))
        except (TypeError, ValueError):
            return default

    def _provider_snapshot(provider: Dict[str, Any], fallback_addr: str = "") -> Dict[str, Any]:
        return {
            "name": str(provider.get("name", "")).strip(),
            "address": str(provider.get("address", fallback_addr)).strip() or fallback_addr,
            "city": str(provider.get("city", "")).strip(),
            "zip": str(provider.get("zip", "")).strip(),
            "state": str(provider.get("state", "")).strip().upper(),
            "source": str(provider.get("source", "")).strip(),
            "license_type": str(provider.get("license_type", "")).strip(),
            "status": str(provider.get("status", "")).strip(),
            "capacity": _to_int(provider.get("capacity", 0), 0),
        }

    def _activeish_status(status: str) -> bool:
        s = str(status or "").strip().lower()
        if not s:
            return False
        if s in {"active", "il", "rn", "ip"}:
            return True
        return any(token in s for token in ("active", "license issued", "pending renewal", "permit issued"))

    def _is_group_home(license_type: str) -> bool:
        lt = str(license_type or "").strip().upper()
        return "GROUP DAY CARE HOME" in lt or lt in {"GDC", "GDCH"}

    def _is_day_care_home(license_type: str) -> bool:
        lt = str(license_type or "").strip().upper()
        if _is_group_home(lt):
            return False
        return (
            "DAY CARE HOME" in lt
            or "FAMILY DAY CARE" in lt
            or lt in {"DCH", "FDCH"}
        )

    # 1. Provider count: only from the FIRST search call (target area)
    provider_count = 0
    first_search_seen = False

    # 2. Build provider capacity from ALL search results (for flag matching)
    search_providers: Dict[str, List[Dict[str, Any]]] = {}  # normalized_addr -> providers
    dedup_provider_rows: set[tuple[str, str, str]] = set()
    all_search_rows: List[Dict[str, Any]] = []

    # 3. Property data: addr_arg -> sqft
    property_sqft: Dict[str, float] = {}

    # 4. Capacity calcs: sqft -> max_legal_capacity
    max_caps: Dict[float, int] = {}

    # 5. Licensing overrides: addr_arg -> capacity
    licensing_cap: Dict[str, Dict[str, Any]] = {}

    # 6. Track sequence: when property returns 0 sqft, link AI-estimated sqft
    #    from a subsequent calculate_max_capacity call to that address.
    _last_property_addr: str = ""
    _property_addrs_without_sqft: set = set()

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
                name = str(p.get("name", "")).strip()
                license_number = str(p.get("license_number", "")).strip()
                dedup_key = (name.upper(), norm, license_number.upper())
                if dedup_key in dedup_provider_rows:
                    continue
                dedup_provider_rows.add(dedup_key)
                provider_row = _provider_snapshot(p)
                all_search_rows.append(provider_row)
                if norm:
                    search_providers.setdefault(norm, []).append(provider_row)

        elif tool == "get_property_data" and isinstance(result, dict):
            addr = args.get("address", "")
            sqft = result.get("building_sqft", 0)
            _last_property_addr = addr
            if addr and sqft:
                property_sqft[addr] = float(sqft)
            elif addr:
                _property_addrs_without_sqft.add(addr)

        elif tool == "calculate_max_capacity" and isinstance(result, dict):
            sqft = args.get("building_sqft", 0)
            max_cap = result.get("max_legal_capacity", 0)
            if sqft and max_cap:
                max_caps[float(sqft)] = int(max_cap)
                # Link AI-estimated sqft to the most recent property address
                # that had no sqft from GIS (don't overwrite real GIS data).
                if (
                    _last_property_addr
                    and _last_property_addr in _property_addrs_without_sqft
                    and _last_property_addr not in property_sqft
                ):
                    property_sqft[_last_property_addr] = float(sqft)

        elif tool == "check_licensing_status" and isinstance(result, dict):
            if result.get("status") == "found":
                cap = _to_int(result.get("capacity", 0), 0)
                addr = args.get("address", "")
                name = args.get("provider_name", "")
                if cap and (addr or name):
                    licensing_cap[addr or name] = {"name": name, "capacity": cap}

    # Build flags: for each property with a capacity calc, check if licensed > max
    flagged: List[Dict[str, Any]] = []
    seen_flags: set[tuple[str, str, str]] = set()

    def _append_flag(
        *,
        flag_type: str,
        provider_name: str,
        address: str,
        flag_text: str,
        provider: Dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        key = (flag_type, _normalize_addr(address), provider_name.strip().upper())
        if key in seen_flags:
            return
        seen_flags.add(key)
        row: Dict[str, Any] = {
            "flag_type": flag_type,
            "provider_name": provider_name or "Unknown",
            "address": address or "Unknown address",
            "flag": flag_text,
        }
        if provider:
            row["provider"] = _provider_snapshot(provider, fallback_addr=address)
        row.update(extra)
        flagged.append(row)

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
        provider_row: Dict[str, Any] | None = None

        # Try licensing results (keyed by addr_arg or provider_name)
        if addr_arg in licensing_cap:
            licensed_cap = licensing_cap[addr_arg]["capacity"]
            provider_name = licensing_cap[addr_arg]["name"]

        # Fall back to search results (match by normalized address)
        if not licensed_cap:
            norm = _normalize_addr(addr_arg)
            if norm in search_providers:
                provider_row = search_providers[norm][0]
                licensed_cap = _to_int(provider_row.get("capacity", 0), 0)
                provider_name = str(provider_row.get("name", ""))

        if not provider_name:
            norm = _normalize_addr(addr_arg)
            if norm in search_providers:
                provider_row = search_providers[norm][0]
                provider_name = str(provider_row.get("name", ""))

        if licensed_cap > max_cap:
            _append_flag(
                flag_type="physical_capacity_overage",
                provider_name=provider_name or "Unknown",
                address=addr_arg,
                flag_text="licensed capacity exceeds physical maximum",
                provider=provider_row,
                licensed_capacity=licensed_cap,
                max_legal_capacity=max_cap,
                excess_capacity=licensed_cap - max_cap,
                building_sqft=sqft,
            )

    # Zero-capacity active/pending licenses.
    for provider in all_search_rows:
        status = str(provider.get("status", "")).strip()
        cap = _to_int(provider.get("capacity", 0), 0)
        if cap != 0 or not _activeish_status(status):
            continue
        _append_flag(
            flag_type="zero_capacity_active_license",
            provider_name=str(provider.get("name", "")) or "Unknown",
            address=str(provider.get("address", "")),
            flag_text="active/pending license has zero recorded capacity",
            provider=provider,
            licensed_capacity=0,
            note=f"status={status or 'unknown'}",
        )

    # License-type capacity mismatches for home-based license classes.
    for provider in all_search_rows:
        license_type = str(provider.get("license_type", ""))
        cap = _to_int(provider.get("capacity", 0), 0)
        if cap <= 0:
            continue
        if _is_group_home(license_type) and cap > 16:
            _append_flag(
                flag_type="license_type_capacity_mismatch",
                provider_name=str(provider.get("name", "")) or "Unknown",
                address=str(provider.get("address", "")),
                flag_text="group day care home capacity exceeds 16-child limit",
                provider=provider,
                licensed_capacity=cap,
                legal_limit=16,
                excess_capacity=cap - 16,
            )
        elif _is_day_care_home(license_type) and cap > 12:
            _append_flag(
                flag_type="license_type_capacity_mismatch",
                provider_name=str(provider.get("name", "")) or "Unknown",
                address=str(provider.get("address", "")),
                flag_text="day care home capacity exceeds 12-child limit",
                provider=provider,
                licensed_capacity=cap,
                legal_limit=12,
                excess_capacity=cap - 12,
            )

    # Permit-only records should be monitored as pre-operational, not active.
    for provider in all_search_rows:
        status = str(provider.get("status", "")).strip().lower()
        cap = _to_int(provider.get("capacity", 0), 0)
        if cap <= 0:
            continue
        if "permit issued" not in status and status not in {"ip"}:
            continue
        _append_flag(
            flag_type="permit_only_provider",
            provider_name=str(provider.get("name", "")) or "Unknown",
            address=str(provider.get("address", "")),
            flag_text="provider is permit-issued (pre-operational), verify not treated as fully licensed",
            provider=provider,
            licensed_capacity=cap,
        )

    # Multiple providers at the same address.
    for norm_addr, providers_at_addr in search_providers.items():
        unique_names = sorted({
            str(p.get("name", "")).strip()
            for p in providers_at_addr
            if str(p.get("name", "")).strip()
        })
        if len(unique_names) < 2:
            continue
        primary = providers_at_addr[0]
        total_capacity = sum(_to_int(p.get("capacity", 0), 0) for p in providers_at_addr)
        _append_flag(
            flag_type="shared_address_multiple_licenses",
            provider_name=f"Shared address ({len(unique_names)} providers)",
            address=str(primary.get("address", norm_addr)),
            flag_text="multiple providers share this address; verify independent operations",
            provider=primary,
            licensed_capacity=total_capacity,
            provider_count=len(unique_names),
            provider_names=unique_names,
        )

    return {"provider_count": provider_count, "flagged": flagged}


_REPORT_MARKERS = (
    "INVESTIGATION REPORT",
    "PROVIDER DOSSIERS",
    "EXPOSURE ESTIMATE",
    "PATTERN ANALYSIS",
    "CONFIDENCE CALIBRATION",
    "Investigation complete",
)

_REPORT_SECTION_MARKERS = (
    "INVESTIGATION NARRATIVE",
    "PROVIDER DOSSIERS",
    "PATTERN ANALYSIS",
    "CONFIDENCE CALIBRATION",
    "EXPOSURE ESTIMATE",
    "RECOMMENDATIONS",
)

_REPORT_HEADER_PATTERNS = (
    r"(?im)^#\s+SURELOCK HOMES(?:\s+—\s+|\s+)?(?:FINAL\s+)?INVESTIGATION REPORT\b",
    r"(?im)^#\s+SURELOCK HOMES\b",
    r"(?im)^##\s*1\.\s*INVESTIGATION NARRATIVE\b",
    r"(?im)^1\.\s*INVESTIGATION NARRATIVE\b",
)

_PROMPT_ECHO_LINE_PATTERNS = (
    r"(?i)^\s*do\s+not\s+use\s+introductory\s+text.*$",
    r"(?i)^\s*do\s+not\s+omit\s+any\s+sections.*$",
    r"(?i)^\s*write\s+the\s+final\s+report.*$",
    r"(?i)^\s*do\s+not\s+use\s+any\s+tools.*$",
    r"(?i)^\s*start\s+the\s+output\s+immediately.*$",
    r"(?i)^\s*begin\s+writing\s+the\s+report.*$",
)


def _report_already_written(assistant_text: List[str]) -> bool:
    """Return True if the assistant has already produced a final investigation report."""
    combined = " ".join(assistant_text)
    marker_hits = sum(1 for m in _REPORT_MARKERS if m in combined)
    return marker_hits >= 3


def _extract_inline_report(assistant_text: List[str]) -> str:
    """Extract the report section from assistant text when the LLM wrote it inline.

    Scans through the per-turn text blocks and returns everything from the first
    block that contains a report header marker onward.
    """
    # Report-start markers — the LLM typically begins with one of these
    _START_MARKERS = (
        "SURELOCK HOMES",
        "INVESTIGATION REPORT",
        "# Surelock Homes",
        "# INVESTIGATION REPORT",
        "## 1. INVESTIGATION NARRATIVE",
        "1. INVESTIGATION NARRATIVE",
    )
    report_blocks: List[str] = []
    collecting = False
    for block in assistant_text:
        if not collecting:
            upper = block.upper()
            if any(m.upper() in upper for m in _START_MARKERS):
                collecting = True
                report_blocks.append(block)
        else:
            report_blocks.append(block)
    return "\n".join(report_blocks)


def _normalize_report_output(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""

    # If the model echoed prompt directives before the report heading, trim to the first report heading.
    first_heading_at: int | None = None
    for pattern in _REPORT_HEADER_PATTERNS:
        match = re.search(pattern, body)
        if not match:
            continue
        pos = match.start()
        if first_heading_at is None or pos < first_heading_at:
            first_heading_at = pos
    if first_heading_at is not None and first_heading_at > 0:
        body = body[first_heading_at:].lstrip(' \t\n"\'')

    # Defensive cleanup for leading instruction echoes when no heading was found.
    lines = body.splitlines()
    while lines:
        first = lines[0].strip()
        if not first:
            lines.pop(0)
            continue
        if any(re.match(pattern, first) for pattern in _PROMPT_ECHO_LINE_PATTERNS):
            lines.pop(0)
            continue
        break
    return "\n".join(lines).strip()


def _looks_like_final_report(text: str) -> bool:
    body = _normalize_report_output(text)
    if not body:
        return False
    upper = body.upper()
    marker_hits = sum(1 for m in _REPORT_SECTION_MARKERS if m in upper)
    heading_hits = len(re.findall(r"(?im)^(#{1,3}\s+|[1-6]\.\s+)", body))
    if marker_hits >= 3:
        return True
    return marker_hits >= 2 and heading_hits >= 4


def _synthesize_report(
    *,
    query: str,
    raw_turns: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
) -> str:
    metrics = _extract_metrics(tool_calls)
    flagged = metrics.get("flagged", []) if isinstance(metrics, dict) else []
    provider_count = int(metrics.get("provider_count", 0) or 0) if isinstance(metrics, dict) else 0
    investigation_turns = len(raw_turns)

    exposure_monthly = 0
    for item in flagged:
        excess = int(item.get("excess_capacity", 0) or 0)
        if excess > 0:
            exposure_monthly += excess * 1100
    exposure_annual = exposure_monthly * 12

    lines: List[str] = [
        "# SURELOCK HOMES INVESTIGATION REPORT",
        "",
        "## 1. INVESTIGATION NARRATIVE",
        f"Query: {query}",
        f"Investigation turns completed: {investigation_turns}.",
        f"Providers identified in primary search: {provider_count}.",
        f"Flagged providers from tool evidence: {len(flagged)}.",
        "This report was synthesized from completed investigation outputs because the model did not return a complete final report block.",
        "",
        "## 2. PROVIDER DOSSIERS",
    ]

    if flagged:
        for idx, item in enumerate(flagged, start=1):
            provider = item.get("provider_name") or "Unknown provider"
            address = item.get("address") or "Unknown address"
            licensed = item.get("licensed_capacity")
            max_legal = item.get("max_legal_capacity")
            excess = item.get("excess_capacity")
            sqft = item.get("building_sqft")
            note = item.get("note")
            flag_text = item.get("flag") or "Potential anomaly."
            if licensed is not None:
                licensed = int(licensed or 0)
            if max_legal is not None:
                max_legal = int(max_legal or 0)
            if excess is not None:
                excess = int(excess or 0)
            lines.append(f"### {idx}. {provider}")
            lines.append(f"- Address: {address}")
            if sqft:
                lines.append(f"- Building sqft: {sqft}")
            if licensed is not None:
                lines.append(f"- Licensed capacity: {licensed}")
            if max_legal is not None:
                lines.append(f"- Maximum legal capacity (estimated): {max_legal}")
            if excess is not None:
                lines.append(f"- Excess capacity: {excess}")
            if note:
                lines.append(f"- Note: {note}")
            lines.append(f"- Preliminary finding: {flag_text}.")
            lines.append("")
    else:
        lines.append("No structured anomalies were detected from available tool outputs.")
        lines.append("")

    lines.extend(
        [
            "## 3. PATTERN ANALYSIS",
            "Cross-provider pattern analysis is limited when direct licensing/property confirmations are unavailable or incomplete.",
            "",
            "## 4. CONFIDENCE CALIBRATION",
            "HIGH confidence in direct numerical mismatches (licensed capacity vs computed maximum legal capacity).",
            "MEDIUM confidence in operational inferences from map/listing signals without direct regulator confirmation.",
            "",
            "## 5. EXPOSURE ESTIMATE",
            f"Estimated monthly exposure (if all excess slots are billed): ${exposure_monthly:,.0f}.",
            f"Estimated annual exposure: ${exposure_annual:,.0f}.",
            "This estimate is directional and depends on actual enrollment and billing records.",
            "",
            "## 6. RECOMMENDATIONS",
            "1. Verify flagged providers in official state licensing portals by address and license number.",
            "2. Run site verification for addresses with major capacity anomalies.",
            "3. Request regulator-side billing/attendance audits where exposure is material.",
        ]
    )
    return "\n".join(lines).strip()


def _ensure_report_text(
    *,
    mode: str,
    query: str,
    report_text: str,
    assistant_text: List[str],
    raw_turns: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
) -> str:
    text = _normalize_report_output(report_text or "")
    if mode != "agent":
        return text

    if _looks_like_final_report(text):
        return text

    inline = _normalize_report_output(_extract_inline_report(assistant_text))
    if _looks_like_final_report(inline):
        return inline

    turns_inline = _normalize_report_output(_extract_inline_report(
        [str(turn.get("assistant", "")).strip() for turn in raw_turns if str(turn.get("assistant", "")).strip()]
    ))
    if _looks_like_final_report(turns_inline):
        return turns_inline

    if text:
        logger.warning("Report text looked incomplete; using synthesized fallback report.")
    else:
        logger.warning("Report text missing; using synthesized fallback report.")
    return _synthesize_report(query=query, raw_turns=raw_turns, tool_calls=tool_calls)


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
    if nudge_count >= _LLM_MAX_CONTINUATIONS:
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
    # Only nudge if significant providers remain uninvestigated
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
        f"Continue investigating the remaining providers — pull property data "
        f"and calculate max capacity to check for physical impossibility. "
        f"Remember: the report will be generated automatically after your investigation "
        f"turns are complete, so use all remaining turns for investigation.{scope_reminder}"
    )


def _enforce_context_budget(messages: List[Dict[str, Any]], max_chars: int = _LLM_MAX_CONTEXT_CHARS) -> None:
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


def _to_openai_tools(tool_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _create_openai_client(settings: Any) -> "OpenAI":
    if OpenAI is None:
        raise RuntimeError(
            "The openai package is required for OpenRouter calls. "
            "Install it with: pip install openai"
        )
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
        },
    )


_MAX_STREET_VIEW_IMAGES = 4


def _build_image_message(sv_results: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Build a user message with street view images for visual analysis.

    Images are sent as image_url content blocks so vision-capable models
    can actually see them.  The message is injected temporarily into the
    API request and NOT stored in the permanent message history (base64
    images are far too large for the text context budget).
    """
    content_blocks: List[Dict[str, Any]] = []
    for sv in sv_results:
        address = sv.get("address", "unknown address")
        images = sv.get("images", [])
        if not images:
            continue
        content_blocks.append({
            "type": "text",
            "text": f"Street View images for {address} — analyze whether this looks like a childcare facility:",
        })
        for img in images[:_MAX_STREET_VIEW_IMAGES]:
            b64 = img.get("image_base64", "")
            status = img.get("status", "")
            if not b64 or status == "fallback":
                continue
            heading = img.get("heading", "?")
            capture_date = img.get("capture_date", "unknown")
            content_blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
            content_blocks.append({
                "type": "text",
                "text": f"(Heading {heading}°, captured {capture_date})",
            })
    if len(content_blocks) <= 1:
        return None
    return {"role": "user", "content": content_blocks}


_REPORT_GENERATION_PROMPT = (
    "Your investigation turns are now complete. Write the final investigation report NOW.\n\n"
    "IMPORTANT: Start writing the actual report immediately. Do NOT describe what the report "
    "should contain — just write it. Do NOT output meta-instructions or guidelines.\n\n"
    "Begin with:\n\n"
    "# SURELOCK HOMES INVESTIGATION REPORT\n\n"
    "Then write these sections using the data from your investigation:\n\n"
    "## 1. INVESTIGATION NARRATIVE\n"
    "The full story: what area was investigated, how many providers were found, "
    "what was examined, what stood out, what connections were discovered.\n\n"
    "## 2. PROVIDER DOSSIERS\n"
    "For each flagged provider: the facts (building sqft, capacity, zoning, visual assessment), "
    "the reasoning, innocent explanations, recommended next steps, confidence level.\n\n"
    "## 3. PATTERN ANALYSIS\n"
    "Cross-provider patterns: shared owners/agents, geographic clustering, temporal patterns.\n\n"
    "## 4. CONFIDENCE CALIBRATION\n"
    "What you're confident about vs uncertain about for each finding.\n\n"
    "## 5. EXPOSURE ESTIMATE\n"
    "For each flagged provider: excess_capacity x monthly_rate x 12. Aggregate total.\n\n"
    "## 6. RECOMMENDATIONS\n"
    "Prioritized next steps for human investigators.\n\n"
    "Include ALL findings from the investigation. Do NOT call any tools. Write the full report now."
)


def _generate_report_with_openai(
    *,
    client: Any,
    messages: List[Dict[str, Any]],
    model: str,
    max_tokens: int,
    emit_chunk: Callable[[str], None] | None = None,
) -> str:
    """Run the final report generation call (with continuation handling)."""
    _enforce_context_budget(messages)
    messages.append({"role": "user", "content": _REPORT_GENERATION_PROMPT})
    logger.info("Sending report generation request to %s (timeout=%ds)...", model, _LLM_REPORT_TIMEOUT_SECONDS)

    report_chunks: List[str] = []
    report_continuation_count = 0
    while True:
        report_response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=_LLM_REPORT_TIMEOUT_SECONDS,
        )
        report_choice = report_response.choices[0]
        raw_content = report_choice.message.content
        report_text = _normalize_report_output(_extract_text(raw_content))
        logger.info(
            "Report response: finish_reason=%s, content_type=%s, content_len=%d, extracted_len=%d",
            report_choice.finish_reason,
            type(raw_content).__name__,
            len(str(raw_content or "")),
            len(report_text),
        )
        if not report_text and raw_content:
            logger.warning("Report content extraction failed. Raw content: %s", repr(str(raw_content)[:500]))
        messages.append({"role": "assistant", "content": report_text or ""})
        if report_text:
            report_chunks.append(report_text)
            if emit_chunk:
                emit_chunk(report_text)

        if report_choice.finish_reason != "length":
            break

        report_continuation_count += 1
        if report_continuation_count > _LLM_MAX_CONTINUATIONS:
            logger.warning("LLM report text remained truncated after %s continuations", _LLM_MAX_CONTINUATIONS)
            break
        messages.append({"role": "user", "content": _LLM_CONTINUE_PROMPT})
        _enforce_context_budget(messages)

    if not report_chunks:
        logger.warning("Report generation returned empty response.")
        return ""
    return _normalize_report_output("\n\n".join(report_chunks))


def _append_final_report_to_state(
    *,
    report_text: str,
    narration: InvestigationNarration,
    assistant_text: List[str],
    raw_turns: List[Dict[str, Any]],
) -> str:
    """Persist final report text into narration/state structures exactly once."""
    cleaned = _normalize_report_output(report_text)
    if not cleaned:
        return ""
    narration.add_narration(cleaned)
    narration.add_assistant_text(cleaned)
    assistant_text.append(cleaned)
    raw_turns.append({"turn": len(raw_turns) + 1, "assistant": cleaned.strip(), "tool_results": []})
    return cleaned


def _build_result_payload(
    *,
    query: str,
    mode: str,
    status: str,
    narration: InvestigationNarration,
    assistant_text: List[str],
    report_text: str,
    tool_calls: List[Dict[str, Any]],
    thinking_blocks: List[str],
    raw_turns: List[Dict[str, Any]],
    fallback_text: str = "Investigation complete.",
    **extras: Any,
) -> Dict[str, Any]:
    """Assemble the standard investigation result payload."""
    final_report_text = _ensure_report_text(
        mode=mode,
        query=query,
        report_text=report_text,
        assistant_text=assistant_text,
        raw_turns=raw_turns,
        tool_calls=tool_calls,
    )
    metrics = _extract_metrics(tool_calls)
    thinking_analysis = build_thinking_analysis(
        query=query,
        report_text=final_report_text,
        narration_text=narration.to_markdown(),
        thinking=thinking_blocks,
        tool_calls=tool_calls,
    )
    payload: Dict[str, Any] = {
        "query": query,
        "mode": mode,
        "status": status,
        "turns": len(raw_turns),
        "provider_count": metrics["provider_count"],
        "flagged": metrics["flagged"],
        "narration": narration.to_markdown(),
        "assistant_text": "\n".join(assistant_text) or fallback_text,
        "report_text": final_report_text,
        "tool_calls": tool_calls,
        "thinking": thinking_blocks,
        "thinking_analysis": thinking_analysis,
        "raw_turns": raw_turns,
    }
    payload.update(extras)
    return payload


def _parse_tool_arguments(raw: Any) -> Dict[str, Any]:
    """Parse tool call arguments from string or dict form."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _call_tool(name: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    handler_map = {
        "search_childcare_providers": search_childcare_providers,
        "get_property_data": get_property_data,
        "get_street_view": get_street_view,
        "get_satellite_view": get_satellite_view,
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


def _run_openai_investigation(
    query: str,
    max_turns: int,
    model: str,
    settings: Any,
) -> Dict[str, Any]:
    client = _create_openai_client(settings)

    target_state, target_zip = _infer_state_and_zip(query)
    tool_defs = get_tool_definitions()
    openai_tools = _to_openai_tools(tool_defs)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": load_system_prompt(target_state=target_state, target_zip=target_zip, max_turns=max_turns)},
        {"role": "user", "content": query},
    ]
    tool_calls: List[Dict[str, Any]] = []
    raw_turns: List[Dict[str, Any]] = []
    thinking_blocks: List[str] = []
    narration = InvestigationNarration(query=query)
    assistant_text: List[str] = []
    _pending_sv_images: List[Dict[str, Any]] = []  # street view results to show next turn

    for turn in range(1, max_turns + 1):
        _enforce_context_budget(messages)

        # Build request messages — inject turn progress and pending images temporarily
        request_messages = list(messages)
        turns_remaining = max_turns - turn
        request_messages.append({
            "role": "user",
            "content": f"[TURN {turn}/{max_turns} — {turns_remaining} turns remaining after this one. "
            f"{'This is your LAST investigation turn.' if turns_remaining == 0 else ''}]",
        })
        if _pending_sv_images:
            img_msg = _build_image_message(_pending_sv_images)
            _pending_sv_images = []
            if img_msg:
                request_messages.append(img_msg)

        response = client.chat.completions.create(
            model=model,
            messages=request_messages,
            tools=openai_tools,
            tool_choice="auto",
            max_tokens=settings.max_tokens,
            timeout=settings.tool_timeout_seconds,
        )
        choice = response.choices[0]
        assistant_text_block = _extract_text(choice.message.content).strip()
        tool_calls_block = choice.message.tool_calls or []

        turn_summary = {"turn": turn, "assistant": "", "tool_results": []}
        turn_text_chunks: List[str] = []
        continuation_count = 0
        while True:
            if assistant_text_block:
                turn_text_chunks.append(assistant_text_block)

            assistant_history_entry: Dict[str, Any] = {"role": "assistant", "content": assistant_text_block or ""}
            if tool_calls_block:
                assistant_history_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls_block
                ]
            messages.append(assistant_history_entry)

            if tool_calls_block or choice.finish_reason != "length":
                break

            continuation_count += 1
            if continuation_count > _LLM_MAX_CONTINUATIONS:
                logger.warning("LLM assistant text remained truncated after %s continuations (turn %s)", _LLM_MAX_CONTINUATIONS, turn)
                break

            messages.append({"role": "user", "content": _LLM_CONTINUE_PROMPT})
            _enforce_context_budget(messages)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                max_tokens=settings.max_tokens,
                timeout=settings.tool_timeout_seconds,
            )
            choice = response.choices[0]
            assistant_text_block = _extract_text(choice.message.content).strip()
            tool_calls_block = choice.message.tool_calls or []

        combined_turn_text = "\n\n".join(chunk for chunk in turn_text_chunks if chunk).strip()
        if combined_turn_text:
            turn_summary["assistant"] = combined_turn_text
            narration.add_narration(combined_turn_text)
            narration.add_assistant_text(combined_turn_text)
            assistant_text.append(combined_turn_text)

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

        for tc in tool_calls_block:
            tool_name = tc.function.name
            arguments = _parse_tool_arguments(tc.function.arguments)
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
                    "tool_call_id": tc.id,
                    "name": tool_name,
                    "content": json.dumps(_compact_tool_result(result)),
                }
            )
            # Collect street view / satellite images for visual analysis in the next turn
            if tool_name == "get_street_view" and tool_status == "ok" and isinstance(result, dict):
                sv_images = result.get("images", [])
                if sv_images and any(img.get("status") != "fallback" for img in sv_images):
                    _pending_sv_images.append(result)
            if tool_name == "get_satellite_view" and tool_status == "ok" and isinstance(result, dict):
                b64 = result.get("image_base64", "")
                if b64 and result.get("status") != "fallback":
                    _pending_sv_images.append({
                        "address": result.get("address", ""),
                        "images": [{
                            "heading": "satellite",
                            "image_base64": b64,
                            "capture_date": "satellite",
                            "status": "ok",
                        }],
                    })

        raw_turns.append(turn_summary)

    # ── Report generation: one additional LLM call outside the turn budget ──
    logger.info("Investigation turns complete (%d turns). Starting report generation.", len(raw_turns))
    report_text_final = ""
    if _report_already_written(assistant_text):
        report_text_final = _normalize_report_output(_extract_inline_report(assistant_text))
        if report_text_final:
            logger.info("Report extracted from inline text (%d chars).", len(report_text_final))

    if not _looks_like_final_report(report_text_final):
        try:
            generated_report = _generate_report_with_openai(
                client=client,
                messages=messages,
                model=model,
                max_tokens=settings.max_tokens,
            )
            if generated_report:
                report_text_final = _append_final_report_to_state(
                    report_text=generated_report,
                    narration=narration,
                    assistant_text=assistant_text,
                    raw_turns=raw_turns,
                )
                logger.info("Report generated successfully (%d chars).", len(report_text_final))
        except Exception:
            logger.warning("Report generation call failed", exc_info=True)

    return _build_result_payload(
        query=query,
        mode="agent",
        status="complete",
        narration=narration,
        assistant_text=assistant_text,
        report_text=report_text_final,
        tool_calls=tool_calls,
        thinking_blocks=thinking_blocks,
        raw_turns=raw_turns,
    )


def _run_openai_investigation_stream(
    query: str,
    max_turns: int,
    model: str,
    settings: Any,
) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
    client = _create_openai_client(settings)

    target_state, target_zip = _infer_state_and_zip(query)
    yield {
        "event": "start",
        "query": query,
        "state": target_state,
        "zip": target_zip,
        "provider": "openrouter",
        "max_turns": max_turns,
    }

    tool_defs = get_tool_definitions()
    openai_tools = _to_openai_tools(tool_defs)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": load_system_prompt(target_state=target_state, target_zip=target_zip, max_turns=max_turns)},
        {"role": "user", "content": query},
    ]
    tool_calls: List[Dict[str, Any]] = []
    raw_turns: List[Dict[str, Any]] = []
    thinking_blocks: List[str] = []
    narration = InvestigationNarration(query=query)
    assistant_text: List[str] = []
    _pending_sv_images: List[Dict[str, Any]] = []

    try:
        for turn in range(1, max_turns + 1):
            _enforce_context_budget(messages)
            yield {"event": "turn_start", "turn": turn, "max_turns": max_turns}

            # Build request messages — inject turn progress and pending images temporarily
            request_messages = list(messages)
            turns_remaining = max_turns - turn
            request_messages.append({
                "role": "user",
                "content": f"[TURN {turn}/{max_turns} — {turns_remaining} turns remaining after this one. "
                f"{'This is your LAST investigation turn.' if turns_remaining == 0 else ''}]",
            })
            if _pending_sv_images:
                img_msg = _build_image_message(_pending_sv_images)
                _pending_sv_images = []
                if img_msg:
                    request_messages.append(img_msg)

            response = client.chat.completions.create(
                model=model,
                messages=request_messages,
                tools=openai_tools,
                tool_choice="auto",
                max_tokens=settings.max_tokens,
                timeout=settings.tool_timeout_seconds,
            )
            choice = response.choices[0]
            assistant_text_block = _extract_text(choice.message.content).strip()
            tool_calls_block = choice.message.tool_calls or []

            turn_summary = {"turn": turn, "assistant": "", "tool_results": []}
            turn_text_chunks: List[str] = []
            continuation_count = 0
            while True:
                if assistant_text_block:
                    turn_text_chunks.append(assistant_text_block)
                    yield {
                        "event": "assistant_text",
                        "turn": turn,
                        "text": assistant_text_block,
                    }

                assistant_history_entry: Dict[str, Any] = {"role": "assistant", "content": assistant_text_block or ""}
                if tool_calls_block:
                    assistant_history_entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in tool_calls_block
                    ]
                messages.append(assistant_history_entry)

                if tool_calls_block or choice.finish_reason != "length":
                    break

                continuation_count += 1
                if continuation_count > _LLM_MAX_CONTINUATIONS:
                    logger.warning("LLM assistant text remained truncated after %s continuations (turn %s)", _LLM_MAX_CONTINUATIONS, turn)
                    break

                messages.append({"role": "user", "content": _LLM_CONTINUE_PROMPT})
                _enforce_context_budget(messages)
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    max_tokens=settings.max_tokens,
                    timeout=settings.tool_timeout_seconds,
                )
                choice = response.choices[0]
                assistant_text_block = _extract_text(choice.message.content).strip()
                tool_calls_block = choice.message.tool_calls or []

            combined_turn_text = "\n\n".join(chunk for chunk in turn_text_chunks if chunk).strip()
            if combined_turn_text:
                turn_summary["assistant"] = combined_turn_text
                narration.add_narration(combined_turn_text)
                narration.add_assistant_text(combined_turn_text)
                assistant_text.append(combined_turn_text)

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

            for tc in tool_calls_block:
                tool_name = tc.function.name
                arguments = _parse_tool_arguments(tc.function.arguments)
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
                        "tool_call_id": tc.id,
                        "name": tool_name,
                        "content": json.dumps(_compact_tool_result(result)),
                    }
                )
                # Collect street view / satellite images for visual analysis in the next turn
                if tool_name == "get_street_view" and tool_status == "ok" and isinstance(result, dict):
                    sv_images = result.get("images", [])
                    if sv_images and any(img.get("status") != "fallback" for img in sv_images):
                        _pending_sv_images.append(result)
                if tool_name == "get_satellite_view" and tool_status == "ok" and isinstance(result, dict):
                    b64 = result.get("image_base64", "")
                    if b64 and result.get("status") != "fallback":
                        _pending_sv_images.append({
                            "address": result.get("address", ""),
                            "images": [{
                                "heading": "satellite",
                                "image_base64": b64,
                                "capture_date": "satellite",
                                "status": "ok",
                            }],
                        })

                yield {
                    "event": "tool_payload",
                    "turn": turn,
                    "tool": tool_name,
                    "status": tool_status,
                    "result": _coerce_tool_payload(result),
                }

            raw_turns.append(turn_summary)
            yield {"event": "turn_done", "turn": turn, "tools": [item["tool"] for item in turn_summary["tool_results"]]}

        # ── Report generation: one additional LLM call outside the turn budget ──
        logger.info("Investigation turns complete (%d turns). Starting report generation.", len(raw_turns))
        report_text_final = ""
        if _report_already_written(assistant_text):
            report_text_final = _normalize_report_output(_extract_inline_report(assistant_text))
            if report_text_final:
                logger.info("Report extracted from inline text (%d chars).", len(report_text_final))

        if not _looks_like_final_report(report_text_final):
            yield {"event": "report_start"}
            try:
                generated_report = _generate_report_with_openai(
                    client=client,
                    messages=messages,
                    model=model,
                    max_tokens=settings.max_tokens,
                )
                if generated_report:
                    report_text_final = _append_final_report_to_state(
                        report_text=generated_report,
                        narration=narration,
                        assistant_text=assistant_text,
                        raw_turns=raw_turns,
                    )
                    yield {"event": "assistant_text", "turn": len(raw_turns), "text": report_text_final}
                    logger.info("Report generated successfully (%d chars).", len(report_text_final))
            except Exception:
                logger.warning("Report generation call failed", exc_info=True)

        result_payload = _build_result_payload(
            query=query,
            mode="agent",
            status="complete",
            narration=narration,
            assistant_text=assistant_text,
            report_text=report_text_final,
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
            raw_turns=raw_turns,
        )
        yield {"event": "complete", "payload": result_payload}
        return result_payload

    except Exception as exc:
        logger.warning("Streaming OpenAI investigation failed for query %s: %s", query, exc, exc_info=True)
        yield {
            "event": "error",
            "error": _sanitize_error(exc),
            "query": query,
        }
        result_payload = _build_result_payload(
            query=query,
            mode="agent",
            status="error",
            narration=narration,
            assistant_text=assistant_text,
            report_text="",
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
            raw_turns=raw_turns,
            fallback_text="Investigation failed.",
            error=_sanitize_error(exc),
        )
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
            "report_text": "No providers found in fallback dataset.",
            "tool_calls": [],
            "thinking": [],
            "thinking_analysis": build_thinking_analysis(
                query=query,
                report_text="No providers found in fallback dataset.",
                narration_text=narration.to_markdown(),
                thinking=[],
                tool_calls=[],
            ),
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
    report_text = summary
    thinking = ["Offline deterministic reasoning mode used for stable results."]
    thinking_analysis = build_thinking_analysis(
        query=query,
        report_text=report_text,
        narration_text=narration.to_markdown(),
        thinking=thinking,
        tool_calls=tool_calls,
    )
    return {
        "query": query,
        "mode": "offline",
        "status": "complete",
        "provider_count": len(providers),
        "flagged": flagged,
        "turns": min(len(providers), max_turns),
        "narration": narration.to_markdown(),
        "assistant_text": summary,
        "report_text": report_text,
        "tool_calls": tool_calls,
        "thinking": thinking,
        "thinking_analysis": thinking_analysis,
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
                "report_text": "No providers found in fallback dataset.",
                "tool_calls": [],
                "thinking": [],
                "thinking_analysis": build_thinking_analysis(
                    query=query,
                    report_text="No providers found in fallback dataset.",
                    narration_text=narration.to_markdown(),
                    thinking=[],
                    tool_calls=[],
                ),
                "raw_turns": [
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

    report_text = summary
    thinking = ["Offline deterministic reasoning mode used for stable results."]
    thinking_analysis = build_thinking_analysis(
        query=query,
        report_text=report_text,
        narration_text=narration.to_markdown(),
        thinking=thinking,
        tool_calls=tool_calls,
    )

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
            "report_text": report_text,
            "tool_calls": tool_calls,
            "thinking": thinking,
            "thinking_analysis": thinking_analysis,
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
        result = _run_openai_investigation(
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

        # ── Report generation: one additional LLM call outside the turn budget ──
        report_text_final = ""
        if _report_already_written(assistant_text):
            # LLM wrote the report inline during investigation — extract it
            report_text_final = _extract_inline_report(assistant_text)
        else:
            messages.append({"role": "user", "content": _REPORT_GENERATION_PROMPT})
            try:
                report_response = client.messages.create(
                    model=model or settings.model,
                    max_tokens=settings.max_tokens,
                    thinking={"type": "enabled", "budget_tokens": settings.thinking_budget_tokens},
                    system=load_system_prompt(target_state=target_state_anthropic, target_zip=target_zip_anthropic, max_turns=max_turns),
                    messages=messages,
                )
                report_parts = []
                for block in _normalize_blocks(report_response.content):
                    if block.get("type") == "text":
                        report_text = block.get("text", "")
                        if report_text:
                            report_parts.append(report_text)
                            narration.add_narration(report_text)
                            narration.add_assistant_text(report_text)
                            assistant_text.append(report_text)
                            raw_turns.append({"turn": len(raw_turns) + 1, "assistant": report_text.strip(), "tool_results": []})
                report_text_final = "\n".join(report_parts)
            except Exception:
                logger.warning("Anthropic report generation call failed", exc_info=True)

        result = _build_result_payload(
            query=query,
            mode="agent",
            status="complete",
            narration=narration,
            assistant_text=assistant_text,
            report_text=report_text_final,
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
            raw_turns=raw_turns,
        )
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
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _inner():
        if offline:
            yield from _offline_investigation_stream(query, max_turns=max_turns)
            return

        if settings.llm_provider == "openrouter":
            if not settings.openrouter_api_key:
                raise RuntimeError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter.")
            yield from _run_openai_investigation_stream(
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

    for event in _inner():
        yield event
        if event.get("event") == "complete" and "payload" in event:
            _persist_investigation(run_id, event["payload"], output_dir=OUTPUT_DIR)


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
