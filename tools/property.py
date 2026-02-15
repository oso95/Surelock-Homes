from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from config import DATA_DIR


HENNEPIN_API_URL = (
    "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1/query"
)
COOK_API_URL = (
    "https://gis.cookcountyil.gov/traditional/rest/services/cookVwrDynmc/MapServer/44/query"
)


ADDRESS_RE = re.compile(r"^(?P<number>\d+)\s+(?P<rest>.+)$")
SUFFIXES = {
    "STREET": "ST",
    "ST.": "ST",
    "AVENUE": "AVE",
    "AVE.": "AVE",
    "ROAD": "RD",
    "RD.": "RD",
    "BOULEVARD": "BLVD",
    "BLVD.": "BLVD",
    "COURT": "CT",
    "CT.": "CT",
    "LANE": "LN",
    "LN.": "LN",
    "PLACE": "PL",
    "PL.": "PL",
    "DRIVE": "DR",
    "DR.": "DR",
    "TERRACE": "TER",
    "TER.": "TER",
    "PARKWAY": "PKWY",
    "PKWY.": "PKWY",
}
DIRECTIONS = {
    "N": "N",
    "NORTH": "N",
    "S": "S",
    "SOUTH": "S",
    "E": "E",
    "EAST": "E",
    "W": "W",
    "WEST": "W",
}


def _normalize_addr(address: str) -> str:
    return (address or "").lower().replace(".", "").replace(",", "").strip()


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _parse_address(address: str) -> Dict[str, str]:
    text = _normalize_addr(address).upper().strip()
    match = ADDRESS_RE.match(text)
    if not match:
        return {}

    number = match.group("number")
    rest = match.group("rest").replace("  ", " ").strip()
    tokens = rest.split()
    if not tokens:
        return {"house": number}

    direction = ""
    if tokens[0] in DIRECTIONS:
        direction = DIRECTIONS[tokens[0]]
        tokens = tokens[1:]
    if not tokens:
        return {"house": number}

    suffix = ""
    if tokens[-1] in SUFFIXES:
        suffix = SUFFIXES[tokens[-1]]
        tokens = tokens[:-1]

    street = " ".join(tokens)
    return {"house": number, "direction": direction, "street": street, "suffix": suffix}


def _sanitize_arcgis_value(value: str) -> str:
    sanitized = value.replace("'", "''")
    sanitized = re.sub(r"[^A-Za-z0-9 \-.]", "", sanitized)
    return sanitized


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _query_hennepin(address: str) -> Dict[str, Any]:
    parsed = _parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return {}

    house = _sanitize_arcgis_value(parsed["house"])
    street = _sanitize_arcgis_value(parsed["street"])
    where = [f"HOUSE_NO={house}", f"upper(STREET_NM) LIKE '{street}%'"]
    if parsed.get("suffix"):
        suffix = _sanitize_arcgis_value(parsed["suffix"])
        where.append(f"upper(STREET_NM) LIKE '% {suffix}'")

    params = {
        "where": " AND ".join(where),
        "outFields": "HOUSE_NO,STREET_NM,ZIP_CD,PARCEL_AREA,BUILD_YR,PR_TYP_NM1",
        "f": "json",
        "outSR": "4326",
        "returnGeometry": "false",
    }

    response = requests.get(HENNEPIN_API_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        return {}

    for feature in features:
        attrs = feature.get("attributes", {})
        parcel_area = _to_float(attrs.get("PARCEL_AREA"), 0.0)
        if str(attrs.get("HOUSE_NO", "")).strip() != parsed["house"]:
            continue
        street_norm = str(attrs.get("STREET_NM", "")).replace(" ", "").replace(".", "").upper()
        if parsed["street"].replace(" ", "") not in street_norm:
            continue
        return {
            "address": attrs.get("STREET_NM", ""),
            "building_sqft": 0.0,
            "lot_size": str(int(parcel_area)) if parcel_area else "",
            "zoning": attrs.get("PR_TYP_NM1", ""),
            "property_class": attrs.get("PR_TYP_NM1", ""),
            "year_built": _to_int(attrs.get("BUILD_YR"), 0),
        }
    return {}


def _query_cook(address: str) -> Dict[str, Any]:
    parsed = _parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return {}

    house = _sanitize_arcgis_value(parsed["house"])
    street = _sanitize_arcgis_value(parsed["street"])
    where = [f"HouseNo='{house}'", f"upper(Street) LIKE '{street}%'"]
    if parsed.get("suffix"):
        suffix = _sanitize_arcgis_value(parsed["suffix"])
        where.append(f"upper(Suffix)='{suffix}'")
    if parsed.get("direction"):
        direction = _sanitize_arcgis_value(parsed["direction"])
        where.append(f"upper(Dir)='{direction}'")

    params = {
        "where": " AND ".join(where),
        "outFields": "Address,BLDGClass,LandSqft,BldgSqft,BldgAge,City,Zip_Code",
        "f": "json",
        "returnGeometry": "false",
    }

    response = requests.get(COOK_API_URL, params=params, timeout=30)
    response.raise_for_status()
    features = response.json().get("features") or []
    if not features:
        return {}

    for feature in features:
        attrs = feature.get("attributes", {})
        building = _to_float(attrs.get("BldgSqft"), 0.0)
        lot = _to_float(attrs.get("LandSqft"), 0.0)
        return {
            "address": attrs.get("Address", ""),
            "building_sqft": building,
            "lot_size": str(int(lot)) if lot else "",
            "zoning": "",
            "property_class": attrs.get("BLDGClass", ""),
            "year_built": _to_int(attrs.get("BldgAge"), 0),
        }

    return {}


def get_property_data(
    address: str,
    county: str | None = None,
    state: str | None = None,
    offline: bool = False,
) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required"}

    state_key = (state or "").upper()
    normalized_target = _normalize_addr(address)

    if not offline and state_key == "MN":
        live = _query_hennepin(address)
        if live:
            return {
                "status": "found",
                "source": "live_hennepin",
                "address": live.get("address", address),
                "building_sqft": live.get("building_sqft", 0.0),
                "lot_size": live.get("lot_size", ""),
                "zoning": live.get("zoning", ""),
                "property_class": live.get("property_class", ""),
                "year_built": live.get("year_built", 0),
                "county": county or "Hennepin",
                "state": "MN",
            }
    elif not offline and state_key == "IL":
        live = _query_cook(address)
        if live:
            return {
                "status": "found",
                "source": "live_cook",
                "address": live.get("address", address),
                "building_sqft": live.get("building_sqft", 0.0),
                "lot_size": live.get("lot_size", ""),
                "zoning": live.get("zoning", ""),
                "property_class": live.get("property_class", ""),
                "year_built": live.get("year_built", 0),
                "county": county or "Cook",
                "state": "IL",
            }

    source_paths = []
    if state_key == "MN":
        source_paths.append(DATA_DIR / "hennepin_parcels.csv")
    elif state_key == "IL":
        source_paths.append(DATA_DIR / "cook_parcels.csv")
    else:
        source_paths.append(DATA_DIR / "hennepin_parcels.csv")
        source_paths.append(DATA_DIR / "cook_parcels.csv")

    for path in source_paths:
        if not path.exists():
            continue
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
        "state": state_key,
        "error": "no parcel match in local datasets",
    }
