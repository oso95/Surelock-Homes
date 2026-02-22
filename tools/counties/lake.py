"""Lake County, IL - property data via ArcGIS Open Data FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class LakeCounty(ArcGISCountyModule):
    county_name = "Lake"
    state = "IL"
    source_label = "live_lake"
    fallback_csv = DATA_DIR / "lake_parcels.csv"
    arcgis_url = (
        "https://services3.arcgis.com/HESxeTbDliKKvec2/arcgis/rest/services/"
        "OpenData_ParcelPolygons/FeatureServer/0/query"
    )
    field_map = ArcGISFieldMap(
        full_address="situs_addr_line_1_First",
        pin="PIN",
        latitude="INSIDE_Y",
        longitude="INSIDE_X",
        owner_name="taxpayer_name",
    )


register(LakeCounty())
