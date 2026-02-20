from __future__ import annotations

import csv
import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from config import DATA_DIR


HENNEPIN_API_URL = (
    "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1/query"
)
# Cook County Assessor Socrata Open Data endpoints (replaces dead ArcGIS)
COOK_ADDR_URL = "https://datacatalog.cookcountyil.gov/resource/3723-97qp.json"
COOK_RES_URL = "https://datacatalog.cookcountyil.gov/resource/x54s-btds.json"
COOK_ASSESSED_URL = "https://datacatalog.cookcountyil.gov/resource/uzyt-m557.json"
COOK_COMMERCIAL_URL = "https://datacatalog.cookcountyil.gov/resource/csik-bsws.json"

from config import load_settings as _load_settings

_GIS_TIMEOUT_SECONDS = 8.0
_SOCRATA_TIMEOUT_SECONDS = 10.0


def _gis_timeout() -> float:
    try:
        return float(_load_settings().gis_timeout_seconds)
    except Exception:
        return _GIS_TIMEOUT_SECONDS


def _socrata_timeout() -> float:
    try:
        return float(_load_settings().socrata_timeout_seconds)
    except Exception:
        return _SOCRATA_TIMEOUT_SECONDS


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


@dataclass
class PropertyCountyConfig:
    live_query: Callable[[str], Dict[str, Any]]
    fallback_csv: Path
    default_county: str
    source_label: str


# Registry populated after state-specific query functions are defined (see bottom of module)
PROPERTY_REGISTRY: Dict[str, PropertyCountyConfig] = {}


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
        # Check for trailing direction after suffix (e.g., "Cedar Ave S")
        trailing = tokens[suffix_index + 1:]
        if trailing and trailing[0] in DIRECTIONS and not direction:
            direction = DIRECTIONS[trailing[0]]
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


_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_TIMEOUT = 6.0
_OSM_SEARCH_RADIUS_M = 50
_OSM_RATE_LIMIT_DELAY = 0.5
_last_osm_call: float = 0.0


def _shoelace_area_sqft(coords: List[List[float]]) -> float:
    """Compute polygon area in sq ft from lat/lon coordinates using the shoelace formula.

    Uses a local Mercator approximation to convert degrees to meters, then to sq ft.
    coords: list of [lon, lat] pairs (GeoJSON order).
    """
    if len(coords) < 3:
        return 0.0
    # Reference point: centroid
    ref_lat = sum(c[1] for c in coords) / len(coords)
    lat_rad = math.radians(ref_lat)
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_132.0 * math.cos(lat_rad)

    # Convert to meters relative to first point
    xs = [(c[0] - coords[0][0]) * m_per_deg_lon for c in coords]
    ys = [(c[1] - coords[0][1]) * m_per_deg_lat for c in coords]

    # Shoelace formula
    n = len(xs)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += xs[i] * ys[j]
        area -= xs[j] * ys[i]
    area_m2 = abs(area) / 2.0
    return area_m2 * 10.7639  # m² → sq ft


