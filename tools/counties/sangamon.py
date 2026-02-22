"""Sangamon County, IL - property data via SangCadastral ArcGIS MapServer."""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class SangamonCounty(ArcGISCountyModule):
    county_name = "Sangamon"
    state = "IL"
    source_label = "live_sangamon"
    fallback_csv = DATA_DIR / "sangamon_parcels.csv"
    arcgis_url = (
        "https://sangis.co.sangamon.il.us/server/rest/services/"
        "SangCadastral/MapServer/3/query"
    )
    field_map = ArcGISFieldMap(
        address_number="SOA.SANGIS.Reg_ptinfo.PropHouseNo",
        street_direction="SOA.SANGIS.Reg_ptinfo.PropDir",
        street_name="SOA.SANGIS.Reg_ptinfo.PropStreet",
        pin="SOA.SANGIS.Parcel_Poly.PIN",
        property_class="SOA.SANGIS.Reg_ptinfo.ClassCode",
        lot_sqft="SOA.SANGIS.Parcel_Poly.TOTACRES",
        owner_name="SOA.SANGIS.Reg_ptinfo.Owner1",
    )


register(SangamonCounty())
