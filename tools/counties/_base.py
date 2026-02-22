"""Base classes for county property data modules."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import requests

from config import load_settings as _load_settings
from tools.property_helpers import (
    parse_address as _parse_address,
    sanitize_arcgis_value as _sanitize_arcgis_value,
    to_float as _to_float,
    to_int as _to_int,
)
from tools.property_osm import estimate_sqft_from_osm as _estimate_sqft_from_osm

logger = logging.getLogger(__name__)

_GIS_TIMEOUT_SECONDS = 8.0


def _gis_timeout() -> float:
    try:
        return float(_load_settings().gis_timeout_seconds)
    except Exception:
        return _GIS_TIMEOUT_SECONDS


@dataclass
class ArcGISFieldMap:
    """Maps county-specific ArcGIS field names to standard output fields."""

    address_number: str = ""
    street_name: str = ""
    street_direction: str = ""
    street_suffix: str = ""
    full_address: str = ""
    building_sqft: str = ""
    lot_sqft: str = ""
    year_built: str = ""
    property_class: str = ""
    pin: str = ""
    owner_name: str = ""
    latitude: str = ""
    longitude: str = ""


class CountyModule(ABC):
    """Abstract base class for a county property data module."""

    county_name: str = ""
    state: str = ""
    source_label: str = ""
    fallback_csv: Path = Path()

    @abstractmethod
    def query(self, address: str) -> Dict[str, Any]:
        """Query property data for an address. Returns {} on no match."""

class ArcGISCountyModule(CountyModule):
    """Generic ArcGIS REST query logic shared by county modules.

    Subclasses define ``arcgis_url`` and ``field_map``; this class handles
    building the WHERE clause, issuing the HTTP request, validating the match,
    and normalising the response into the standard output dict.
    """

    arcgis_url: str = ""
    field_map: ArcGISFieldMap = ArcGISFieldMap()
    # Subclasses can set extra HTTP headers (e.g. Referer for portal proxies).
    _request_headers: Dict[str, str] = {}

    # Subclasses can override to customise the WHERE clause construction.
    # By default we match on address number + street name prefix.
    def _build_where(self, parsed: Dict[str, str]) -> str:
        fm = self.field_map
        house = _sanitize_arcgis_value(parsed["house"])
        street = _sanitize_arcgis_value(parsed["street"])

        if fm.full_address:
            return f"upper({fm.full_address}) LIKE '{house} %{street}%'"

        clauses: List[str] = []
        if fm.address_number:
            clauses.append(f"{fm.address_number}='{house}'")
        if fm.street_name:
            clauses.append(f"upper({fm.street_name}) LIKE '{street}%'")

        if parsed.get("direction") and fm.street_direction:
            direction = _sanitize_arcgis_value(parsed["direction"])
            clauses.append(f"upper({fm.street_direction})='{direction}'")

        return " AND ".join(clauses)

    def _out_fields(self) -> str:
        fm = self.field_map
        fields = [
            fm.address_number, fm.street_name, fm.street_direction,
            fm.street_suffix, fm.full_address, fm.building_sqft,
            fm.lot_sqft, fm.year_built, fm.property_class, fm.pin,
            fm.owner_name, fm.latitude, fm.longitude,
        ]
        return ",".join(f for f in fields if f)

    def _validate_match(self, attrs: Dict[str, Any], parsed: Dict[str, str]) -> bool:
        """Verify the returned feature actually matches the requested address."""
        fm = self.field_map

        # Check house number
        if fm.address_number:
            gis_house = str(attrs.get(fm.address_number, "")).strip()
            if gis_house != parsed["house"]:
                return False

        # Check street name
        if fm.street_name:
            gis_street = str(attrs.get(fm.street_name, "")).replace(".", "").upper().strip()
            if parsed["street"].replace(" ", "") not in gis_street.replace(" ", ""):
                return False

        # Check full address if that's the match field
        if fm.full_address and not fm.address_number:
            gis_addr = str(attrs.get(fm.full_address, "")).upper()
            if parsed["house"] not in gis_addr or parsed["street"] not in gis_addr:
                return False

        return True

    def _extract_result(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        fm = self.field_map

        building_sqft = _to_float(attrs.get(fm.building_sqft)) if fm.building_sqft else 0.0
        lot_size = _to_float(attrs.get(fm.lot_sqft)) if fm.lot_sqft else 0.0
        year_built = _to_int(attrs.get(fm.year_built)) if fm.year_built else 0
        prop_class = str(attrs.get(fm.property_class, "")) if fm.property_class else ""
        pin = str(attrs.get(fm.pin, "")) if fm.pin else ""
        owner = str(attrs.get(fm.owner_name, "")) if fm.owner_name else ""

        lat = _to_float(attrs.get(fm.latitude)) if fm.latitude else 0.0
        lon = _to_float(attrs.get(fm.longitude)) if fm.longitude else 0.0

        # Build display address from components
        parts = []
        if fm.address_number:
            parts.append(str(attrs.get(fm.address_number, "")))
        if fm.street_direction:
            d = str(attrs.get(fm.street_direction, "")).strip()
            if d:
                parts.append(d)
        if fm.street_name:
            parts.append(str(attrs.get(fm.street_name, "")))
        if fm.street_suffix:
            s = str(attrs.get(fm.street_suffix, "")).strip()
            if s:
                parts.append(s)
        display_address = " ".join(p.strip() for p in parts if p.strip())
        if not display_address and fm.full_address:
            display_address = str(attrs.get(fm.full_address, ""))

        result: Dict[str, Any] = {
            "address": display_address,
            "building_sqft": building_sqft,
            "lot_size": str(int(lot_size)) if lot_size else "",
            "zoning": "",
            "property_class": prop_class,
            "year_built": year_built,
        }

        if pin:
            result["pin"] = pin
        if owner:
            result["owner_name"] = owner
        if lat:
            result["latitude"] = lat
        if lon:
            result["longitude"] = lon

        # If the GIS lacks building sqft, try OSM footprint estimation
        if not building_sqft and lat and lon:
            osm = _estimate_sqft_from_osm(lat, lon)
            result["building_sqft"] = osm["building_sqft"]
            result["building_sqft_source"] = osm["building_sqft_source"]
            result["building_sqft_confidence"] = osm["building_sqft_confidence"]
            if not osm["building_sqft"]:
                result["note"] = (
                    f"Building sqft not available from {self.county_name} County GIS or OSM"
                )

        return result

    def query(self, address: str) -> Dict[str, Any]:
        parsed = _parse_address(address)
        if "house" not in parsed or "street" not in parsed:
            return {}

        where = self._build_where(parsed)
        params = {
            "where": where,
            "outFields": self._out_fields(),
            "f": "json",
            "outSR": "4326",
            "returnGeometry": "false",
            "resultRecordCount": "5",
        }

        resp = requests.get(
            self.arcgis_url, params=params, headers=self._request_headers,
            timeout=_gis_timeout(),
        )
        resp.raise_for_status()
        payload = resp.json()

        features = payload.get("features") or []
        if not features:
            return {}

        for feature in features:
            attrs = feature.get("attributes", {})
            if self._validate_match(attrs, parsed):
                return self._extract_result(attrs)

        return {}
