from __future__ import annotations

from typing import Any, Dict, List

import requests

from config import load_settings


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
        find_resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
            params={"input": address, "inputtype": "textquery", "fields": "place_id,name,types", "key": settings.google_maps_api_key},
            timeout=5,
        )
        find_resp.raise_for_status()
        candidates = find_resp.json().get("candidates", [])
        if not candidates:
            return {"status": "not_found", "address": address, "error": "No place results"}
        place_id = candidates[0].get("place_id")
        details = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "fields": "business_status,rating,user_ratings_total,types,review", "key": settings.google_maps_api_key},
            timeout=5,
        )
        detail_payload = details.json().get("result", {})
        return {
            "status": "ok",
            "address": address,
            "business_type": ", ".join(detail_payload.get("types", [])),
            "operating_status": detail_payload.get("business_status"),
            "rating": detail_payload.get("rating"),
            "review_count": detail_payload.get("user_ratings_total", 0),
            "recent_reviews": detail_payload.get("reviews", [])[:3],
        }
    except Exception as exc:
        return {"status": "error", "address": address, "error": str(exc)}

