from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from config import DATA_DIR
from config import load_settings as _load_settings
from tools import property_fallback as _fallback
from tools import property_live_cook as _live_cook
from tools import property_live_mn as _live_mn
from tools import property_osm as _osm
from tools.property_helpers import (
    address_matches as _address_matches,
    escape_where_literal as _escape_where_literal,
    extract_city as _extract_city,
    extract_zip as _extract_zip,
    normalize_street_name as _normalize_street_name,
    normalize_suffix as _normalize_suffix,
    parse_address as _parse_address,
    sanitize_arcgis_value as _sanitize_arcgis_value,
    street_variants as _street_variants,
    to_float as _to_float,
    to_int as _to_int,
)

HENNEPIN_API_URL = (
    "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1/query"
)
MN_OPEN_PARCELS_API_URL = (
    "https://utility.arcgis.com/usrsvcs/servers/"
    "1627519e8d3f42bcb55532d48e9a61e5/rest/services/OpenParcels/plan_parcels_open/MapServer/0/query"
)
CENSUS_GEOGRAPHY_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
)

# Cook County Assessor Socrata Open Data endpoints (replaces dead ArcGIS)
COOK_ADDR_URL = "https://datacatalog.cookcountyil.gov/resource/3723-97qp.json"
COOK_RES_URL = "https://datacatalog.cookcountyil.gov/resource/x54s-btds.json"
COOK_ASSESSED_URL = "https://datacatalog.cookcountyil.gov/resource/uzyt-m557.json"
COOK_COMMERCIAL_URL = "https://datacatalog.cookcountyil.gov/resource/csik-bsws.json"

_GIS_TIMEOUT_SECONDS = 8.0
_SOCRATA_TIMEOUT_SECONDS = 10.0

_MN_COUNTY_GEOCODE_CACHE: Dict[str, Optional[str]] = {}

# Kept for backward-compatible tests that monkeypatch this module variable.
_last_osm_call: float = 0.0

logger = logging.getLogger(__name__)


@dataclass
class PropertyCountyConfig:
    live_query: Callable[[str], Dict[str, Any]]
    fallback_csv: Path
    default_county: str
    source_label: str


# Registry populated after query wrappers are defined (see bottom of module)
PROPERTY_REGISTRY: Dict[str, PropertyCountyConfig] = {}


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


# -- OSM wrappers (compatibility-preserving private API) ----------------------

def _shoelace_area_sqft(coords: List[List[float]]) -> float:
    return _osm.shoelace_area_sqft(coords)


def _estimate_sqft_from_osm(lat: float, lon: float) -> Dict[str, Any]:
    global _last_osm_call
    store = {"value": _last_osm_call}
    result = _osm.estimate_sqft_from_osm(
        lat,
        lon,
        http_post=requests.post,
        last_call_store=store,
    )
    _last_osm_call = float(store.get("value", 0.0))
    return result


# -- MN live wrappers ---------------------------------------------------------

def _mn_where_clause(
    *,
    parsed: Dict[str, str],
    county: str | None,
    city: str,
    zip_code: str,
    include_house: bool,
    strict_street: bool,
) -> str:
    return _live_mn.mn_where_clause(
        parsed=parsed,
        county=county,
        city=city,
        zip_code=zip_code,
        include_house=include_house,
        strict_street=strict_street,
    )


