"""Kane County, IL - property data via ArcGIS Online FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class KaneCounty(ArcGISCountyModule):
    county_name = "Kane"
    state = "IL"
    source_label = "live_kane"
    fallback_csv = DATA_DIR / "kane_parcels.csv"
    arcgis_url = (
        "https://services9.arcgis.com/GWGikmQqMfXmMkKr/arcgis/rest/services/"
        "KaneCountyParcels/FeatureServer/0/query"
    )
    field_map = ArcGISFieldMap(
        full_address="SITEADDRESS",
        pin="PIN",
        property_class="PROPCLASS",
        lot_sqft="ACREAGE",
        owner_name="OWNERNAME",
    )


register(KaneCounty())
