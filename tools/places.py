from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import requests

from config import load_settings
from tools.geocoding import geocode_address

logger = logging.getLogger(__name__)


def _is_childcare_candidate(candidate: Dict[str, Any]) -> bool:
    fields = [str(candidate.get("name", ""))]
    fields.extend(str(type_value) for type_value in candidate.get("types", []))
    haystack = " ".join(fields).lower()
    return any(token in haystack for token in ("daycare", "day care", "child", "preschool", "school", "nursery"))


def _find_place_candidates(address: str, api_key: str, timeout: int) -> List[Dict[str, Any]]:
    addr = address.strip()
    query_plan = [
        (f"childcare {addr}", True),
        (f"child care {addr}", True),
        (f"daycare {addr}", True),
        (f"preschool {addr}", True),
        (f"kids center {addr}", True),
        (addr, False),
    ]
    for query, require_childcare in query_plan:
        query = query.strip()
        if not query:
            continue
        find_resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
            params={"input": query, "inputtype": "textquery", "fields": "place_id,name,types", "key": api_key},
            timeout=timeout,
        )
        find_resp.raise_for_status()
        payload = find_resp.json()
        status = str(payload.get("status", "")).upper()
        if status not in {"OK", "ZERO_RESULTS"}:
            message = payload.get("error_message", "Google Places request failed")
            raise RuntimeError(f"findplacefromtext error {status}: {message}")
        candidates = payload.get("candidates", [])
        for candidate in candidates:
            if not require_childcare or _is_childcare_candidate(candidate):
                return [candidate]
    return []


def _house_number(address: str) -> str:
    match = re.search(r"\b(\d+)\b", address or "")
    return match.group(1) if match else ""


def _has_matching_house(formatted: str, expected_house: str) -> bool:
    return bool(expected_house and re.search(rf"\b{re.escape(expected_house)}\b", formatted))


def _build_no_place_result(address: str, note: str) -> Dict[str, Any]:
    geocoded = geocode_address(address)
    house_number = _house_number(address)
    formatted_address = geocoded.get("formatted_address")
    geo_status = str(geocoded.get("status", "")).lower()
    has_house_match = bool(formatted_address and _has_matching_house(str(formatted_address), house_number))

    if geo_status == "error":
        notes = geocoded.get("error") or note
        formatted_address = None
        latitude = None
        longitude = None
    else:
        if house_number and not has_house_match:
            notes = (
                "Google Places returned no match for this facility, and geocoding resolved a nearby/related address "
                "that does not match the requested street number."
            )
        else:
            notes = geocoded.get("error") or note

        latitude = geocoded.get("lat")
        longitude = geocoded.get("lng")

    return {
        "status": "no_place",
        "address": address,
        "formatted_address": formatted_address,
        "business_type": "address_only",
        "operating_status": "not_listed_as_business",
        "rating": None,
        "review_count": 0,
        "recent_reviews": [],
        "latitude": latitude,
        "longitude": longitude,
        "notes": geocoded.get("error") or notes,
        "geocode_status": geocoded.get("status"),
    }


def get_places_info(address: str) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required"}

    settings = load_settings()
    if not settings.google_maps_api_key:
        lowered = address.lower()
        is_likely_care = any(tok in lowered for tok in ["day", "child", "care", "school", "kids", "family"])
        return {
            "status": "fallback",
            "address": address,
            "business_type": "child care center" if is_likely_care else "unknown",
            "operating_status": "likely_open",
            "rating": None,
            "review_count": 0,
            "recent_reviews": [],
            "notes": "No Google API key configured.",
        }

    try:
        candidates = _find_place_candidates(address, settings.google_maps_api_key, timeout=5)
        if not candidates:
            return _build_no_place_result(address, "No Google Places childcare record found; address was geocoded.")

        place_id = candidates[0].get("place_id")
        details = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "name,business_status,rating,user_ratings_total,types,reviews,geometry,formatted_address",
                "key": settings.google_maps_api_key,
            },
            timeout=5,
        )
        details.raise_for_status()
        detail_payload = details.json()
        detail_status = str(detail_payload.get("status", "")).upper()
        if detail_status not in {"OK", "ZERO_RESULTS"}:
            message = detail_payload.get("error_message", "Google Places detail request failed")
            raise RuntimeError(f"place/details error {detail_status}: {message}")

        detail_payload = detail_payload.get("result", {})
        geometry = detail_payload.get("geometry", {}).get("location", {})
        formatted_address = detail_payload.get("formatted_address", "")
        expected_house = _house_number(address)

        if expected_house and formatted_address:
            has_house_match = bool(re.search(rf"\\b{re.escape(expected_house)}\\b", formatted_address))
            if not has_house_match:
                return _build_no_place_result(address, "Place result matched no matching street number; using geocode fallback.")

        return {
            "status": "ok",
            "address": address,
            "place_name": detail_payload.get("name"),
            "formatted_address": detail_payload.get("formatted_address"),
            "business_type": ", ".join(detail_payload.get("types", [])),
            "operating_status": detail_payload.get("business_status"),
            "rating": detail_payload.get("rating"),
            "review_count": detail_payload.get("user_ratings_total", 0),
            "recent_reviews": detail_payload.get("reviews", [])[:3],
            "latitude": geometry.get("lat"),
            "longitude": geometry.get("lng"),
            "notes": "Google Places record found.",
        }
    except Exception as exc:
        logger.warning("Google Places API call failed for %s", address, exc_info=True)
        return {"status": "error", "address": address, "error": str(exc) or "Places lookup failed"}
