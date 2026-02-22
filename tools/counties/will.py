"""Will County, IL - property data via ArcGIS Hub FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class WillCounty(ArcGISCountyModule):
    county_name = "Will"
    state = "IL"
    source_label = "live_will"
    fallback_csv = DATA_DIR / "will_parcels.csv"
    arcgis_url = (
        "https://gis.willcountyillinois.com/hosting/rest/services/"
        "Hosted/WillCountyParcels/FeatureServer/0/query"
    )
    field_map = ArcGISFieldMap(
        full_address="SITEADDRESS",
        pin="PIN",
        property_class="PROPCLASS",
        lot_sqft="ACREAGE",
        owner_name="OWNERNAME",
    )


register(WillCounty())