def _estimate_sqft_from_osm(lat: float, lon: float) -> Dict[str, Any]:
    """Query Overpass API for building polygons near (lat, lon) and return estimated sqft.

    Returns dict with keys: building_sqft, building_sqft_source, building_sqft_confidence.
    """
    global _last_osm_call
    result = {
        "building_sqft": 0.0,
        "building_sqft_source": "none",
        "building_sqft_confidence": "none",
    }
    if not lat or not lon:
        return result

    # Rate-limit OSM calls
    elapsed = time.time() - _last_osm_call
    if elapsed < _OSM_RATE_LIMIT_DELAY:
        time.sleep(_OSM_RATE_LIMIT_DELAY - elapsed)

    query = (
        f'[out:json][timeout:{int(_OVERPASS_TIMEOUT)}];'
        f'way["building"](around:{_OSM_SEARCH_RADIUS_M},{lat},{lon});'
        f'out body;>;out skel qt;'
    )
    try:
        _last_osm_call = time.time()
        resp = requests.post(
            _OVERPASS_URL,
            data={"data": query},
            timeout=_OVERPASS_TIMEOUT + 2,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.debug("OSM Overpass query failed for (%s, %s)", lat, lon, exc_info=True)
        return result

    elements = data.get("elements", [])
    if not elements:
        return result

    # Collect node coordinates
    nodes: Dict[int, List[float]] = {}
    ways: List[Dict[str, Any]] = []
    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = [el["lon"], el["lat"]]
        elif el["type"] == "way":
            ways.append(el)

    # Compute footprint area for each building way, pick the largest
    best_area = 0.0
    for way in ways:
        node_ids = way.get("nodes", [])
        coords = [nodes[nid] for nid in node_ids if nid in nodes]
        if len(coords) < 3:
            continue
        area = _shoelace_area_sqft(coords)
        if area > best_area:
            best_area = area

    if best_area > 0:
        result["building_sqft"] = round(best_area, 1)
        result["building_sqft_source"] = "osm_footprint"
        result["building_sqft_confidence"] = "moderate"

    return result


def _query_hennepin(address: str) -> Dict[str, Any]:
    parsed = _parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return {}

    house = _sanitize_arcgis_value(parsed["house"])
    street = _sanitize_arcgis_value(parsed["street"])
    where = [f"HOUSE_NO={house}", f"upper(STREET_NM) LIKE '{street}%'"]
    if parsed.get("suffix"):
        suffix = _sanitize_arcgis_value(parsed["suffix"])
        where.append(f"upper(STREET_NM) LIKE '% {suffix}%'")

    params = {
        "where": " AND ".join(where),
        "outFields": "HOUSE_NO,STREET_NM,ZIP_CD,PARCEL_AREA,BUILD_YR,PR_TYP_NM1,BLDG_MV1,MKT_VAL_TOT,NET_IMPRV_AMT,OWNER_NM,LAT,LON",
        "f": "json",
        "outSR": "4326",
        "returnGeometry": "false",
    }

    response = requests.get(HENNEPIN_API_URL, params=params, timeout=_gis_timeout())
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
        lat = _to_float(attrs.get("LAT"))
        lon = _to_float(attrs.get("LON"))

        # Try to estimate building sqft from OSM footprint data
        osm = _estimate_sqft_from_osm(lat, lon)
        building_sqft = osm["building_sqft"]
        building_sqft_source = osm["building_sqft_source"]
        building_sqft_confidence = osm["building_sqft_confidence"]
        note = ""
        if not building_sqft:
            note = "Building sqft not available from Hennepin GIS or OSM; use building_market_value for size estimates"

        return {
            "address": attrs.get("STREET_NM", ""),
            "building_sqft": building_sqft,
            "building_sqft_source": building_sqft_source,
            "building_sqft_confidence": building_sqft_confidence,
            "lot_size": str(int(parcel_area)) if parcel_area else "",
            "zoning": attrs.get("PR_TYP_NM1", ""),
            "property_class": attrs.get("PR_TYP_NM1", ""),
            "year_built": _to_int(attrs.get("BUILD_YR"), 0),
            "building_market_value": _to_int(attrs.get("BLDG_MV1"), 0),
            "total_market_value": _to_int(attrs.get("MKT_VAL_TOT"), 0),
            "owner_name": attrs.get("OWNER_NM", ""),
            "latitude": lat,
            "longitude": lon,
            "note": note,
        }
    return {}


def _socrata_address_to_pin(address: str) -> Optional[str]:
    """Look up a Cook County parcel PIN from a street address via Socrata."""
    parsed = _parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return None

    # Build the address prefix for exact match: "1512 S PULASKI RD"
    parts = [parsed["house"]]
    if parsed.get("direction"):
        parts.append(parsed["direction"])
    parts.append(parsed["street"])
    if parsed.get("suffix"):
        parts.append(parsed["suffix"])
    addr_prefix = " ".join(parts)

    # Try exact match first, then starts_with for partial matches
    for query_pattern in [
        f"prop_address_full='{addr_prefix}'",
        f"starts_with(prop_address_full, '{addr_prefix}')",
    ]:
        params = {
            "$where": query_pattern,
            "$select": "pin",
            "$order": "year DESC",
            "$limit": "1",
        }
        resp = requests.get(COOK_ADDR_URL, params=params, timeout=_socrata_timeout())
        resp.raise_for_status()
        rows = resp.json()
        if rows:
            return rows[0].get("pin")
    return None


def _socrata_residential(pin: str) -> Dict[str, Any]:
    """Get building characteristics from the residential dataset."""
    params = {
        "pin": pin,
        "$select": "char_bldg_sf,char_land_sf,char_yrblt,class,char_type_resd",
        "$order": "year DESC",
        "$limit": "1",
    }
    resp = requests.get(COOK_RES_URL, params=params, timeout=_socrata_timeout())
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    row = rows[0]
    return {
        "building_sqft": _to_float(row.get("char_bldg_sf"), 0.0),
        "lot_size": str(int(_to_float(row.get("char_land_sf"), 0.0))) or "",
        "property_class": row.get("class", ""),
        "year_built": _to_int(row.get("char_yrblt"), 0),
        "property_type": row.get("char_type_resd", ""),
    }


def _socrata_commercial(pin: str) -> Dict[str, Any]:
    """Get building data from the commercial valuation dataset."""
    # Commercial dataset uses dashed PIN format: 16-23-325-002-0000
    dashed = f"{pin[:2]}-{pin[2:4]}-{pin[4:7]}-{pin[7:10]}-{pin[10:]}"
    params = {
        "keypin": dashed,
        "$select": "bldgsf,landsf,yearbuilt,property_type_use",
        "$order": "year DESC",
        "$limit": "1",
    }
    resp = requests.get(COOK_COMMERCIAL_URL, params=params, timeout=_socrata_timeout())
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    row = rows[0]
    return {
        "building_sqft": _to_float(row.get("bldgsf"), 0.0),
        "lot_size": str(int(_to_float(row.get("landsf"), 0.0))) or "",
        "property_class": row.get("property_type_use", ""),
        "year_built": _to_int(row.get("yearbuilt"), 0),
    }


def _socrata_assessed(pin: str) -> Dict[str, Any]:
    """Get assessed values and property class from the assessment dataset."""
    params = {
        "pin": pin,
        "$select": "class,mailed_bldg,mailed_land,mailed_tot,township_name",
        "$order": "year DESC",
        "$limit": "1",
    }
    resp = requests.get(COOK_ASSESSED_URL, params=params, timeout=_socrata_timeout())
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    row = rows[0]
    return {
        "property_class": row.get("class", ""),
        "assessed_building": _to_float(row.get("mailed_bldg"), 0.0),
        "assessed_land": _to_float(row.get("mailed_land"), 0.0),
        "assessed_total": _to_float(row.get("mailed_tot"), 0.0),
        "township": row.get("township_name", ""),
    }


def _query_cook(address: str) -> Dict[str, Any]:
    """Cook County property lookup via Socrata Open Data API.

    Three-tier approach:
    1. Resolve address → PIN via address dataset
    2. Look up residential building characteristics (sqft, year built)
    3. If not residential, try commercial dataset
    4. Fall back to assessed values for class info
    """
    pin = _socrata_address_to_pin(address)
    if not pin:
        return {}

    # Tier 1: Residential characteristics (most detailed)
    res = _socrata_residential(pin)
    if res and res.get("building_sqft", 0) > 0:
        return {
            "address": address,
            "building_sqft": res["building_sqft"],
            "lot_size": res.get("lot_size", ""),
            "zoning": "",
            "property_class": res.get("property_class", ""),
            "year_built": res.get("year_built", 0),
            "pin": pin,
            "source_dataset": "residential_characteristics",
        }

    # Tier 2: Commercial valuation data
    comm = _socrata_commercial(pin)
    if comm and comm.get("building_sqft", 0) > 0:
        return {
            "address": address,
            "building_sqft": comm["building_sqft"],
            "lot_size": comm.get("lot_size", ""),
            "zoning": "",
            "property_class": comm.get("property_class", ""),
            "year_built": comm.get("year_built", 0),
            "pin": pin,
            "source_dataset": "commercial_valuation",
        }

    # Tier 3: Assessed values (class info but no sqft)
    assessed = _socrata_assessed(pin)
    return {
        "address": address,
        "building_sqft": 0.0,
        "lot_size": "",
        "zoning": "",
        "property_class": assessed.get("property_class", ""),
        "year_built": 0,
        "pin": pin,
        "assessed_total": assessed.get("assessed_total", 0.0),
        "source_dataset": "assessed_values",
        "note": "No building characteristics available (property may be tax-exempt)",
    }


def get_property_data(
    address: str,
    county: str | None = None,
    state: str | None = None,
    offline: bool = False,
) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required"}

    state_key = (state or "").upper()
    config = PROPERTY_REGISTRY.get(state_key)

    if not offline and config is not None:
        try:
            live = config.live_query(address)
            if live:
                result = {
                    "status": "found",
                    "source": config.source_label,
                    "address": live.get("address", address),
                    "building_sqft": live.get("building_sqft", 0.0),
                    "lot_size": live.get("lot_size", ""),
                    "zoning": live.get("zoning", ""),
                    "property_class": live.get("property_class", ""),
                    "year_built": live.get("year_built", 0),
                    "county": county or config.default_county,
                    "state": state_key,
                }
                for extra in ("building_market_value", "total_market_value", "owner_name",
                              "latitude", "longitude", "note", "pin", "source_dataset", "assessed_total",
                              "building_sqft_source", "building_sqft_confidence"):
                    if live.get(extra):
                        result[extra] = live[extra]
                return result
            # Important: in online mode, a clean live "no match" should not
            # silently fall through to fixture CSVs.
            return {
                "status": "not_found",
                "source": config.source_label,
                "address": address,
                "building_sqft": 0.0,
                "lot_size": "",
                "zoning": "",
                "property_class": "",
                "year_built": 0,
                "county": county or config.default_county,
                "state": state_key,
                "error": "no parcel match in live county dataset",
                "live_not_found": True,
            }
        except Exception as exc:
            logger.warning("Live %s query failed for %s: %s", config.default_county, address, exc, exc_info=True)
            return _fallback_property_result(
                address=address,
                state_key=state_key,
                county=county,
                live_error=str(exc),
            )

    # Fallback to CSV datasets
    if config is not None:
        source_paths = [config.fallback_csv]
    else:
        source_paths = [c.fallback_csv for c in PROPERTY_REGISTRY.values()]

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
    config = PROPERTY_REGISTRY.get(state_key)
    if config is not None:
        fallback_paths = [config.fallback_csv]
    else:
        fallback_paths = [c.fallback_csv for c in PROPERTY_REGISTRY.values()]

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


# Populate the registry now that all query functions are defined
PROPERTY_REGISTRY.update({
    "MN": PropertyCountyConfig(
        live_query=_query_hennepin,
        fallback_csv=DATA_DIR / "hennepin_parcels.csv",
        default_county="Hennepin",
        source_label="live_hennepin",
    ),
    "IL": PropertyCountyConfig(
        live_query=_query_cook,
        fallback_csv=DATA_DIR / "cook_parcels.csv",
        default_county="Cook",
        source_label="live_cook",
    ),
})
