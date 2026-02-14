from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from config import DATA_DIR


def _read_rows() -> List[Dict[str, str]]:
    path = DATA_DIR / "business_registration.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check_business_registration(
    name: str,
    state: str,
    search_type: str = "business",
) -> List[Dict[str, Any]] | Dict[str, Any]:
    if not name:
        return {"status": "error", "error": "name is required"}

    rows = _read_rows()
    needle = name.lower()
    state_key = (state or "").upper()
    matches = []

    for row in rows:
        if row.get("state", "").upper() != state_key:
            continue
        target_field = "business_name" if search_type == "business" else "registered_agent"
        candidate = row.get(target_field, "").lower()
        if needle in candidate:
            matches.append(
                {
                    "status": "found",
                    "business_name": row.get("business_name", ""),
                    "state": row.get("state", state_key),
                    "registered_agent": row.get("registered_agent", ""),
                    "entity_type": row.get("entity_type", ""),
                    "registration_status": row.get("registration_status", ""),
                    "incorporation_date": row.get("incorporation_date", ""),
                    "registered_address": row.get("registered_address", ""),
                }
            )

    if not matches:
        return {
            "status": "not_found",
            "query": name,
            "state": state_key,
            "search_type": search_type,
            "results": [],
        }

    return matches if search_type == "agent" else {"status": "found", "results": matches}

