"""Minnesota high-impact counties via MnGeo Open Parcels."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import CountyModule
from tools.counties import register


MN_HIGH_IMPACT_COUNTIES = (
    "Hennepin",
    "Ramsey",
    "Dakota",
    "Anoka",
    "Washington",
    "Olmsted",
    "St. Louis",
    "Stearns",
    "Scott",
    "Wright",
    "Carver",
    "Sherburne",
)


class MnOpenParcelsCounty(CountyModule):
    state = "MN"
    source_label = "live_mn_open_parcels"
    # No county-specific CSV fallback currently exists; state fallback still applies.
    fallback_csv = DATA_DIR / "mn_open_parcels.csv"

    def __init__(self, county_name: str) -> None:
        self.county_name = county_name

    def query(self, address: str) -> Dict[str, Any]:
        from tools.property import _query_mn_open_parcels
        return _query_mn_open_parcels(address, county=self.county_name)


for _county_name in MN_HIGH_IMPACT_COUNTIES:
    register(MnOpenParcelsCounty(_county_name))

