"""Winnebago County, IL - property data via WinGIS ArcGIS MapServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class WinnebagoCounty(ArcGISCountyModule):
    county_name = "Winnebago"
    state = "IL"
    source_label = "live_winnebago"
    fallback_csv = DATA_DIR / "winnebago_parcels.csv"
    arcgis_url = (
        "https://maps.wingis.org/public/rest/services/"
        "PropertySearch/MapServer/15/query"
    )
    field_map = ArcGISFieldMap(
        address_number="STNO",
        street_direction="PREFIX",
        street_name="STNAME",
        street_suffix="SUFFIX",
        pin="PIN",
    )


register(WinnebagoCounty())
