"""Shared helpers for property data parsing, normalization, and matching."""
from __future__ import annotations

import re
from typing import Dict, List

ADDRESS_RE = re.compile(r"^(?P<number>\d+)\s+(?P<rest>.+)$")
SUFFIXES = {
    "ST": "ST",
    "STREET": "ST",
    "ST.": "ST",
    "AVE": "AVE",
    "AVENUE": "AVE",
    "AVE.": "AVE",
    "RD": "RD",
    "ROAD": "RD",
    "RD.": "RD",
    "BLVD": "BLVD",
    "BOULEVARD": "BLVD",
    "BLVD.": "BLVD",
    "CT": "CT",
    "COURT": "CT",
    "CT.": "CT",
    "LN": "LN",
    "LANE": "LN",
    "LN.": "LN",
    "PL": "PL",
    "PLACE": "PL",
    "PL.": "PL",
    "DR": "DR",
    "DRIVE": "DR",
    "DR.": "DR",
    "TER": "TER",
    "TERRACE": "TER",
    "TER.": "TER",
    "PKWY": "PKWY",
    "PARKWAY": "PKWY",
    "PKWY.": "PKWY",
}
DIRECTIONS = {
    "N": "N",
    "NORTH": "N",
    "S": "S",
    "SOUTH": "S",
    "E": "E",
    "EAST": "E",
    "W": "W",
    "WEST": "W",
}
_ORDINAL_SUFFIX_RE = re.compile(r"(\d+)(ST|ND|RD|TH)\b", re.IGNORECASE)


def extract_zip(address: str) -> str:
    if not address:
        return ""
    match = re.search(r"\b(\d{5})\b", address)
    return match.group(1) if match else ""


def normalize_addr(address: str) -> str:
    return (address or "").lower().replace(".", "").replace(",", "").strip()


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: object, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def parse_address(address: str) -> Dict[str, str]:
    if not address:
        return {}

    # Prefer the street-level portion before the first comma so
    # "123 Main St, City" still parses as the street address.
    text = (address or "").replace(".", "").split(",")[0].strip().upper()
    text = re.sub(r"\s+", " ", text).strip()
    match = ADDRESS_RE.match(text)
    if not match:
        return {}

    number = match.group("number")
    rest = re.sub(r"\s+", " ", match.group("rest")).strip()
    tokens = rest.split()
    if not tokens:
        return {"house": number}

    # Remove trailing ZIP/state artifacts when callers pass a full address.
    if tokens and re.fullmatch(r"\d{5}", tokens[-1]):
        tokens = tokens[:-1]
    if tokens and tokens[-1] in {"IL", "IL.", "MN", "MN.", "WI", "WI.", "CA", "CA.", "NY", "NY."}:
        tokens = tokens[:-1]

    if not tokens:
        return {"house": number}

    direction = ""
    if tokens[0] in DIRECTIONS:
        direction = DIRECTIONS[tokens[0]]
        tokens = tokens[1:]
    if not tokens:
        return {"house": number}

    suffix = ""
    suffix_index: int | None = None
    for idx, token in enumerate(tokens):
        if token in SUFFIXES:
            suffix_index = idx
            suffix = SUFFIXES[token]
            break
    if suffix_index is not None:
        street_tokens = tokens[:suffix_index]
        trailing = tokens[suffix_index + 1:]
        if trailing and trailing[0] in DIRECTIONS and not direction:
            direction = DIRECTIONS[trailing[0]]
    else:
        street_tokens = tokens

    street = " ".join(street_tokens)
    return {"house": number, "direction": direction, "street": street, "suffix": suffix}


def sanitize_arcgis_value(value: str) -> str:
    sanitized = value.replace("'", "''")
    sanitized = re.sub(r"[^A-Za-z0-9 \-.]", "", sanitized)
    return sanitized


def extract_city(address: str) -> str:
    if not address:
        return ""
    parts = [part.strip() for part in address.split(",")]
    if len(parts) < 2:
        return ""
    return parts[1].upper()


def normalize_street_name(value: str) -> str:
    text = str(value or "").upper().strip().replace(".", "")
    text = _ORDINAL_SUFFIX_RE.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_suffix(value: str) -> str:
    token = str(value or "").upper().replace(".", "").strip()
    return SUFFIXES.get(token, token)


def street_variants(street: str) -> List[str]:
    raw = normalize_street_name(street)
    if not raw:
        return []
    variants = {raw}
    variants.add(_ORDINAL_SUFFIX_RE.sub(r"\1", raw))
    variants.add(re.sub(r"[^A-Z0-9 ]", "", raw))
    return sorted(v for v in variants if v)


def escape_where_literal(value: str) -> str:
    return sanitize_arcgis_value(value or "")


def address_matches(address_target: str, address_row: str) -> bool:
    parsed_target = parse_address(address_target)
    parsed_row = parse_address(address_row)

    if not parsed_target or not parsed_row:
        return normalize_addr(address_target) == normalize_addr(address_row)

    if parsed_target.get("house") != parsed_row.get("house"):
        return False

    if parsed_target.get("street") != parsed_row.get("street"):
        return False

    if (
        parsed_target.get("suffix")
        and parsed_row.get("suffix")
        and parsed_target["suffix"] != parsed_row["suffix"]
    ):
        return False

    if (
        parsed_target.get("direction")
        and parsed_row.get("direction")
        and parsed_target["direction"] != parsed_row["direction"]
    ):
        return False

    target_zip = extract_zip(address_target)
    row_zip = extract_zip(address_row)
    if target_zip and row_zip and target_zip != row_zip:
        return False

    return True
