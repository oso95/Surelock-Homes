"""Download and cache Illinois provider records from DCFS Sunshine."""
from __future__ import annotations

from typing import Dict, List
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR
from tools.providers import IL_LIVE_CACHE, _load_il_live_records, refresh_il_provider_cache


TARGET_ZIPS = {
    "60612",
    "60621",
    "60623",
    "60624",
    "60629",
    "60636",
    "60637",
    "60644",
    "60649",
}


def run(*, zip_code: str | None = None, force_refresh: bool = False) -> List[Dict[str, object]]:
    """Refresh the IL provider cache and return parsed rows."""
    if force_refresh and IL_LIVE_CACHE.exists():
        IL_LIVE_CACHE.unlink()

    try:
        providers = refresh_il_provider_cache()
    except Exception:
        providers = _load_il_live_records()

    if zip_code:
        providers = [row for row in providers if (row.get("zip") or "").strip() == str(zip_code)]

    return providers


def main() -> None:
    providers = run()
    print(f"Loaded {len(providers)} IL provider records into {IL_LIVE_CACHE}")

    for zip_code in sorted(TARGET_ZIPS):
        count = len([row for row in providers if (row.get("zip") or "").strip() == zip_code])
        print(f"ZIP {zip_code}: {count}")

    fallback_path = DATA_DIR / "il_providers.csv"
    if fallback_path.exists():
        fallback_count = sum(1 for _ in fallback_path.read_text(encoding="utf-8").splitlines()) - 1
        print(f"Fallback rows available in {fallback_path}: {max(fallback_count, 0)}")


if __name__ == "__main__":
    main()
