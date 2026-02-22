"""Champaign County, IL - property data via CCGISC ArcGIS Portal sharing proxy.

The CCGISC ArcGIS Server requires authentication for direct REST access.
The public web map viewer at maps.ccgisc.org uses a portal sharing proxy
that accepts requests with the appropriate Referer header.

The parcel layer lacks site address and building sqft fields; address-based
queries are limited and the CSV fallback provides the primary data source.
"""
from __future__ import annotations

from typing import Any, Dict

from config import DATA_DIR
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap
from tools.counties import register


class ChampaignCounty(ArcGISCountyModule):
    county_name = "Champaign"
    state = "IL"
    source_label = "live_champaign"
    fallback_csv = DATA_DIR / "champaign_parcels.csv"
    arcgis_url = (
        "https://services.ccgisc.org/portal/sharing/servers/"
        "6f68b33636234c19aeb0601dbc50d9fa/rest/services/"
        "General/Pop_Ups/MapServer/1/query"
    )
    _request_headers = {"Referer": "https://www.maps.ccgisc.org/"}
    field_map = ArcGISFieldMap(
        pin="PIN",
        property_class="PropertyUseCode",
        lot_sqft="Acreage",
        owner_name="TaxPayer_Name",
    )


register(ChampaignCounty())
