from __future__ import annotations

import csv
import logging
import requests
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote, urlencode

from config import DATA_DIR

logger = logging.getLogger(__name__)


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()


def _read_rows() -> List[Dict[str, str]]:
    path = DATA_DIR / "business_registration.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _live_registration_probe(state: str, name: str) -> Dict[str, Any] | None:
    state_key = (state or "").upper()
    target = _normalize(name)
    if state_key == "IL":
        endpoint = "https://www.cyberdriveillinois.com/corpservices/api/entitysearch?" + urlencode({"searchstring": target})
        try:
            response = requests.get(endpoint, timeout=10)
            if response.status_code >= 200 and response.status_code < 500:
                return {
                    "status": "live_available_not_parsed",
                    "note": "cyberdriveillinois endpoint reachable; parser is not implemented in this environment.",
                }
        except Exception:
            logger.warning("IL business registration probe failed", exc_info=True)
            return None
    elif state_key == "MN":
        endpoint = "https://mblsportal.sos.state.mn.us/Business/search/" + quote(target, safe="")
        try:
            response = requests.get(endpoint, timeout=10)
            if response.status_code >= 200 and response.status_code < 500:
                return {
                    "status": "live_available_not_parsed",
                    "note": "MN SOS endpoint reachable; parser is not implemented in this environment.",
                }
        except Exception:
            logger.warning("MN business registration probe failed", exc_info=True)
            return None
    return None


def check_business_registration(
    name: str,
    state: str,
    search_type: str = "business",
) -> List[Dict[str, Any]] | Dict[str, Any]:
    if not name:
        return {"status": "error", "error": "name is required"}

    rows = _read_rows()
    needle = _normalize(name)
    state_key = (state or "").upper()
    matches = []

    for row in rows:
        if row.get("state", "").upper() != state_key:
            continue
        target_field = "business_name" if search_type == "business" else "registered_agent"
        candidate = row.get(target_field, "").lower()
        if needle in candidate:
            matches.append(
                {
                    "status": "found",
                    "business_name": row.get("business_name", ""),
                    "state": row.get("state", state_key),
                    "registered_agent": row.get("registered_agent", ""),
                    "entity_type": row.get("entity_type", ""),
                    "registration_status": row.get("registration_status", ""),
                    "incorporation_date": row.get("incorporation_date", ""),
                    "registered_address": row.get("registered_address", ""),
                }
            )

    if not matches:
        live_probe = _live_registration_probe(state_key, name)
        if live_probe:
            return {
                "status": "not_found",
                "state": state_key,
                "search_type": search_type,
                "results": [],
                "live_probe": live_probe,
            }
        return {
            "status": "not_found",
            "query": name,
            "state": state_key,
            "search_type": search_type,
            "results": [],
        }

    return matches if search_type == "agent" else {"status": "found", "results": matches}
