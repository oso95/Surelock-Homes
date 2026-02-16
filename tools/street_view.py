from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import requests

from config import DATA_DIR, load_settings

logger = logging.getLogger(__name__)


def _cache_path(address: str) -> Path:
    slug = "".join(ch if ch.isalnum() else "_" for ch in address.lower().strip())[:60]
    cache_dir = DATA_DIR / "cached_street_view"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / f"{slug}.json"


def _fallback_images(address: str, headings: List[int], size: str) -> List[Dict[str, Any]]:
    image_blocks = []
    for heading in headings:
        payload = f"fallback street view placeholder for {address} heading {heading}"
        image_blocks.append(
            {
                "heading": heading,
                "image_base64": base64.b64encode(payload.encode("utf-8")).decode("ascii"),
                "capture_date": "fallback",
                "status": "fallback",
            }
        )
    return image_blocks


def get_street_view(
    address: str,
    headings: List[int] | None = None,
    size: str = "640x480",
) -> Dict[str, Any]:
    if not address:
        return {"status": "error", "error": "address is required", "images": []}

    headings = headings or [0, 90, 180, 270]
    cache_file = _cache_path(address)
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("address") == address:
            return cached

    settings = load_settings()
    if not settings.google_maps_api_key:
        return {
            "status": "fallback",
            "address": address,
            "size": size,
            "headings": headings,
            "images": _fallback_images(address, headings, size),
        }

    images = []
    try:
        for heading in headings:
            params = {"location": address, "heading": heading, "size": size, "key": settings.google_maps_api_key}
            meta = requests.get(
                "https://maps.googleapis.com/maps/api/streetview/metadata",
                params={**params, "return_error_codes": True},
                timeout=5,
            )
            meta_payload = meta.json()
            meta_status = str(meta_payload.get("status", "")).upper()
            if meta_status not in {"OK", "ZERO_RESULTS"}:
                message = meta_payload.get("status", "unknown_error")
                if meta_payload.get("status") == "REQUEST_DENIED":
                    raise RuntimeError(f"Street View denied: {meta_payload.get('error_message', message)}")
                if meta_payload.get("status") not in {"ZERO_RESULTS"}:
                    raise RuntimeError(f"Street View metadata error: {message}")
            img_resp = requests.get(
                "https://maps.googleapis.com/maps/api/streetview",
                params=params,
                timeout=5,
            )
            img_resp.raise_for_status()
            image_base64 = base64.b64encode(img_resp.content).decode("ascii")
            images.append(
                {
                    "heading": heading,
                    "image_base64": image_base64,
                    "capture_date": meta_payload.get("date", "unknown"),
                    "status": meta_payload.get("status", "unknown"),
                }
            )
    except Exception as exc:
        logger.warning("Street View API call failed for %s", address, exc_info=True)
        return {
            "status": "error",
            "error": "Street View lookup failed",
            "address": address,
            "images": _fallback_images(address, headings, size),
        }

    response = {
        "status": "ok",
        "address": address,
        "size": size,
        "headings": headings,
        "images": images,
    }
    cache_file.write_text(json.dumps(response, indent=2), encoding="utf-8")
    return response
