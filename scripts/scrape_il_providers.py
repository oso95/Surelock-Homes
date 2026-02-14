"""Pre-scrape IL provider CSV for target ZIPs.

The full DCFS Sunshine scraper is out-of-scope for this repository setup stage.
Instead, this script validates local cache and keeps target ZIPs ready for demo runs.
"""
from __future__ import annotations

from pathlib import Path

from config import DATA_DIR

TARGET_ZIPS = [
    "60612",
    "60621",
    "60623",
    "60624",
    "60629",
    "60636",
    "60637",
    "60644",
    "60649",
]


def run() -> Path:
    target = DATA_DIR / "il_providers.csv"
    if not target.exists():
        raise FileNotFoundError(f"Expected IL provider dataset at {target}")

    # Keep one-row-per-line simple output for transparency.
    return target


def main() -> None:
    path = run()
    print(f"IL provider cache ready: {path}")
    print("Target ZIPs:", ", ".join(TARGET_ZIPS))


if __name__ == "__main__":
    main()

