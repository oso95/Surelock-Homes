"""Kankakee County, IL - property data via K3GIS ArcGIS MapServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class KankakeeCounty(ArcGISCountyModule):
    county_name = "Kankakee"
    state = "IL"
    source_label = "live_kankakee"
    fallback_csv = DATA_DIR / "kankakee_parcels.csv"
    arcgis_url = (
        "https://k3gis.com/arcgis/rest/services/Cadastral/"
        "Tax_Parcels_and_Subdivisions_Tax_Year_2024/MapServer/0/query"
    )
    field_map = ArcGISFieldMap(
        full_address="site_address",
        pin="pin",
        property_class="use_code",
        lot_sqft="gross_acres",
        owner_name="owner1_name",
        latitude="latitude",
        longitude="longitude",
    )


register(KankakeeCounty())
