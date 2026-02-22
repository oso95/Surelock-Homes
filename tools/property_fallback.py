"""CSV fallback utilities for property lookup."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def collect_fallback_paths(
    state_key: str,
    resolved_county: str | None,
    config: Optional[Any],
    *,
    property_registry: Dict[str, Any],
    get_county_module: Callable[[str, str], Any],
) -> List[Path]:
    """Build an ordered list of fallback CSV paths to search."""
    paths: List[Path] = []

    if resolved_county:
        county_mod = get_county_module(state_key, resolved_county)
        if county_mod is not None and getattr(county_mod, "fallback_csv", None):
            paths.append(county_mod.fallback_csv)

    if config is not None:
        if config.fallback_csv not in paths:
            paths.append(config.fallback_csv)
    else:
        for cfg in property_registry.values():
            if cfg.fallback_csv not in paths:
                paths.append(cfg.fallback_csv)

    return paths


def _row_to_result(
    *,
    row: Dict[str, str],
    state_key: str,
    source: str,
    county_override: str | None = None,
    live_error: str | None = None,
    live_fallback: bool = False,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "found",
        "source": source,
        "address": row.get("address", ""),
        "building_sqft": float(row.get("building_sqft", 0) or 0),
        "lot_size": row.get("lot_size", ""),
        "zoning": row.get("zoning", ""),
        "property_class": row.get("property_class", ""),
        "year_built": int(float(row.get("year_built", 0) or 0)),
        "county": row.get("county", "") or county_override or "",
        "state": row.get("state", state_key),
    }
    if live_error is not None:
        result["live_error"] = live_error
    if live_fallback:
        result["live_fallback"] = True
    return result


def find_match_in_paths(
    *,
    address: str,
    state_key: str,
    paths: List[Path],
    read_rows: Callable[[Path], List[Dict[str, str]]],
    address_matches: Callable[[str, str], bool],
    source_suffix: str = "",
    county_override: str | None = None,
    live_error: str | None = None,
    live_fallback: bool = False,
) -> Optional[Dict[str, Any]]:
    """Search ordered fallback paths and return the first matching row result."""
    for path in paths:
        if not path.exists():
            continue
        for row in read_rows(path):
            if address_matches(address, row.get("address", "")):
                return _row_to_result(
                    row=row,
                    state_key=state_key,
                    source=f"{path.name}{source_suffix}",
                    county_override=county_override,
                    live_error=live_error,
                    live_fallback=live_fallback,
                )
    return None


def fallback_property_result(
    *,
    address: str,
    state_key: str,
    county: str | None,
    config: Optional[Any],
    live_error: str | None,
    property_registry: Dict[str, Any],
    get_county_module: Callable[[str, str], Any],
    read_rows: Callable[[Path], List[Dict[str, str]]],
    address_matches: Callable[[str, str], bool],
) -> Dict[str, Any]:
    paths = collect_fallback_paths(
        state_key=state_key,
        resolved_county=county,
        config=config,
        property_registry=property_registry,
        get_county_module=get_county_module,
    )
    found = find_match_in_paths(
        address=address,
        state_key=state_key,
        paths=paths,
        read_rows=read_rows,
        address_matches=address_matches,
        source_suffix=".fallback",
        county_override=county,
        live_error=live_error,
        live_fallback=True,
    )
    if found:
        return found

    return {
        "status": "not_found",
        "source": "fallback",
        "address": address,
        "building_sqft": 0.0,
        "lot_size": "",
        "zoning": "",
        "property_class": "",
        "year_built": 0,
        "county": county or "",
        "state": state_key,
        "error": "no parcel match in local datasets",
        "live_error": live_error,
    }
