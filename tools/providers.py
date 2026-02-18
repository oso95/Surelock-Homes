from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
import shapefile

from config import DATA_DIR, load_settings as _load_settings

logger = logging.getLogger(__name__)


MN_SHAPE_URL = "https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_mngeo/econ_child_care/shp_econ_child_care.zip"
IL_DCFS_URL = "https://sunshine.dcfs.illinois.gov/Content/Licensing/Daycare/ProviderLookup.aspx"
PARENTAWARE_API_URL = "https://www.parentaware.org/wp-json/pa/v3/providers"
REQUEST_TIMEOUT_SECONDS = 8  # default; overridden by settings.gis_timeout_seconds
_PARENTAWARE_TIMEOUT_SECONDS = 10.0


def _request_timeout() -> int:
    try:
        return _load_settings().gis_timeout_seconds
    except Exception:
        return REQUEST_TIMEOUT_SECONDS

def _parentaware_timeout() -> float:
    try:
        return float(_load_settings().gis_timeout_seconds)
    except Exception:
        return _PARENTAWARE_TIMEOUT_SECONDS


MN_LIVE_CACHE = DATA_DIR / "mn_providers_live.csv"
IL_LIVE_CACHE = DATA_DIR / "il_providers_live.csv"

STATE_COLUMNS = ("name", "address", "city", "zip", "capacity", "license_type", "status", "state", "license_number")


def _normalize(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _coalesce_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return int(value)
        normalized = str(value).replace(",", "").replace(" ", "")
        if not normalized:
            return default
        return int(float(normalized))
    except (TypeError, ValueError):
        return default


def _provider_key(row: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        _normalize(row.get("name")),
        _normalize(row.get("address")),
        _normalize(row.get("zip")),
    )


def _is_fresh_cache(path: Path, *, max_age_hours: int | None = None) -> bool:
    if not path.exists():
        return False
    if max_age_hours is None:
        try:
            max_age_hours = _load_settings().cache_max_age_hours
        except Exception:
            max_age_hours = 12
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age <= timedelta(hours=max_age_hours)


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STATE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "name": row.get("name", ""),
                "address": row.get("address", ""),
                "city": row.get("city", ""),
                "zip": row.get("zip", ""),
                "capacity": row.get("capacity", 0),
                "license_type": row.get("license_type", ""),
                "status": row.get("status", ""),
                "state": row.get("state", ""),
                "license_number": row.get("license_number", ""),
            })


def _zip5(raw: str) -> str:
    """Extract the 5-digit ZIP from a possibly ZIP+4 string (e.g. '55454-1208' → '55454')."""
    return raw.split("-")[0].strip()[:5]


def _zip_matches(row_zip: str, target_zip: str, radius_miles: float) -> bool:
    """Check if a row's ZIP is within range of the target ZIP.

    Uses ZIP prefix proximity as an approximation:
    - radius <= 5: exact 5-digit ZIP match only
    - radius <= 25: same 3-digit ZIP prefix (~15-25 mile radius)
    - radius > 25: same state (no ZIP filter applied)
    """
    rz = _zip5(_normalize(row_zip))
    tz = _zip5(_normalize(target_zip))
    if not tz:
        return True
    if radius_miles <= 5:
        return rz == tz
    if radius_miles <= 25:
        return len(rz) >= 3 and len(tz) >= 3 and rz[:3] == tz[:3]
    return True


