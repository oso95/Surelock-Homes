from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Optional

from config import DATA_DIR


def _read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check_licensing_status(provider_name: str, state: str, address: str | None = None) -> Dict[str, Any]:
    if not provider_name:
        return {"status": "error", "error": "provider_name is required"}
    state_key = (state or "").upper()
    path = DATA_DIR / ("mn_licensing.csv" if state_key == "MN" else "il_licensing.csv")
    target = provider_name.lower()
    address_norm = (address or "").lower()
    for row in _read_csv(path):
        if target in row.get("provider_name", "").lower():
            if address and address_norm and address_norm not in row.get("address", "").lower():
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
    return {
        "status": "not_found",
        "provider_name": provider_name,
        "state": state_key,
        "error": "No matching licensing record in local dataset.",
    }

