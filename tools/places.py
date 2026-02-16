from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from config import load_settings

logger = logging.getLogger(__name__)


def _find_place_candidates(address: str, api_key: str, timeout: int) -> List[Dict[str, Any]]:
    queries = [
        address,
        f"{address} child care",
        f"childcare {address}",
    ]
    for query in queries:
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
        if candidates:
            return candidates
    return []


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
            return {"status": "not_found", "address": address, "error": "No place results"}
        place_id = candidates[0].get("place_id")
        details = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "name,business_status,rating,user_ratings_total,types,review",
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
        return {
            "status": "ok",
            "address": address,
            "place_name": detail_payload.get("name"),
            "business_type": ", ".join(detail_payload.get("types", [])),
            "operating_status": detail_payload.get("business_status"),
            "rating": detail_payload.get("rating"),
            "review_count": detail_payload.get("user_ratings_total", 0),
            "recent_reviews": detail_payload.get("reviews", [])[:3],
        }
    except Exception as exc:
        logger.warning("Google Places API call failed for %s", address, exc_info=True)
        return {"status": "error", "address": address, "error": str(exc) or "Places lookup failed"}
