"""Hennepin County, MN - delegates to MN Open Parcels lookup."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import CountyModule
from tools.counties import register


class HennepinCounty(CountyModule):
    county_name = "Hennepin"
    state = "MN"
    source_label = "live_mn_open_parcels"
    fallback_csv = DATA_DIR / "hennepin_parcels.csv"

    def query(self, address: str) -> Dict[str, Any]:
        from tools.property import _query_mn_open_parcels
        return _query_mn_open_parcels(address, county=self.county_name)


register(HennepinCounty())
