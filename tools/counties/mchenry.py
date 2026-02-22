"""McHenry County, IL - property data via ArcGIS Open Data FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class McHenryCounty(ArcGISCountyModule):
    county_name = "McHenry"
    state = "IL"
    source_label = "live_mchenry"
    fallback_csv = DATA_DIR / "mchenry_parcels.csv"
    arcgis_url = (
        "https://services1.arcgis.com/8BKBZ0vTlaNfJPyh/arcgis/rest/services/"
        "McHenryCountyParcels/FeatureServer/0/query"
    )
    field_map = ArcGISFieldMap(
        full_address="SITEADDRESS",
        pin="PIN",
        property_class="PROPCLASS",
        lot_sqft="ACREAGE",
        owner_name="OWNERNAME",
    )


register(McHenryCounty())
