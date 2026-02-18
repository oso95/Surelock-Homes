from __future__ import annotations

import csv
import logging
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote, urlencode

from config import DATA_DIR, load_settings

logger = logging.getLogger(__name__)


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()


def _read_rows() -> List[Dict[str, str]]:
    path = DATA_DIR / "business_registration.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


MN_SOS_URL = "https://mblsportal.sos.mn.gov/Business/Search"
MN_SOS_DETAIL_URL = "https://mblsportal.sos.mn.gov"
_MN_SOS_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _search_mn_sos(name: str) -> List[Dict[str, Any]]:
    """Search MN Secretary of State Business Filings and parse results."""
    settings = load_settings()
    timeout = settings.probe_timeout_seconds

    session = requests.Session()
    page = session.get(MN_SOS_URL, headers=_MN_SOS_HEADERS, timeout=timeout)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    token_el = soup.find("input", {"name": "__RequestVerificationToken"})
    token = token_el["value"] if token_el else ""

    data = {
        "__RequestVerificationToken": token,
        "BusinessName": name,
        "Type": "Contains",
        "Status": "Active",
        "IncludePriorNames": "False",
        "RequiredValue": "",
    }
    resp = session.post(MN_SOS_URL, data=data, headers=_MN_SOS_HEADERS, timeout=timeout)
    resp.raise_for_status()

    results_soup = BeautifulSoup(resp.text, "html.parser")
    table = results_soup.find("table")
    if not table:
        return []

    matches: List[Dict[str, Any]] = []
    for row in table.find_all("tr")[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        cell = cells[0]
        biz_name_el = cell.find("strong")
        biz_name = biz_name_el.get_text(strip=True) if biz_name_el else ""

        # Extract status, type, name type from small section
        spans = cell.find_all("span")
        biz_status = spans[0].get_text(strip=True) if len(spans) > 0 else ""
        biz_type = spans[1].get_text(strip=True) if len(spans) > 1 else ""

        link = cells[1].find("a", href=True)
        detail_href = link["href"] if link else ""

        entry = {
            "business_name": biz_name,
            "registration_status": biz_status,
            "entity_type": biz_type,
            "state": "MN",
        }

        # Fetch detail page for richer data
        if detail_href:
            try:
                detail = _fetch_mn_sos_detail(session, detail_href, timeout)
                entry.update(detail)
            except Exception:
                logger.debug("Failed to fetch MN SOS detail for %s", biz_name, exc_info=True)

        matches.append(entry)

    return matches


def _fetch_mn_sos_detail(session: requests.Session, href: str, timeout: float) -> Dict[str, Any]:
    """Fetch and parse an MN SOS business detail page using dt/dd structure."""
    url = MN_SOS_DETAIL_URL + href if href.startswith("/") else href
    resp = session.get(url, headers=_MN_SOS_HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    detail: Dict[str, Any] = {}
    field_map = {
        "File Number": "file_number",
        "Filing Date": "incorporation_date",
        "Status": "registration_status",
        "Business Type": "entity_type",
        "Renewal Due Date": "renewal_due_date",
        "Home Jurisdiction": "home_jurisdiction",
        "Principal Place of Business Address": "registered_address",
    }

    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True)
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        value = dd.get_text(separator=", ", strip=True)
        key = field_map.get(label)
        if key:
            detail[key] = value

    # Extract applicant/agent name from the text structure
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if line == "Applicant" and i + 1 < len(lines):
                # Skip "Address" sub-label if present
                j = i + 1
                if lines[j] == "Applicant":
                    j += 1
                if j < len(lines) and lines[j] == "Address":
                    j += 1
                if j < len(lines) and lines[j] not in ("Filing History", "Renewal History"):
                    detail["registered_agent"] = lines[j].split(",")[0].strip()
                break

    return detail


def _live_registration_probe(state: str, name: str) -> Dict[str, Any] | None:
    state_key = (state or "").upper()
    target = _normalize(name)
    settings = load_settings()
    if state_key == "IL":
        endpoint = "https://www.cyberdriveillinois.com/corpservices/api/entitysearch?" + urlencode({"searchstring": target})
        try:
            response = requests.get(endpoint, timeout=settings.probe_timeout_seconds)
            if response.status_code == 403:
                return {
                    "status": "blocked",
                    "note": "IL SOS API is behind a CDN firewall (HTTP 403). Direct API access is not available.",
                }
            if 200 <= response.status_code < 400:
                return {
                    "status": "live_available_not_parsed",
                    "note": "cyberdriveillinois endpoint reachable; parser is not implemented in this environment.",
                }
        except Exception:
            logger.warning("IL business registration probe failed", exc_info=True)
            return None
    elif state_key == "MN":
        try:
            results = _search_mn_sos(name)
            if results:
                return {"status": "found", "results": results}
            return {
                "status": "live_no_match",
                "note": "MN SOS search returned no matching filings.",
            }
        except Exception:
            logger.warning("MN SOS live search failed", exc_info=True)
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
