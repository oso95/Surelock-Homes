"""OSM/Overpass helpers for estimating building square footage."""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_TIMEOUT = 6.0
_OSM_SEARCH_RADIUS_M = 50
_OSM_RATE_LIMIT_DELAY = 0.5
_last_osm_call: float = 0.0


def shoelace_area_sqft(coords: List[List[float]]) -> float:
    """Compute polygon area in sq ft from lat/lon coordinates."""
    if len(coords) < 3:
        return 0.0

    ref_lat = sum(c[1] for c in coords) / len(coords)
    lat_rad = math.radians(ref_lat)
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_132.0 * math.cos(lat_rad)

    xs = [(c[0] - coords[0][0]) * m_per_deg_lon for c in coords]
    ys = [(c[1] - coords[0][1]) * m_per_deg_lat for c in coords]

    area = 0.0
    for i in range(len(xs)):
        j = (i + 1) % len(xs)
        area += xs[i] * ys[j]
        area -= xs[j] * ys[i]
    area_m2 = abs(area) / 2.0
    return area_m2 * 10.7639


def estimate_sqft_from_osm(
    lat: float,
    lon: float,
    *,
    http_post: Callable[..., Any] | None = None,
    last_call_store: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Query Overpass for building polygons near coordinates and estimate sqft."""
    global _last_osm_call
    post_fn = http_post or requests.post

    result = {
        "building_sqft": 0.0,
        "building_sqft_source": "none",
        "building_sqft_confidence": "none",
    }
    if not lat or not lon:
        return result

    last_call = _last_osm_call if last_call_store is None else float(last_call_store.get("value", 0.0))
    elapsed = time.time() - last_call
    if elapsed < _OSM_RATE_LIMIT_DELAY:
        time.sleep(_OSM_RATE_LIMIT_DELAY - elapsed)

    query = (
        f'[out:json][timeout:{int(_OVERPASS_TIMEOUT)}];'
        f'way["building"](around:{_OSM_SEARCH_RADIUS_M},{lat},{lon});'
        f'out body;>;out skel qt;'
    )
    try:
        now = time.time()
        if last_call_store is None:
            _last_osm_call = now
        else:
            last_call_store["value"] = now

        resp = post_fn(
            _OVERPASS_URL,
            data={"data": query},
            timeout=_OVERPASS_TIMEOUT + 2,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.debug("OSM Overpass query failed for (%s, %s)", lat, lon, exc_info=True)
        return result

    elements = data.get("elements", [])
    if not elements:
        return result

    nodes: Dict[int, List[float]] = {}
    ways: List[Dict[str, Any]] = []
    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = [el["lon"], el["lat"]]
        elif el["type"] == "way":
            ways.append(el)

    best_area = 0.0
    for way in ways:
        node_ids = way.get("nodes", [])
        coords = [nodes[nid] for nid in node_ids if nid in nodes]
        if len(coords) < 3:
            continue
        area = shoelace_area_sqft(coords)
        if area > best_area:
            best_area = area

    if best_area > 0:
        result["building_sqft"] = round(best_area, 1)
        result["building_sqft_source"] = "osm_footprint"
        result["building_sqft_confidence"] = "moderate"

    return result
