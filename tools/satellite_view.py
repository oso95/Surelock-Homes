from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict

import requests

from config import DATA_DIR, load_settings

logger = logging.getLogger(__name__)


def _cache_path(address: str, zoom: int) -> Path:
    slug = "".join(ch if ch.isalnum() else "_" for ch in address.lower().strip())[:60]
    cache_dir = DATA_DIR / "cached_satellite_view"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / f"{slug}_z{zoom}.json"


def _fallback_result(address: str, zoom: int, size: str) -> Dict[str, Any]:
    payload = f"fallback satellite view placeholder for {address} zoom {zoom}"
    return {
        "status": "fallback",
        "address": address,
        "zoom": zoom,
        "size": size,
        "image_base64": base64.b64encode(payload.encode("utf-8")).decode("ascii"),
        "note": "No Google Maps API key configured; satellite view unavailable",
    }


def get_satellite_view(
    address: str,
    lat: float | None = None,
    lon: float | None = None,
    zoom: int = 19,
    size: str = "640x640",
) -> Dict[str, Any]:
    """Fetch a top-down satellite image from Google Maps Static API.

    Zoom 19 gives ~0.3m/pixel — building-level detail for visual estimation.
    """
    if not address and not (lat and lon):
        return {"status": "error", "error": "address or lat/lon is required"}

    cache_file = _cache_path(address or f"{lat}_{lon}", zoom)
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("address") == address:
            return cached

    settings = load_settings()
    if not settings.google_maps_api_key:
        return _fallback_result(address, zoom, size)

    # Use lat/lon if provided for precision, otherwise geocode from address
    center = f"{lat},{lon}" if lat and lon else address

    try:
        params = {
            "center": center,
            "zoom": zoom,
            "size": size,
            "maptype": "satellite",
            "key": settings.google_maps_api_key,
        }
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/staticmap",
            params=params,
            timeout=settings.google_api_timeout_seconds,
        )
        resp.raise_for_status()
        image_base64 = base64.b64encode(resp.content).decode("ascii")
    except Exception as exc:
        logger.warning("Satellite view API call failed for %s", address, exc_info=True)
        return {
            "status": "error",
            "error": "Satellite view lookup failed",
            "address": address,
            **_fallback_result(address, zoom, size),
        }

    response = {
        "status": "ok",
        "address": address,
        "zoom": zoom,
        "size": size,
        "image_base64": image_base64,
        "meters_per_pixel": round(156543.03392 * abs(
            __import__("math").cos(__import__("math").radians(lat or 45.0))
        ) / (2 ** zoom), 3),
    }
    cache_file.write_text(json.dumps(response, indent=2), encoding="utf-8")
    return response
