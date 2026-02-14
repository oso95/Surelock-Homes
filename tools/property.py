from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR


def _normalize_addr(address: str) -> str:
    return (address or "").lower().replace(".", "").replace(",", "").strip()


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def get_property_data(
    address: str,
    county: str | None = None,
    state: str | None = None,
) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required"}

    state_key = (state or "").upper()
    normalized_target = _normalize_addr(address)

    source_paths = []
    if state_key == "MN":
        source_paths.append(DATA_DIR / "hennepin_parcels.csv")
    elif state_key == "IL":
        source_paths.append(DATA_DIR / "cook_parcels.csv")
    else:
        source_paths.append(DATA_DIR / "hennepin_parcels.csv")
        source_paths.append(DATA_DIR / "cook_parcels.csv")

    if county:
        source_paths = [p for p in source_paths if county.lower() in p.name.lower()] or source_paths

    for path in source_paths:
        for row in _read_csv(path):
            if _normalize_addr(row.get("address", "")) == normalized_target:
                return {
                    "status": "found",
                    "source": path.name,
                    "address": row.get("address", ""),
                    "building_sqft": float(row.get("building_sqft", 0) or 0),
                    "lot_size": row.get("lot_size", ""),
                    "zoning": row.get("zoning", ""),
                    "property_class": row.get("property_class", ""),
                    "year_built": int(float(row.get("year_built", 0) or 0)),
                    "county": row.get("county", ""),
                    "state": row.get("state", state_key),
                }

    return {
        "status": "not_found",
        "source": "fallback",
        "address": address,
        "building_sqft": 0.0,
        "lot_size": "",
        "zoning": "",
        "property_class": "",
        "year_built": 0,
        "county": county or "",
        "state": state_key or "",
        "error": "no parcel match in local datasets",
    }

