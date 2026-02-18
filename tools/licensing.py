from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict

from config import DATA_DIR
from tools.providers import _load_il_live_records, _load_stale_cache, _query_parentaware_by_name

logger = logging.getLogger(__name__)


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_addr(addr: str) -> str:
    """Normalize address for matching: strip city/state/zip, standardize abbreviations."""
    a = str(addr).upper().strip()
    a = a.split(",")[0].strip()
    for full, abbr in [
        ("STREET", "ST"), ("AVENUE", "AVE"), ("ROAD", "RD"), ("DRIVE", "DR"),
        ("BOULEVARD", "BLVD"), ("PLACE", "PL"), ("COURT", "CT"), ("LANE", "LN"),
        ("WEST", "W"), ("EAST", "E"), ("NORTH", "N"), ("SOUTH", "S"),
    ]:
        a = re.sub(r"\b" + full + r"\b", abbr, a)
    return re.sub(r"\s+", " ", a).strip()


def _addr_matches(addr_a: str | None, addr_b: str | None) -> bool:
    """Check if two addresses refer to the same location despite format differences."""
    if not addr_a or not addr_b:
        return True  # No address to compare — don't filter out
    return _normalize_addr(addr_a) == _normalize_addr(addr_b)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _find_live_il_matches(name: str, address: str | None) -> list[Dict[str, Any]]:
    needle = _normalize(name)
    matches: list[Dict[str, Any]] = []
    try:
        records = _load_il_live_records()
    except Exception:
        logger.warning("Live IL fetch failed for licensing lookup, trying stale cache", exc_info=True)
        records = _load_stale_cache("IL")
    if not records:
        return []

    for row in records:
        provider = _normalize(row.get("name"))
        if needle not in provider:
            continue
        if address and not _addr_matches(address, row.get("address")):
            continue
        matches.append(
            {
                "status": "found",
                "provider_name": row.get("name", ""),
                "state": "IL",
                "license_type": row.get("license_type", ""),
                "license_status": row.get("status", ""),
                "issue_date": "",
                "expiration_date": "",
                "capacity": _safe_int(row.get("capacity")),
                "violation_history": "",
                "inspection_notes": "Live DCFS provider lookup",
            }
        )
    return matches


def _pa_address_line1(pa: Dict[str, Any]) -> str:
    """Extract the street address (line1) from a ParentAware address dict."""
    addr = pa.get("address")
    if isinstance(addr, dict):
        return (addr.get("line1") or "").strip()
    if isinstance(addr, str):
        return addr.strip()
    return ""


def _find_live_mn_matches(name: str, address: str | None) -> list[Dict[str, Any]]:
    """Search ParentAware API for MN provider licensing info."""
    needle = _normalize(name)
    matches: list[Dict[str, Any]] = []
    try:
        results = _query_parentaware_by_name(name)
    except Exception:
        logger.warning("ParentAware lookup failed for MN licensing", exc_info=True)
        return []

    for pa in results:
        pa_name = _normalize(pa.get("name", ""))
        if needle not in pa_name and pa_name not in needle:
            continue
        if address:
            pa_addr = _pa_address_line1(pa)
            if pa_addr and not _addr_matches(address, pa_addr):
                continue
        matches.append(
            {
                "status": "found",
                "provider_name": pa.get("name", ""),
                "state": "MN",
                "license_type": pa.get("licenseType", ""),
                "license_status": pa.get("licenseStatus", ""),
                "issue_date": "",
                "expiration_date": "",
                "capacity": _safe_int(pa.get("licensedCapacity")),
                "age_range": pa.get("ageRange", ""),
                "accepts_ccap": pa.get("acceptsCCAP"),
                "violation_history": "",
                "inspection_notes": "ParentAware live lookup",
            }
        )
    return matches


def check_licensing_status(
    provider_name: str,
    state: str,
    address: str | None = None,
) -> Dict[str, Any]:
    if not provider_name:
        return {"status": "error", "error": "provider_name is required"}

    state_key = (state or "").upper()
    path = DATA_DIR / ("mn_licensing.csv" if state_key == "MN" else "il_licensing.csv")
    target = _normalize(provider_name)

    for row in _read_csv(path):
        provider_row = _normalize(row.get("provider_name"))
        if target in provider_row:
            if address and not _addr_matches(address, row.get("address")):
                continue
            return {
                "status": "found",
                "provider_name": row.get("provider_name", ""),
                "state": row.get("state", state_key),
                "license_type": row.get("license_type", ""),
                "license_status": row.get("license_status", ""),
                "issue_date": row.get("issue_date", ""),
                "expiration_date": row.get("expiration_date", ""),
                "capacity": int(float(row.get("capacity", 0) or 0)),
                "violation_history": row.get("violation_history", ""),
                "inspection_notes": row.get("inspection_notes", ""),
            }

    if state_key == "MN":
        matches = _find_live_mn_matches(provider_name, address)
        if matches:
            if len(matches) == 1:
                return matches[0]
            return {
                "status": "found",
                "provider_name": provider_name,
                "state": "MN",
                "license_type": matches[0].get("license_type", ""),
                "license_status": matches[0].get("license_status", ""),
                "issue_date": matches[0].get("issue_date", ""),
                "expiration_date": matches[0].get("expiration_date", ""),
                "capacity": matches[0].get("capacity", 0),
                "age_range": matches[0].get("age_range", ""),
                "accepts_ccap": matches[0].get("accepts_ccap"),
                "violation_history": "",
                "inspection_notes": "Multiple ParentAware records found; returning first match",
                "results": matches,
            }

    if state_key == "IL":
        matches = _find_live_il_matches(provider_name, address)
        if matches:
            if len(matches) == 1:
                return matches[0]
            return {
                "status": "found",
                "provider_name": provider_name,
                "state": "IL",
                "license_type": matches[0].get("license_type", ""),
                "license_status": matches[0].get("license_status", ""),
                "issue_date": matches[0].get("issue_date", ""),
                "expiration_date": matches[0].get("expiration_date", ""),
                "capacity": matches[0].get("capacity", 0),
                "violation_history": "",
                "inspection_notes": "Multiple live records found; returning first match",
                "results": matches,
            }

    return {
        "status": "not_found",
        "provider_name": provider_name,
        "state": state_key,
        "error": "No matching licensing record in local dataset.",
    }