def _filter(
    records: List[Dict[str, Any]],
    *,
    city: Optional[str],
    state: str,
    zip_code: Optional[str],
    radius_miles: float = 5,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in records:
        if row.get("state", "").upper() != state.upper():
            continue
        if zip_code and not _zip_matches(row.get("zip", ""), zip_code, radius_miles):
            continue
        if city and _normalize(row.get("city")) != _normalize(city):
            continue
        normalized = {
            "name": (row.get("name") or "").strip(),
            "address": (row.get("address") or "").strip(),
            "city": (row.get("city") or "").strip(),
            "zip": (row.get("zip") or "").strip(),
            "capacity": _coalesce_int(row.get("capacity"), 0),
            "license_type": (row.get("license_type") or "").strip(),
            "status": (row.get("status") or "").strip(),
            "state": (row.get("state") or "").strip().upper(),
            "license_number": (row.get("license_number") or "").strip(),
        }
        result.append(normalized)
    return result


def _parse_mn_record(record: Dict[str, Any], source: str = "shapefile") -> Optional[Dict[str, Any]]:
    raw_name = (record.get("Name_of_Pr") or "").strip()
    if not raw_name:
        return None

    address = " ".join(
        part.strip()
        for part in (
            record.get("AddressLin", ""),
            record.get("AddressL_1", ""),
        )
        if part
    ).strip()
    return {
        "source": source,
        "name": raw_name,
        "address": address,
        "city": (record.get("City") or "").strip(),
        "zip": (record.get("Zip") or "").strip(),
        "capacity": _coalesce_int(record.get("Capacity"), 0),
        "license_type": (record.get("License_Ty") or "").strip(),
        "status": (record.get("Status") or "Active").strip(),
        "state": (record.get("State") or "MN").strip().upper(),
        "license_number": str(record.get("License_Nu", "")).strip(),
    }


def _mn_cache_has_license_number() -> bool:
    """Check if the MN cache CSV includes the license_number column."""
    if not MN_LIVE_CACHE.exists():
        return False
    with MN_LIVE_CACHE.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        return header is not None and "license_number" in header


def _load_mn_live_records() -> List[Dict[str, Any]]:
    if _is_fresh_cache(MN_LIVE_CACHE) and _mn_cache_has_license_number():
        return _read_csv(MN_LIVE_CACHE)

    response = requests.get(MN_SHAPE_URL, timeout=_request_timeout())
    response.raise_for_status()
    shp_data = io.BytesIO(response.content)
    z = zipfile.ZipFile(shp_data)
    with z.open("econ_child_care.dbf") as dbf_file:
        reader = shapefile.Reader(dbf=dbf_file)
        keys = [field[0] for field in reader.fields[1:]]
        rows: List[Dict[str, Any]] = []
        for values in reader.records():
            row = dict(zip(keys, values))
            parsed = _parse_mn_record(row)
            if parsed:
                rows.append(parsed)

    _write_csv(MN_LIVE_CACHE, rows)
    return rows


def _parse_dcfs_rows_from_payload(payload: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for parsed in csv.reader(io.StringIO(payload)):
        if len(parsed) < 17:
            continue
        if not re.match(r"^\d{6}$", str(parsed[0]).strip()):
            continue
        rows.append(
            {
                "license_number": str(parsed[0]).strip(),
                "name": str(parsed[1]).strip(),
                "address": str(parsed[2]).strip(),
                "city": str(parsed[3]).strip(),
                "county": str(parsed[4]).strip(),
                "zip": str(parsed[5]).strip(),
                "phone": str(parsed[6]).strip(),
                "license_type": str(parsed[7]).strip(),
                "age_range": str(parsed[8]).strip(),
                "unused_lang_1": str(parsed[9]).strip(),
                "language_1": str(parsed[10]).strip(),
                "language_2": str(parsed[11]).strip(),
                "status": str(parsed[16]).strip(),
                "capacity": str(parsed[14]).strip(),
            }
        )
    return rows


def _load_il_live_records() -> List[Dict[str, Any]]:
    if _is_fresh_cache(IL_LIVE_CACHE):
        return _read_csv(IL_LIVE_CACHE)

    session = requests.Session()
    page = session.get(IL_DCFS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=_request_timeout())
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    form_data = {}
    for element in soup.find_all("input"):
        name = element.get("name")
        if not name:
            continue
        form_data[name] = element.get("value", "")
    form_data["__EVENTTARGET"] = "ctl00$ContentPlaceHolderContent$ASPxSearch"
    for key in [k for k in form_data if k.endswith("ASPxSearch") and k.startswith("ctl00$ContentPlaceHolderContent$")]:
        form_data[key] = "Search"

    response = session.post(IL_DCFS_URL, data=form_data, headers={"User-Agent": "Mozilla/5.0"}, timeout=_request_timeout())
    response.raise_for_status()
    parsed = _parse_dcfs_rows_from_payload(response.text)
    rows = [
        {
            "name": row.get("name", "").strip(),
            "address": row.get("address", "").strip(),
            "city": row.get("city", "").strip(),
            "zip": row.get("zip", "").strip(),
            "capacity": _coalesce_int(row.get("capacity"), 0),
            "license_type": row.get("license_type", ""),
            "status": row.get("status", ""),
            "state": "IL",
        }
        for row in parsed
    ]
    if rows:
        _write_csv(IL_LIVE_CACHE, rows)
    return rows


def _get_fallback_records(state_key: str) -> List[Dict[str, str]]:
    if state_key == "MN":
        return _read_csv(DATA_DIR / "mn_providers.csv")
    if state_key == "IL":
        return _read_csv(DATA_DIR / "il_providers.csv")
    return []


def _get_live_cache_path(state_key: str) -> Optional[Path]:
    if state_key == "MN":
        return MN_LIVE_CACHE
    if state_key == "IL":
        return IL_LIVE_CACHE
    return None


def _load_stale_cache(state_key: str) -> List[Dict[str, Any]]:
    cache_path = _get_live_cache_path(state_key)
    if cache_path is None or not cache_path.exists():
        return []
    return _read_csv(cache_path)


def _tag_source(records: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    for row in records:
        row["source"] = source
    return records


def _query_parentaware_by_name(name: str) -> List[Dict[str, Any]]:
    """Search ParentAware.org API by provider name. Returns list of provider dicts."""
    if not name:
        return []
    try:
        encoded = requests.utils.quote(name, safe="")
        url = f"{PARENTAWARE_API_URL}/search/{encoded}"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_parentaware_timeout(),
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []
    except Exception:
        logger.warning("ParentAware API search failed for %r", name, exc_info=True)
        return []


def _pa_address_line1(pa: Dict[str, Any]) -> str:
    """Extract the street address (line1) from a ParentAware address dict."""
    addr = pa.get("address")
    if isinstance(addr, dict):
        return (addr.get("line1") or "").strip()
    if isinstance(addr, str):
        return addr.strip()
    return ""


def _normalize_street(addr: str) -> str:
    """Normalize a street address for fuzzy comparison."""
    a = addr.upper().strip().split(",")[0].strip()
    for full, abbr in [
        ("STREET", "ST"), ("AVENUE", "AVE"), ("ROAD", "RD"), ("DRIVE", "DR"),
        ("BOULEVARD", "BLVD"), ("PLACE", "PL"), ("COURT", "CT"), ("LANE", "LN"),
        ("WEST", "W"), ("EAST", "E"), ("NORTH", "N"), ("SOUTH", "S"),
    ]:
        a = re.sub(r"\b" + full + r"\b", abbr, a)
    return re.sub(r"\s+", " ", a).strip()


def _apply_pa_enrichment(provider: Dict[str, Any], pa: Dict[str, Any]) -> None:
    """Apply ParentAware fields to a provider record."""
    cap = pa.get("licensedCapacity")
    if cap is not None:
        provider["capacity"] = _coalesce_int(cap, provider.get("capacity", 0))
    if pa.get("licenseStatus"):
        provider["license_status"] = pa["licenseStatus"]
    if pa.get("ageRange"):
        provider["age_range"] = pa["ageRange"]
    if pa.get("acceptsCCAP") is not None:
        provider["accepts_ccap"] = pa["acceptsCCAP"]


def _enrich_mn_with_parentaware(providers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enrich MN provider records with capacity data from ParentAware API."""
    for provider in providers:
        license_num = provider.get("license_number", "")
        name = provider.get("name", "")
        provider_addr = provider.get("address", "")
        if not name:
            continue
        try:
            results = _query_parentaware_by_name(name)
            matched = None

            # Priority 1: Match by license number
            if license_num:
                for pa in results:
                    if str(pa.get("licenseId", "")).strip() == license_num:
                        matched = pa
                        break

            # Priority 2: Match by street address
            if matched is None and provider_addr:
                norm_provider = _normalize_street(provider_addr)
                for pa in results:
                    pa_line1 = _pa_address_line1(pa)
                    if pa_line1 and _normalize_street(pa_line1) == norm_provider:
                        matched = pa
                        break

            # Priority 3: Single result fallback
            if matched is None and len(results) == 1:
                matched = results[0]

            if matched is not None:
                _apply_pa_enrichment(provider, matched)
        except Exception:
            logger.warning("ParentAware enrichment failed for %r", name, exc_info=True)
    return providers


def search_childcare_providers(
    city: str | None = None,
    state: str = "MN",
    zip: str | None = None,
    radius_miles: float = 5,
    offline: bool = False,
) -> List[Dict[str, Any]]:
    state_key = (state or "").upper()

    # Offline mode: use fixture data only (for demo/offline investigations)
    if offline:
        records = _get_fallback_records(state_key)
        filtered = _filter(records, city=city, state=state_key, zip_code=zip, radius_miles=radius_miles)
        return _tag_source(filtered, "fallback")

    # Online mode: three-tier hierarchy — live, stale cache, empty (NEVER fixtures)

    # Tier 1: Fresh live fetch
    records: List[Dict[str, Any]] = []
    try:
        if state_key == "MN":
            records = _load_mn_live_records()
        elif state_key == "IL":
            records = _load_il_live_records()
    except Exception:
        logger.warning("Failed to load %s live records", state_key, exc_info=True)
        records = []

    if records:
        filtered = _filter(records, city=city, state=state_key, zip_code=zip, radius_miles=radius_miles)
        if state_key == "MN" and filtered:
            _enrich_mn_with_parentaware(filtered)
        return _tag_source(filtered, "live")

    # Tier 2: Stale cache (real data from a previous successful fetch)
    stale = _load_stale_cache(state_key)
    if stale:
        logger.info("Using stale cache for %s (%d records)", state_key, len(stale))
        filtered = _filter(stale, city=city, state=state_key, zip_code=zip, radius_miles=radius_miles)
        return _tag_source(filtered, "stale_cache")

    # Tier 3: No data available — return empty, NEVER fixture data
    logger.warning("No live or cached data available for %s", state_key)
    return []


def refresh_mn_provider_cache() -> List[Dict[str, Any]]:
    if MN_LIVE_CACHE.exists():
        MN_LIVE_CACHE.unlink()
    return _load_mn_live_records()


def refresh_il_provider_cache() -> List[Dict[str, Any]]:
    if IL_LIVE_CACHE.exists():
        IL_LIVE_CACHE.unlink()
    return _load_il_live_records()
