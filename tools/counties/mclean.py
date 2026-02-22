"""McLean County, IL (McGIS) - property data via City of Bloomington ArcGIS MapServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class McLeanCounty(ArcGISCountyModule):
    """McLean County parcel data.

    The public GIS layer lacks site address, building sqft, year built, and
    property class.  Address-based queries will not match; the CSV fallback
    provides the main data source for this county.
    """

    county_name = "McLean"
    state = "IL"
    source_label = "live_mclean"
    fallback_csv = DATA_DIR / "mclean_parcels.csv"
    arcgis_url = (
        "https://gispub.cityblm.org/arcgis/rest/services/"
        "OpenGov/OpenGov_Layers/MapServer/29/query"
    )
    field_map = ArcGISFieldMap(
        pin="PIN",
        lot_sqft="DEED_AC",
    )


register(McLeanCounty())
