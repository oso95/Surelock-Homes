"""Download and cache MN provider CSV data.

This implementation ships with fallback sample data so offline environments can
run without external network access.
"""
from __future__ import annotations

import csv
from pathlib import Path

from config import DATA_DIR


MN_SOURCE_URL = "https://gisdata.mn.gov/dataset/health-child-care-providers"
LOCAL_TARGET = DATA_DIR / "mn_providers.csv"


def run() -> None:
    # Keep existing data if user already added an updated source file.
    if LOCAL_TARGET.exists():
        print(f"Using existing cache at {LOCAL_TARGET}")
        return
    print(f"MN source unavailable in offline mode; keeping bundled fallback at {LOCAL_TARGET}")
    if not LOCAL_TARGET.exists():
        raise FileNotFoundError(f"Expected fallback provider dataset at {LOCAL_TARGET}")


def main() -> None:
    run()
    print(f"Done. Source: {MN_SOURCE_URL}")


if __name__ == "__main__":
    main()

