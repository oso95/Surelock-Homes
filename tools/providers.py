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

from config import DATA_DIR

logger = logging.getLogger(__name__)


MN_SHAPE_URL = "https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_mngeo/econ_child_care/shp_econ_child_care.zip"
IL_DCFS_URL = "https://sunshine.dcfs.illinois.gov/Content/Licensing/Daycare/ProviderLookup.aspx"

MN_LIVE_CACHE = DATA_DIR / "mn_providers_live.csv"
IL_LIVE_CACHE = DATA_DIR / "il_providers_live.csv"

STATE_COLUMNS = ("name", "address", "city", "zip", "capacity", "license_type", "status", "state")


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


def _is_fresh_cache(path: Path, *, max_age_hours: int = 12) -> bool:
    if not path.exists():
        return False
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
            })


def _filter(
    records: List[Dict[str, Any]],
    *,
    city: Optional[str],
    state: str,
    zip_code: Optional[str],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in records:
        if row.get("state", "").upper() != state.upper():
            continue
        if zip_code and _normalize(row.get("zip")) != _normalize(zip_code):
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
    }


def _load_mn_live_records() -> List[Dict[str, Any]]:
    if _is_fresh_cache(MN_LIVE_CACHE):
        return _read_csv(MN_LIVE_CACHE)

    response = requests.get(MN_SHAPE_URL, timeout=30)
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
    page = session.get(IL_DCFS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
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

    response = session.post(IL_DCFS_URL, data=form_data, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
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


def search_childcare_providers(
    city: str | None = None,
    state: str = "MN",
    zip: str | None = None,
    radius_miles: float = 5,
) -> List[Dict[str, Any]]:
    _ = radius_miles  # reserved for future geospatial filtering
    state_key = (state or "").upper()
    records: List[Dict[str, Any]]

    if state_key == "MN":
        try:
            records = _load_mn_live_records()
        except Exception:
            logger.warning("Failed to load MN live records, using fallback", exc_info=True)
            records = _get_fallback_records(state_key)
    elif state_key == "IL":
        try:
            records = _load_il_live_records()
        except Exception:
            logger.warning("Failed to load IL live records, using fallback", exc_info=True)
            records = _get_fallback_records(state_key)
    else:
        records = []

    live_filtered = _filter(records, city=city, state=state_key, zip_code=zip)
    fallback_records = _filter(_get_fallback_records(state_key), city=city, state=state_key, zip_code=zip)

    if not live_filtered:
        return fallback_records
    if not fallback_records:
        return live_filtered

    # Merge live + fallback deterministically, prioritizing bundled fixtures
    merged: List[Dict[str, Any]] = []
    for row in fallback_records:
        row.setdefault("source", "fallback")
        merged.append(row)
    seen = {_provider_key(r) for r in merged}
    for row in live_filtered:
        row.setdefault("source", "live")
        if _provider_key(row) in seen:
            continue
        seen.add(_provider_key(row))
        merged.append(row)
    return merged


def refresh_mn_provider_cache() -> List[Dict[str, Any]]:
    if MN_LIVE_CACHE.exists():
        MN_LIVE_CACHE.unlink()
    return _load_mn_live_records()


def refresh_il_provider_cache() -> List[Dict[str, Any]]:
    if IL_LIVE_CACHE.exists():
        IL_LIVE_CACHE.unlink()
    return _load_il_live_records()
