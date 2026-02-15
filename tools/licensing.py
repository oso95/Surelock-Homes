from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict

from config import DATA_DIR
from tools.providers import _load_il_live_records

logger = logging.getLogger(__name__)


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()


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
    address_norm = _normalize(address)
    matches: list[Dict[str, Any]] = []
    try:
        records = _load_il_live_records()
    except Exception:
        logger.warning("Failed to load IL live records for licensing lookup", exc_info=True)
        return []

    for row in records:
        provider = _normalize(row.get("name"))
        if needle not in provider:
            continue
        if address_norm and address_norm not in _normalize(row.get("address")):
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
    address_norm = _normalize(address)

    for row in _read_csv(path):
        if target in _normalize(row.get("provider_name")).lower():
            if address and address_norm and address_norm not in _normalize(row.get("address")):
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
