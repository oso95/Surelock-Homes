"""Pre-cache known Street View responses."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR
from tools.street_view import get_street_view


def run(addresses: list[str] | None = None) -> list[Path]:
    addresses = addresses or [
        "100 Birch Ave",
        "2301 S California Ave",
        "1847 W Roosevelt Rd",
        "606 Southfield St",
        "2500 S Indiana Ave",
    ]
    paths: list[Path] = []
    cache_dir = DATA_DIR / "cached_street_view"
    cache_dir.mkdir(exist_ok=True)
    for addr in addresses:
        payload = get_street_view(addr)
        slug = "".join(ch if ch.isalnum() else "_" for ch in addr.lower().strip())[:60]
        out = cache_dir / f"{slug}.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        paths.append(out)
    return paths


def main() -> None:
    cache_paths = run()
    print("Created/updated cache files:")
    for p in cache_paths:
        print(f"- {p}")


if __name__ == "__main__":
    main()
