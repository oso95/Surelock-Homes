"""Kendall County, IL - property data via ArcGIS Hosted FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class KendallCounty(ArcGISCountyModule):
    county_name = "Kendall"
    state = "IL"
    source_label = "live_kendall"
    fallback_csv = DATA_DIR / "kendall_parcels.csv"
    arcgis_url = (
        "https://maps.co.kendall.il.us/server/rest/services/"
        "Hosted/fabric_hosted/FeatureServer/1/query"
    )
    field_map = ArcGISFieldMap(
        full_address="site_address",
        pin="pin",
        property_class="class",
        lot_sqft="gross_acres",
        owner_name="owner_name",
    )


register(KendallCounty())
