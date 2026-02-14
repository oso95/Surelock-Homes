from __future__ import annotations

from hashlib import sha256
from typing import Any, Dict

import requests

from config import load_settings


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

