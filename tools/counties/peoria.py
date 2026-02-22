"""Peoria County, IL - property data via ArcGIS FeatureServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class PeoriaCounty(ArcGISCountyModule):
    county_name = "Peoria"
    state = "IL"
    source_label = "live_peoria"
    fallback_csv = DATA_DIR / "peoria_parcels.csv"
    arcgis_url = (
        "https://gis.peoriacounty.gov/arcgis/rest/services/"
        "DP/Cadastral/FeatureServer/1/query"
    )
    field_map = ArcGISFieldMap(
        full_address="prop_street",
        building_sqft="total_living_area",
        lot_sqft="Acres",
        year_built="year_built",
        property_class="PropClass",
        pin="PIN",
        owner_name="owner_name",
    )


register(PeoriaCounty())
