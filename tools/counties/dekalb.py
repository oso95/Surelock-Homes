"""DeKalb County, IL - property data via ArcGIS Online FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class DeKalbCounty(ArcGISCountyModule):
    county_name = "DeKalb"
    state = "IL"
    source_label = "live_dekalb"
    fallback_csv = DATA_DIR / "dekalb_parcels.csv"
    arcgis_url = (
        "https://services2.arcgis.com/IxVN2oUE9EYLSnPE/arcgis/rest/services/"
        "Tax_Parcels2/FeatureServer/0/query"
    )
    field_map = ArcGISFieldMap(
        address_number="ADDRESS_NUMBER",
        street_name="FULL_STREET_NAME",
        full_address="SITEADDRESS",
        pin="PARCELID",
        property_class="CLASSCD",
        owner_name="OWNERNME1",
    )


register(DeKalbCounty())
