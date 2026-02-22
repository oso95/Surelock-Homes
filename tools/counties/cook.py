"""Cook County, IL - delegates to existing Socrata-based property lookup."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import CountyModule
from tools.counties import register


class CookCounty(CountyModule):
    county_name = "Cook"
    state = "IL"
    source_label = "live_cook"
    fallback_csv = DATA_DIR / "cook_parcels.csv"

    def query(self, address: str) -> Dict[str, Any]:
        from tools.property import _query_cook
        return _query_cook(address)


register(CookCounty())
