from __future__ import annotations

import csv
import logging
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
_GIS_TIMEOUT_SECONDS = 8.0


ADDRESS_RE = re.compile(r"^(?P<number>\d+)\s+(?P<rest>.+)$")
SUFFIXES = {
    "ST": "ST",
    "STREET": "ST",
    "ST.": "ST",
    "AVE": "AVE",
    "AVENUE": "AVE",
    "AVE.": "AVE",
    "RD": "RD",
    "ROAD": "RD",
    "RD.": "RD",
    "BLVD": "BLVD",
    "BOULEVARD": "BLVD",
    "BLVD.": "BLVD",
    "CT": "CT",
    "COURT": "CT",
    "CT.": "CT",
    "LN": "LN",
    "LANE": "LN",
    "LN.": "LN",
    "PL": "PL",
    "PLACE": "PL",
    "PL.": "PL",
    "DR": "DR",
    "DRIVE": "DR",
    "DR.": "DR",
    "TER": "TER",
    "TERRACE": "TER",
    "TER.": "TER",
    "PKWY": "PKWY",
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

logger = logging.getLogger(__name__)


def _extract_zip(address: str) -> str:
    if not address:
        return ""
    match = re.search(r"\b(\d{5})\b", address)
    return match.group(1) if match else ""


def _address_matches(address_target: str, address_row: str) -> bool:
    parsed_target = _parse_address(address_target)
    parsed_row = _parse_address(address_row)

    if not parsed_target or not parsed_row:
        return _normalize_addr(address_target) == _normalize_addr(address_row)

    if parsed_target.get("house") != parsed_row.get("house"):
        return False

    if parsed_target.get("street") != parsed_row.get("street"):
        return False

    if (
        parsed_target.get("suffix")
        and parsed_row.get("suffix")
        and parsed_target["suffix"] != parsed_row["suffix"]
    ):
        return False

    if (
        parsed_target.get("direction")
        and parsed_row.get("direction")
        and parsed_target["direction"] != parsed_row["direction"]
    ):
        return False

    target_zip = _extract_zip(address_target)
    row_zip = _extract_zip(address_row)
    if target_zip and row_zip and target_zip != row_zip:
        return False

    return True


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
    if not address:
        return {}

    # Prefer the street-level portion before the first comma so \"123 Main St, City\"
    # still parses as the actual street address.
    text = (address or "").replace(".", "").split(",")[0].strip().upper()
    text = re.sub(r"\s+", " ", text).strip()
    match = ADDRESS_RE.match(text)
    if not match:
        return {}

    number = match.group("number")
    rest = re.sub(r"\s+", " ", match.group("rest")).strip()
    tokens = rest.split()
    if not tokens:
        return {"house": number}

    # Remove trailing ZIP/state artifacts when callers pass a full address.
    if tokens and re.fullmatch(r"\d{5}", tokens[-1]):
        tokens = tokens[:-1]
    if tokens and tokens[-1] in {"IL", "IL.", "MN", "MN.", "WI", "WI.", "CA", "CA.", "NY", "NY."}:
        tokens = tokens[:-1]

    if not tokens:
        return {"house": number}

    direction = ""
    if tokens[0] in DIRECTIONS:
        direction = DIRECTIONS[tokens[0]]
        tokens = tokens[1:]
    if not tokens:
        return {"house": number}

    suffix = ""
    suffix_index: int | None = None
    for idx, token in enumerate(tokens):
        if token in SUFFIXES:
            suffix_index = idx
            suffix = SUFFIXES[token]
            break
    if suffix_index is not None:
        street_tokens = tokens[:suffix_index]
    else:
        street_tokens = tokens

    street = " ".join(street_tokens)
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

    response = requests.get(HENNEPIN_API_URL, params=params, timeout=_GIS_TIMEOUT_SECONDS)
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

    response = requests.get(COOK_API_URL, params=params, timeout=_GIS_TIMEOUT_SECONDS)
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

    if not offline and state_key == "MN":
        live_status = None
        live_error: str | None = None
        try:
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
        except Exception as exc:
            live_status = "failed"
            live_error = str(exc)
            logger.warning("Live Hennepin query failed for %s: %s", address, exc, exc_info=True)
        if live_status:
            return _fallback_property_result(
                address=address,
                state_key=state_key,
                county=county,
                live_error=live_error,
            )
    elif not offline and state_key == "IL":
        live_status = None
        live_error: str | None = None
        try:
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
        except Exception as exc:
            live_status = "failed"
            live_error = str(exc)
            logger.warning("Live Cook query failed for %s: %s", address, exc, exc_info=True)
        if live_status:
            return _fallback_property_result(
                address=address,
                state_key=state_key,
                county=county,
                live_error=live_error,
            )

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
            if _address_matches(address, row.get("address", "")):
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


def _fallback_property_result(
    *,
    address: str,
    state_key: str,
    county: str | None = None,
    live_error: str | None = None,
) -> Dict[str, Any]:
    fallback_paths = []
    if state_key == "MN":
        fallback_paths.append(DATA_DIR / "hennepin_parcels.csv")
    elif state_key == "IL":
        fallback_paths.append(DATA_DIR / "cook_parcels.csv")
    else:
        fallback_paths.append(DATA_DIR / "hennepin_parcels.csv")
        fallback_paths.append(DATA_DIR / "cook_parcels.csv")

    for path in fallback_paths:
        if not path.exists():
            continue
        for row in _read_csv(path):
            if _address_matches(address, row.get("address", "")):
                return {
                    "status": "found",
                    "source": f"{path.name}.fallback",
                    "address": row.get("address", ""),
                    "building_sqft": float(row.get("building_sqft", 0) or 0),
                    "lot_size": row.get("lot_size", ""),
                    "zoning": row.get("zoning", ""),
                    "property_class": row.get("property_class", ""),
                    "year_built": int(float(row.get("year_built", 0) or 0)),
                    "county": row.get("county", county or row.get("county", "")),
                    "state": row.get("state", state_key),
                    "live_error": live_error,
                    "live_fallback": True,
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
        "live_error": live_error,
    }