def _query_mn_open_parcels_layer(where: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    return _live_mn.query_mn_open_parcels_layer(
        where,
        api_url=MN_OPEN_PARCELS_API_URL,
        timeout_seconds=_gis_timeout(),
        limit=limit,
        http_get=requests.get,
    )


def _query_mn_open_parcels(address: str, county: str | None = None) -> Dict[str, Any]:
    return _live_mn.query_mn_open_parcels(
        address,
        county=county,
        query_layer=lambda where, limit: _query_mn_open_parcels_layer(where, limit=limit),
        estimate_sqft_from_osm=_estimate_sqft_from_osm,
    )


def _query_hennepin(address: str) -> Dict[str, Any]:
    return _live_mn.query_hennepin(
        address,
        api_url=HENNEPIN_API_URL,
        timeout_seconds=_gis_timeout(),
        estimate_sqft_from_osm=_estimate_sqft_from_osm,
        http_get=requests.get,
    )


# -- Cook live wrappers -------------------------------------------------------

def _socrata_address_to_pin(address: str) -> Optional[str]:
    return _live_cook.socrata_address_to_pin(
        address,
        addr_url=COOK_ADDR_URL,
        timeout_seconds=_socrata_timeout(),
        http_get=requests.get,
    )


def _socrata_residential(pin: str) -> Dict[str, Any]:
    return _live_cook.socrata_residential(
        pin,
        residential_url=COOK_RES_URL,
        timeout_seconds=_socrata_timeout(),
        http_get=requests.get,
    )


def _socrata_commercial(pin: str) -> Dict[str, Any]:
    return _live_cook.socrata_commercial(
        pin,
        commercial_url=COOK_COMMERCIAL_URL,
        timeout_seconds=_socrata_timeout(),
        http_get=requests.get,
    )


def _socrata_assessed(pin: str) -> Dict[str, Any]:
    return _live_cook.socrata_assessed(
        pin,
        assessed_url=COOK_ASSESSED_URL,
        timeout_seconds=_socrata_timeout(),
        http_get=requests.get,
    )


def _query_cook(address: str) -> Dict[str, Any]:
    return _live_cook.query_cook(
        address,
        address_to_pin=_socrata_address_to_pin,
        residential_lookup=_socrata_residential,
        commercial_lookup=_socrata_commercial,
        assessed_lookup=_socrata_assessed,
    )


# -- County resolution --------------------------------------------------------

def _resolve_mn_county_from_geocoder(address: str) -> str | None:
    key = (address or "").strip().upper()
    if not key:
        return None
    if key in _MN_COUNTY_GEOCODE_CACHE:
        return _MN_COUNTY_GEOCODE_CACHE[key]

    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    try:
        response = requests.get(
            CENSUS_GEOGRAPHY_GEOCODER_URL,
            params=params,
            timeout=_gis_timeout(),
            headers={"User-Agent": "SurelockHomes/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        matches = payload.get("result", {}).get("addressMatches", [])
        if not matches:
            _MN_COUNTY_GEOCODE_CACHE[key] = None
            return None

        counties = (matches[0].get("geographies") or {}).get("Counties") or []
        if not counties:
            _MN_COUNTY_GEOCODE_CACHE[key] = None
            return None

        raw_name = str(counties[0].get("NAME") or "").strip()
        county_name = re.sub(r"\s+County$", "", raw_name, flags=re.IGNORECASE).strip()
        _MN_COUNTY_GEOCODE_CACHE[key] = county_name or None
        return _MN_COUNTY_GEOCODE_CACHE[key]
    except Exception:
        logger.debug("MN county geocoder lookup failed for %r", address, exc_info=True)
        _MN_COUNTY_GEOCODE_CACHE[key] = None
        return None


def _resolve_county(address: str, county: str | None, state: str | None) -> str | None:
    """Resolve county from explicit parameter or address/ZIP routing."""
    if county:
        return county

    state_key = (state or "").upper()
    if state_key == "IL":
        zip_code = _extract_zip(address)
        if zip_code:
            from tools.counties._zip_routing import resolve_county_from_zip

            return resolve_county_from_zip(zip_code)
    elif state_key == "MN":
        return _resolve_mn_county_from_geocoder(address)

    return None


def _get_county_module(state: str, county: str):
    """Lazy import and lookup of a county module from the registry."""
    from tools.counties import get_county

    return get_county(state, county)


# -- Fallback wrappers --------------------------------------------------------

def _read_csv(path: Path) -> List[Dict[str, str]]:
    return _fallback.read_csv(path)


def _collect_fallback_paths(
    state_key: str,
    resolved_county: str | None,
    config: Optional[PropertyCountyConfig],
) -> List[Path]:
    return _fallback.collect_fallback_paths(
        state_key=state_key,
        resolved_county=resolved_county,
        config=config,
        property_registry=PROPERTY_REGISTRY,
        get_county_module=_get_county_module,
    )


def _fallback_property_result(
    *,
    address: str,
    state_key: str,
    county: str | None = None,
    live_error: str | None = None,
) -> Dict[str, Any]:
    config = PROPERTY_REGISTRY.get(state_key)
    return _fallback.fallback_property_result(
        address=address,
        state_key=state_key,
        county=county,
        config=config,
        live_error=live_error,
        property_registry=PROPERTY_REGISTRY,
        get_county_module=_get_county_module,
        read_rows=_read_csv,
        address_matches=_address_matches,
    )


# -- Public façade ------------------------------------------------------------

_LIVE_EXTRA_FIELDS = (
    "building_market_value",
    "total_market_value",
    "owner_name",
    "latitude",
    "longitude",
    "note",
    "pin",
    "source_dataset",
    "assessed_total",
    "building_sqft_source",
    "building_sqft_confidence",
)


def _build_live_found_result(
    *,
    source: str,
    address: str,
    county: str,
    state_key: str,
    live: Dict[str, Any],
) -> Dict[str, Any]:
    result = {
        "status": "found",
        "source": source,
        "address": live.get("address", address),
        "building_sqft": live.get("building_sqft", 0.0),
        "lot_size": live.get("lot_size", ""),
        "zoning": live.get("zoning", ""),
        "property_class": live.get("property_class", ""),
        "year_built": live.get("year_built", 0),
        "county": county,
        "state": state_key,
    }
    for extra in _LIVE_EXTRA_FIELDS:
        if live.get(extra):
            result[extra] = live[extra]
    return result


def get_property_data(
    address: str,
    county: str | None = None,
    state: str | None = None,
    offline: bool = False,
) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required"}

    state_key = (state or "").upper()
    resolved_county = county if offline else _resolve_county(address, county, state)

    # County-level dispatch
    if not offline and resolved_county:
        county_mod = _get_county_module(state_key, resolved_county)
        if county_mod is not None:
            try:
                live = county_mod.query(address)
                if live:
                    return _build_live_found_result(
                        source=county_mod.source_label,
                        address=address,
                        county=resolved_county,
                        state_key=state_key,
                        live=live,
                    )
                return {
                    "status": "not_found",
                    "source": county_mod.source_label,
                    "address": address,
                    "building_sqft": 0.0,
                    "lot_size": "",
                    "zoning": "",
                    "property_class": "",
                    "year_built": 0,
                    "county": resolved_county,
                    "state": state_key,
                    "error": "no parcel match in live county dataset",
                    "live_not_found": True,
                }
            except Exception as exc:
                logger.warning(
                    "Live %s County query failed for %s: %s",
                    resolved_county,
                    address,
                    exc,
                    exc_info=True,
                )
                return _fallback_property_result(
                    address=address,
                    state_key=state_key,
                    county=resolved_county,
                    live_error=str(exc),
                )

    # State-level dispatch
    config = PROPERTY_REGISTRY.get(state_key)
    if not offline and config is not None:
        try:
            live = config.live_query(address)
            if live:
                return _build_live_found_result(
                    source=config.source_label,
                    address=address,
                    county=resolved_county or config.default_county,
                    state_key=state_key,
                    live=live,
                )
            return {
                "status": "not_found",
                "source": config.source_label,
                "address": address,
                "building_sqft": 0.0,
                "lot_size": "",
                "zoning": "",
                "property_class": "",
                "year_built": 0,
                "county": resolved_county or config.default_county,
                "state": state_key,
                "error": "no parcel match in live county dataset",
                "live_not_found": True,
            }
        except Exception as exc:
            logger.warning(
                "Live %s query failed for %s: %s",
                config.default_county,
                address,
                exc,
                exc_info=True,
            )
            return _fallback_property_result(
                address=address,
                state_key=state_key,
                county=resolved_county or county,
                live_error=str(exc),
            )

    # CSV fallback in offline mode
    fallback_paths = _collect_fallback_paths(state_key, resolved_county, config)
    found = _fallback.find_match_in_paths(
        address=address,
        state_key=state_key,
        paths=fallback_paths,
        read_rows=_read_csv,
        address_matches=_address_matches,
    )
    if found:
        return found

    return {
        "status": "not_found",
        "source": "fallback",
        "address": address,
        "building_sqft": 0.0,
        "lot_size": "",
        "zoning": "",
        "property_class": "",
        "year_built": 0,
        "county": resolved_county or county or "",
        "state": state_key,
        "error": "no parcel match in local datasets",
    }


# Populate the registry now that all wrappers are defined
PROPERTY_REGISTRY.update(
    {
        "MN": PropertyCountyConfig(
            live_query=lambda address: _query_mn_open_parcels(address, county=None),
            fallback_csv=DATA_DIR / "hennepin_parcels.csv",
            default_county="Minnesota",
            source_label="live_mn_open_parcels",
        ),
        "IL": PropertyCountyConfig(
            # Lambda keeps monkeypatching _query_cook test-friendly.
            live_query=lambda address: _query_cook(address),
            fallback_csv=DATA_DIR / "cook_parcels.csv",
            default_county="Cook",
            source_label="live_cook",
        ),
    }
)
