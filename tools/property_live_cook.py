"""Cook County live property lookup (Socrata datasets)."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import requests

from tools.property_helpers import parse_address, to_float, to_int


def socrata_address_to_pin(
    address: str,
    *,
    addr_url: str,
    timeout_seconds: float,
    http_get: Callable[..., Any] = requests.get,
) -> Optional[str]:
    """Look up a Cook County parcel PIN from a street address."""
    parsed = parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return None

    parts = [parsed["house"]]
    if parsed.get("direction"):
        parts.append(parsed["direction"])
    parts.append(parsed["street"])
    if parsed.get("suffix"):
        parts.append(parsed["suffix"])
    addr_prefix = " ".join(parts)

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
        resp = http_get(addr_url, params=params, timeout=timeout_seconds)
        resp.raise_for_status()
        rows = resp.json()
        if rows:
            return rows[0].get("pin")
    return None


def socrata_residential(
    pin: str,
    *,
    residential_url: str,
    timeout_seconds: float,
    http_get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    """Get building characteristics from the residential dataset."""
    params = {
        "pin": pin,
        "$select": "char_bldg_sf,char_land_sf,char_yrblt,class,char_type_resd",
        "$order": "year DESC",
        "$limit": "1",
    }
    resp = http_get(residential_url, params=params, timeout=timeout_seconds)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    row = rows[0]
    return {
        "building_sqft": to_float(row.get("char_bldg_sf"), 0.0),
        "lot_size": str(int(to_float(row.get("char_land_sf"), 0.0))) or "",
        "property_class": row.get("class", ""),
        "year_built": to_int(row.get("char_yrblt"), 0),
        "property_type": row.get("char_type_resd", ""),
    }


def socrata_commercial(
    pin: str,
    *,
    commercial_url: str,
    timeout_seconds: float,
    http_get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    """Get building characteristics from the commercial valuation dataset."""
    dashed = f"{pin[:2]}-{pin[2:4]}-{pin[4:7]}-{pin[7:10]}-{pin[10:]}"
    params = {
        "keypin": dashed,
        "$select": "bldgsf,landsf,yearbuilt,property_type_use",
        "$order": "year DESC",
        "$limit": "1",
    }
    resp = http_get(commercial_url, params=params, timeout=timeout_seconds)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    row = rows[0]
    return {
        "building_sqft": to_float(row.get("bldgsf"), 0.0),
        "lot_size": str(int(to_float(row.get("landsf"), 0.0))) or "",
        "property_class": row.get("property_type_use", ""),
        "year_built": to_int(row.get("yearbuilt"), 0),
    }


def socrata_assessed(
    pin: str,
    *,
    assessed_url: str,
    timeout_seconds: float,
    http_get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    """Get assessed values and property class from the assessment dataset."""
    params = {
        "pin": pin,
        "$select": "class,mailed_bldg,mailed_land,mailed_tot,township_name",
        "$order": "year DESC",
        "$limit": "1",
    }
    resp = http_get(assessed_url, params=params, timeout=timeout_seconds)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {}
    row = rows[0]
    return {
        "property_class": row.get("class", ""),
        "assessed_building": to_float(row.get("mailed_bldg"), 0.0),
        "assessed_land": to_float(row.get("mailed_land"), 0.0),
        "assessed_total": to_float(row.get("mailed_tot"), 0.0),
        "township": row.get("township_name", ""),
    }


def query_cook(
    address: str,
    *,
    address_to_pin: Callable[[str], Optional[str]],
    residential_lookup: Callable[[str], Dict[str, Any]],
    commercial_lookup: Callable[[str], Dict[str, Any]],
    assessed_lookup: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    """Cook County three-tier lookup: residential -> commercial -> assessed."""
    pin = address_to_pin(address)
    if not pin:
        return {}

    res = residential_lookup(pin)
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

    comm = commercial_lookup(pin)
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

    assessed = assessed_lookup(pin)
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
