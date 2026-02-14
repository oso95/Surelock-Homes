from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR


def _normalize(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _filter(records: List[Dict[str, str]], *, city: Optional[str], state: str, zip_code: Optional[str]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in records:
        if row.get("state", "").upper() != state.upper():
            continue
        if zip_code and _normalize(row.get("zip")) != str(zip_code):
            continue
        if city and _normalize(row.get("city")) != _normalize(city):
            continue
        normalized = {
            "name": row.get("name", "").strip(),
            "address": row.get("address", "").strip(),
            "city": row.get("city", "").strip(),
            "zip": row.get("zip", "").strip(),
            "capacity": int(float(row.get("capacity", 0) or 0)),
            "license_type": row.get("license_type", "").strip(),
            "status": row.get("status", "").strip(),
            "state": row.get("state", "").strip().upper(),
        }
        result.append(normalized)
    return result


def search_childcare_providers(
    city: str | None = None,
    state: str = "MN",
    zip: str | None = None,
    radius_miles: float = 5,
) -> List[Dict[str, Any]]:
    _ = radius_miles  # reserved for future geospatial filtering
    state_key = (state or "").upper()
    if state_key == "MN":
        records = _read_csv(DATA_DIR / "mn_providers.csv")
    elif state_key == "IL":
        records = _read_csv(DATA_DIR / "il_providers.csv")
    else:
        return []
    return _filter(records, city=city, state=state_key, zip_code=zip)

