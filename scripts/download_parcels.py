"""Download/refresh parcel datasets.

In this implementation, parcel CSV files are local fixtures to keep offline demos
stable and deterministic.
"""
from __future__ import annotations

from config import DATA_DIR


def run() -> None:
    for file_name in ("hennepin_parcels.csv", "cook_parcels.csv"):
        path = DATA_DIR / file_name
        if not path.exists():
            raise FileNotFoundError(f"Missing required parcel dataset: {path}")
        print(f"Loaded {path}")


def main() -> None:
    run()


if __name__ == "__main__":
    main()

