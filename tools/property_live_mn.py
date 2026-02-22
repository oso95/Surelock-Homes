"""Minnesota live property lookup clients (MN Open Parcels + Hennepin GIS)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List

import requests

from tools.property_helpers import (
    escape_where_literal,
    extract_city,
    extract_zip,
    normalize_street_name,
    normalize_suffix,
    parse_address,
    sanitize_arcgis_value,
    street_variants,
    to_float,
    to_int,
)

_DIRECTION_WORDS = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
}


def mn_where_clause(
    *,
    parsed: Dict[str, str],
    county: str | None,
    city: str,
    zip_code: str,
    include_house: bool,
    strict_street: bool,
) -> str:
    clauses: List[str] = []

    if county:
        clauses.append(f"co_name='{escape_where_literal(county)}'")

    if include_house and parsed.get("house"):
        clauses.append(f"anumber={to_int(parsed['house'], 0)}")

    street_preds: List[str] = []
    for street in street_variants(parsed.get("street", "")):
        escaped = escape_where_literal(street)
        if not escaped:
            continue
        if strict_street:
            street_preds.append(f"UPPER(st_name) LIKE '{escaped}%'")
        else:
            street_preds.append(f"UPPER(st_name) LIKE '%{escaped}%'")
    if street_preds:
        clauses.append("(" + " OR ".join(street_preds) + ")")

    if zip_code:
        clauses.append(f"zip='{escape_where_literal(zip_code)}'")
    if city:
        clauses.append(f"UPPER(postcomm)='{escape_where_literal(city)}'")

    return " AND ".join(clauses) if clauses else "1=1"


def query_mn_open_parcels_layer(
    where: str,
    *,
    api_url: str,
    timeout_seconds: float,
    limit: int = 50,
    http_get: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    params = {
        "where": where,
        "outFields": (
            "objectid,county_pin,anumber,st_pre_dir,st_name,st_pos_typ,st_pos_dir,"
            "postcomm,zip,co_name,fin_sq_ft,acres_poly,year_built,useclass1,"
            "owner_name,emv_bldg,emv_total"
        ),
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": str(limit),
        "f": "json",
    }
    response = http_get(api_url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    return payload.get("features") or []


def geometry_centroid_lonlat(geometry: Dict[str, Any]) -> tuple[float, float]:
    rings = (geometry or {}).get("rings") or []
    if not rings:
        return 0.0, 0.0
    points = [pt for ring in rings for pt in ring if isinstance(pt, list) and len(pt) >= 2]
    if not points:
        return 0.0, 0.0
    lon = sum(float(pt[0]) for pt in points) / len(points)
    lat = sum(float(pt[1]) for pt in points) / len(points)
    return lat, lon


def build_display_address(attrs: Dict[str, Any], fallback: str) -> str:
    number = str(attrs.get("anumber") or "").strip()
    pre_dir_raw = str(attrs.get("st_pre_dir") or "").strip()
    pre_dir = _DIRECTION_WORDS.get(pre_dir_raw.upper(), pre_dir_raw.upper())
    street = str(attrs.get("st_name") or "").strip()
    suffix = str(attrs.get("st_pos_typ") or "").strip()
    post_dir_raw = str(attrs.get("st_pos_dir") or "").strip()
    post_dir = _DIRECTION_WORDS.get(post_dir_raw.upper(), post_dir_raw.upper())

    parts = [number, pre_dir, street, suffix, post_dir]
    line1 = " ".join(part for part in parts if part).strip()
    city = str(attrs.get("postcomm") or "").strip()
    zip_code = str(attrs.get("zip") or "").strip()
    county = str(attrs.get("co_name") or "").strip()

    if line1 and city and zip_code:
        return f"{line1}, {city}, MN {zip_code}"
    if line1 and city:
        return f"{line1}, {city}, MN"
    if line1:
        return line1
    if county:
        return f"{fallback} ({county} County)"
    return fallback


def score_mn_candidate(
    attrs: Dict[str, Any],
    *,
    parsed: Dict[str, str],
    county: str | None,
    city: str,
    zip_code: str,
) -> float:
    score = 0.0

    target_county = str(county or "").strip().upper()
    attr_county = str(attrs.get("co_name") or "").strip().upper()
    if target_county:
        if attr_county == target_county:
            score += 10.0
        else:
            score -= 10.0

    target_zip = zip_code.strip()
    attr_zip = str(attrs.get("zip") or "").strip()[:5]
    if target_zip:
        if attr_zip == target_zip:
            score += 6.0
        else:
            score -= 2.0

    target_city = city.strip().upper()
    attr_city = str(attrs.get("postcomm") or "").strip().upper()
    if target_city:
        if attr_city == target_city:
            score += 5.0
        elif attr_city and target_city in attr_city:
            score += 2.0

    target_house = to_int(parsed.get("house"), -1)
    attr_house = to_int(attrs.get("anumber"), -1)
    if target_house >= 0 and attr_house >= 0:
        if attr_house == target_house:
            score += 10.0
        else:
            diff = abs(attr_house - target_house)
            if diff <= 2:
                score += 4.0
            elif diff <= 10:
                score += 1.0
            else:
                score -= 3.0

    target_street = normalize_street_name(parsed.get("street", ""))
    attr_street = normalize_street_name(str(attrs.get("st_name") or ""))
    if target_street and attr_street:
        if attr_street == target_street:
            score += 9.0
        elif attr_street.startswith(target_street) or target_street.startswith(attr_street):
            score += 6.0
        elif target_street in attr_street or attr_street in target_street:
            score += 3.0
        else:
            score -= 4.0

    target_suffix = normalize_suffix(parsed.get("suffix", ""))
    attr_suffix = normalize_suffix(str(attrs.get("st_pos_typ") or ""))
    if target_suffix and attr_suffix:
        if target_suffix == attr_suffix:
            score += 2.0
        else:
            score -= 0.5

    target_dir = str(parsed.get("direction") or "").upper().strip()
    attr_dir = str(attrs.get("st_pre_dir") or attrs.get("st_pos_dir") or "").upper().strip()
    attr_dir = _DIRECTION_WORDS.get(attr_dir, attr_dir)
    if target_dir and attr_dir:
        if target_dir == attr_dir:
            score += 1.5
        else:
            score -= 0.5

    return score


def select_best_mn_open_parcel(
    features: List[Dict[str, Any]],
    *,
    parsed: Dict[str, str],
    county: str | None,
    city: str,
    zip_code: str,
) -> Dict[str, Any]:
    if not features:
        return {}

    scored: List[tuple[float, float, Dict[str, Any]]] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        score = score_mn_candidate(
            attrs,
            parsed=parsed,
            county=county,
            city=city,
            zip_code=zip_code,
        )
        sqft = to_float(attrs.get("fin_sq_ft"), 0.0)
        scored.append((score, sqft, feature))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, _best_sqft, best_feature = scored[0]
    if best_score < 8.0:
        return {}
    return best_feature


def query_mn_open_parcels(
    address: str,
    county: str | None = None,
    *,
    query_layer: Callable[[str, int], List[Dict[str, Any]]],
    estimate_sqft_from_osm: Callable[[float, float], Dict[str, Any]],
) -> Dict[str, Any]:
    """Query MnGeo Open Parcels for normalized parcel attributes."""
    parsed = parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return {}

    county_name = (county or "").strip()
    city = extract_city(address)
    zip_code = extract_zip(address)

    feature: Dict[str, Any] = {}
    attempts = [
        mn_where_clause(
            parsed=parsed,
            county=county_name or None,
            city=city,
            zip_code=zip_code,
            include_house=True,
            strict_street=True,
        ),
        mn_where_clause(
            parsed=parsed,
            county=county_name or None,
            city=city,
            zip_code=zip_code,
            include_house=False,
            strict_street=True,
        ),
        mn_where_clause(
            parsed=parsed,
            county=county_name or None,
            city=city,
            zip_code=zip_code,
            include_house=False,
            strict_street=False,
        ),
        mn_where_clause(
            parsed=parsed,
            county=county_name or None,
            city="",
            zip_code=zip_code,
            include_house=True,
            strict_street=False,
        ),
        mn_where_clause(
            parsed=parsed,
            county=county_name or None,
            city="",
            zip_code="",
            include_house=True,
            strict_street=False,
        ),
        mn_where_clause(
            parsed=parsed,
            county=county_name or None,
            city="",
            zip_code="",
            include_house=False,
            strict_street=False,
        ),
    ]

    for where in attempts:
        features = query_layer(where, 60)
        feature = select_best_mn_open_parcel(
            features,
            parsed=parsed,
            county=county_name or None,
            city=city,
            zip_code=zip_code,
        )
        if feature:
            break

    if not feature:
        return {}

    attrs = feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}

    building_sqft = to_float(attrs.get("fin_sq_ft"), 0.0)
    lot_acres = to_float(attrs.get("acres_poly"), 0.0)
    lot_sqft = lot_acres * 43560.0 if lot_acres else 0.0
    lat, lon = geometry_centroid_lonlat(geometry)

    result: Dict[str, Any] = {
        "address": build_display_address(attrs, address),
        "building_sqft": building_sqft,
        "building_sqft_source": "county_assessor" if building_sqft else "none",
        "building_sqft_confidence": "high" if building_sqft else "none",
        "lot_size": str(int(round(lot_sqft))) if lot_sqft else "",
        "zoning": str(attrs.get("useclass1") or ""),
        "property_class": str(attrs.get("useclass1") or ""),
        "year_built": to_int(attrs.get("year_built"), 0),
        "building_market_value": to_int(attrs.get("emv_bldg"), 0),
        "total_market_value": to_int(attrs.get("emv_total"), 0),
        "owner_name": str(attrs.get("owner_name") or ""),
        "pin": str(attrs.get("county_pin") or ""),
        "county": str(attrs.get("co_name") or county_name),
        "latitude": lat,
        "longitude": lon,
    }

    if not building_sqft and lat and lon:
        osm = estimate_sqft_from_osm(lat, lon)
        result["building_sqft"] = osm["building_sqft"]
        result["building_sqft_source"] = osm["building_sqft_source"]
        result["building_sqft_confidence"] = osm["building_sqft_confidence"]
        if not osm["building_sqft"]:
            result["note"] = (
                "Building sqft not available from MN Open Parcels or OSM footprint data"
            )

    return result


def query_hennepin(
    address: str,
    *,
    api_url: str,
    timeout_seconds: float,
    estimate_sqft_from_osm: Callable[[float, float], Dict[str, Any]],
    http_get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    """Legacy Hennepin GIS query (kept for compatibility/tests)."""
    parsed = parse_address(address)
    if "house" not in parsed or "street" not in parsed:
        return {}

    house = sanitize_arcgis_value(parsed["house"])
    street = sanitize_arcgis_value(parsed["street"])
    where = [f"HOUSE_NO={house}", f"upper(STREET_NM) LIKE '{street}%'"]
    if parsed.get("suffix"):
        suffix = sanitize_arcgis_value(parsed["suffix"])
        where.append(f"upper(STREET_NM) LIKE '% {suffix}%'")

    params = {
        "where": " AND ".join(where),
        "outFields": (
            "HOUSE_NO,STREET_NM,ZIP_CD,PARCEL_AREA,BUILD_YR,PR_TYP_NM1,"
            "BLDG_MV1,MKT_VAL_TOT,NET_IMPRV_AMT,OWNER_NM,LAT,LON"
        ),
        "f": "json",
        "outSR": "4326",
        "returnGeometry": "false",
    }

    response = http_get(api_url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        return {}

    for feature in features:
        attrs = feature.get("attributes", {})
        parcel_area = to_float(attrs.get("PARCEL_AREA"), 0.0)
        if str(attrs.get("HOUSE_NO", "")).strip() != parsed["house"]:
            continue
        street_norm = str(attrs.get("STREET_NM", "")).replace(" ", "").replace(".", "").upper()
        if parsed["street"].replace(" ", "") not in street_norm:
            continue

        lat = to_float(attrs.get("LAT"))
        lon = to_float(attrs.get("LON"))
        osm = estimate_sqft_from_osm(lat, lon)

        note = ""
        if not osm["building_sqft"]:
            note = (
                "Building sqft not available from Hennepin GIS or OSM; "
                "use building_market_value for size estimates"
            )

        return {
            "address": attrs.get("STREET_NM", ""),
            "building_sqft": osm["building_sqft"],
            "building_sqft_source": osm["building_sqft_source"],
            "building_sqft_confidence": osm["building_sqft_confidence"],
            "lot_size": str(int(parcel_area)) if parcel_area else "",
            "zoning": attrs.get("PR_TYP_NM1", ""),
            "property_class": attrs.get("PR_TYP_NM1", ""),
            "year_built": to_int(attrs.get("BUILD_YR"), 0),
            "building_market_value": to_int(attrs.get("BLDG_MV1"), 0),
            "total_market_value": to_int(attrs.get("MKT_VAL_TOT"), 0),
            "owner_name": attrs.get("OWNER_NM", ""),
            "latitude": lat,
            "longitude": lon,
            "note": note,
        }
    return {}
