from __future__ import annotations

"""Download and cache Minnesota provider data from MN Geospatial Commons."""

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.providers import refresh_mn_provider_cache
from config import DATA_DIR


MN_TARGET = DATA_DIR / "mn_providers_live.csv"


def run() -> None:
    providers = refresh_mn_provider_cache()
    print(f"Loaded {len(providers)} MN provider records into {MN_TARGET}")


def main() -> None:
    run()
    print("Done. Source: https://gisdata.mn.gov/dataset/health-child-care-providers")


if __name__ == "__main__":
    main()
