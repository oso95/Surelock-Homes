from __future__ import annotations

import logging
from hashlib import sha256
from typing import Any, Dict

import requests

from config import load_settings

logger = logging.getLogger(__name__)


def _stable_coordinate(value: str) -> float:
    digest = sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / (16 ** 8)


def geocode_address(address: str) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required"}

    settings = load_settings()
    if settings.google_maps_api_key:
        params = {"address": address, "key": settings.google_maps_api_key}
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params=params,
                timeout=5,
            )
            resp.raise_for_status()
            payload = resp.json()
            status = str(payload.get("status", "")).upper()
            if status == "REQUEST_DENIED":
                return {
                    "status": "error",
                    "address": address,
                    "formatted_address": None,
                    "lat": None,
                    "lng": None,
                    "valid": False,
                    "error": payload.get("error_message", "Google geocoding request denied"),
                }
            if status not in {"OK", "ZERO_RESULTS"}:
                return {
                    "status": "error",
                    "address": address,
                    "formatted_address": None,
                    "lat": None,
                    "lng": None,
                    "valid": False,
                    "error": payload.get("error_message", f"Google geocode error: {status}"),
                }
            result = payload.get("results", [])[0] if payload.get("results") else None
            if not result:
                return {
                    "status": "not_found",
                    "address": address,
                    "formatted_address": None,
                    "lat": None,
                    "lng": None,
                    "valid": False,
                }
            loc = result["geometry"]["location"]
            return {
                "status": "ok",
                "address": address,
                "formatted_address": result.get("formatted_address"),
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "valid": True,
                "place_id": result.get("place_id"),
            }
        except Exception:
            logger.warning("Geocoding API call failed for %s", address, exc_info=True)
            return {
                "status": "error",
                "address": address,
                "formatted_address": None,
                "lat": None,
                "lng": None,
                "valid": False,
            }

    # Deterministic fallback location within the continental U.S. bounds.
    base_lat = 24.0 + (_stable_coordinate(address) * 28.0)
    base_lng = -125.0 + (_stable_coordinate(address[::-1]) * 51.0)
    return {
        "status": "fallback",
        "address": address,
        "formatted_address": address.title(),
        "lat": round(base_lat, 6),
        "lng": round(base_lng, 6),
        "valid": True,
    }
