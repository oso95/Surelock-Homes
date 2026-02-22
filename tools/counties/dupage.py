"""DuPage County, IL - property data via ArcGIS MapServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class DuPageCounty(ArcGISCountyModule):
    county_name = "DuPage"
    state = "IL"
    source_label = "live_dupage"
    fallback_csv = DATA_DIR / "dupage_parcels.csv"
    arcgis_url = (
        "https://gis.dupageco.org/arcgis/rest/services/"
        "ParcelSearch/DuPageAssessmentParcelViewer/MapServer/4/query"
    )
    field_map = ArcGISFieldMap(
        address_number="PROPSTNUM",
        street_name="PROPSTNAME",
        street_direction="PROPSTDIR",
        property_class="PROPCLASS",
        lot_sqft="ACREAGE",
        pin="PIN",
    )


register(DuPageCounty())
