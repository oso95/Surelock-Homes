"""Comprehensive tests for the county property data module plugin system."""
from __future__ import annotations

import pytest

from tools.counties import get_county, get_county_registry, get_counties_for_state
from tools.counties._base import ArcGISCountyModule, ArcGISFieldMap, CountyModule
from tools.counties._zip_routing import IL_ZIP_TO_COUNTY, resolve_county_from_zip


# ── Auto-discovery tests ──


def test_registry_contains_all_il_counties():
    """All 14 IL counties should be registered (Cook + 13 new)."""
    registry = get_county_registry()
    expected_il = {
        "COOK", "DUPAGE", "LAKE", "WILL", "KANE", "MCHENRY", "KENDALL",
        "WINNEBAGO", "CHAMPAIGN", "SANGAMON", "PEORIA", "MCLEAN",
        "KANKAKEE", "DEKALB",
    }
    actual_il = {county for (state, county) in registry if state == "IL"}
    assert expected_il == actual_il


def test_registry_contains_hennepin():
    """Hennepin County (MN) should be registered."""
    mod = get_county("MN", "Hennepin")
    assert mod is not None
    assert mod.county_name == "Hennepin"
    assert mod.state == "MN"


def test_get_counties_for_state_il():
    """get_counties_for_state('IL') should return all 14 IL counties."""
    il_counties = get_counties_for_state("IL")
    assert len(il_counties) == 14
    names = {m.county_name for m in il_counties}
    assert "Cook" in names
    assert "DuPage" in names
    assert "DeKalb" in names


def test_get_county_case_insensitive():
    """get_county lookup should be case-insensitive."""
    assert get_county("il", "dupage") is not None
    assert get_county("IL", "DuPage") is not None
    assert get_county("IL", "DUPAGE") is not None


def test_get_county_unknown_returns_none():
    """Unknown county should return None."""
    assert get_county("IL", "Atlantis") is None
    assert get_county("XX", "Nowhere") is None


# ── CountyModule interface tests ──


def test_all_modules_have_required_attributes():
    """Every registered module should have county_name, state, source_label, fallback_csv."""
    for (state, county), mod in get_county_registry().items():
        assert mod.county_name, f"Missing county_name for {state}/{county}"
        assert mod.state, f"Missing state for {state}/{county}"
        assert mod.source_label, f"Missing source_label for {state}/{county}"
        assert mod.fallback_csv is not None, f"Missing fallback_csv for {state}/{county}"


def test_all_arcgis_modules_have_url():
    """ArcGIS-based modules should have a non-empty arcgis_url."""
    for (state, county), mod in get_county_registry().items():
        if isinstance(mod, ArcGISCountyModule):
            assert mod.arcgis_url, f"Missing arcgis_url for {state}/{county}"
            assert mod.arcgis_url.startswith("https://"), (
                f"arcgis_url should use HTTPS for {state}/{county}"
            )


# ── ZIP routing tests ──


_ZIP_COUNTY_SAMPLES = [
    ("60601", "Cook"),
    ("60623", "Cook"),
    ("60515", "DuPage"),
    ("60187", "DuPage"),
    ("60045", "Lake"),
    ("60085", "Lake"),
    ("60435", "Will"),
    ("60490", "Will"),
    ("60120", "Kane"),
    ("60506", "Kane"),
    ("60014", "McHenry"),
    ("60098", "McHenry"),
    ("60543", "Kendall"),
    ("60560", "Kendall"),
    ("61101", "Winnebago"),
    ("61114", "Winnebago"),
    ("61820", "Champaign"),
    ("61802", "Champaign"),
    ("62702", "Sangamon"),
    ("62704", "Sangamon"),
    ("61602", "Peoria"),
    ("61614", "Peoria"),
    ("61701", "McLean"),
    ("61761", "McLean"),
    ("60901", "Kankakee"),
    ("60914", "Kankakee"),
    ("60115", "DeKalb"),
    ("60178", "DeKalb"),
]


@pytest.mark.parametrize("zip_code,expected_county", _ZIP_COUNTY_SAMPLES)
def test_zip_routes_to_correct_county(zip_code, expected_county):
    """Each ZIP code should route to the correct county."""
    result = resolve_county_from_zip(zip_code)
    assert result == expected_county, f"ZIP {zip_code} -> {result}, expected {expected_county}"


def test_zip_routing_unknown_zip():
    """Unknown ZIP should return None."""
    assert resolve_county_from_zip("99999") is None
    assert resolve_county_from_zip("") is None
    assert resolve_county_from_zip(None) is None


def test_zip_routing_all_counties_covered():
    """Every IL county in the registry should have at least one ZIP mapping."""
    il_counties = {m.county_name for m in get_counties_for_state("IL")}
    counties_with_zips = set(IL_ZIP_TO_COUNTY.values())
    assert il_counties <= counties_with_zips, (
        f"Counties missing ZIP coverage: {il_counties - counties_with_zips}"
    )


# ── Fallback CSV tests ──


@pytest.mark.parametrize("state,county", [
    ("IL", "DuPage"), ("IL", "Lake"), ("IL", "Will"), ("IL", "Kane"),
    ("IL", "McHenry"), ("IL", "Kendall"), ("IL", "Winnebago"),
    ("IL", "Champaign"), ("IL", "Sangamon"), ("IL", "Peoria"),
    ("IL", "McLean"), ("IL", "Kankakee"), ("IL", "DeKalb"),
])
def test_fallback_csv_exists(state, county):
    """Each new county should have a fallback CSV file."""
    mod = get_county(state, county)
    assert mod is not None
    assert mod.fallback_csv.exists(), f"Missing CSV: {mod.fallback_csv}"


@pytest.mark.parametrize("state,county", [
    ("IL", "DuPage"), ("IL", "Lake"), ("IL", "Will"), ("IL", "Kane"),
    ("IL", "McHenry"), ("IL", "Kendall"), ("IL", "Winnebago"),
    ("IL", "Champaign"), ("IL", "Sangamon"), ("IL", "Peoria"),
    ("IL", "McLean"), ("IL", "Kankakee"), ("IL", "DeKalb"),
])
def test_fallback_csv_has_required_columns(state, county):
    """Each fallback CSV should have the standard column headers."""
    import csv
    mod = get_county(state, county)
    with mod.fallback_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    required = {"address", "state", "county", "building_sqft", "lot_size", "property_class", "year_built"}
    assert required <= set(headers), f"Missing columns in {mod.fallback_csv.name}: {required - set(headers)}"


@pytest.mark.parametrize("state,county", [
    ("IL", "DuPage"), ("IL", "Lake"), ("IL", "Will"), ("IL", "Kane"),
    ("IL", "McHenry"), ("IL", "Kendall"), ("IL", "Winnebago"),
    ("IL", "Champaign"), ("IL", "Sangamon"), ("IL", "Peoria"),
    ("IL", "McLean"), ("IL", "Kankakee"), ("IL", "DeKalb"),
])
def test_fallback_csv_has_rows(state, county):
    """Each fallback CSV should have at least one data row."""
    import csv
    mod = get_county(state, county)
    with mod.fallback_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) >= 1, f"Empty CSV: {mod.fallback_csv.name}"
    for row in rows:
        assert row.get("county") == county
        assert row.get("state") == state


# ── ArcGIS query construction tests ──


def test_dupage_where_clause():
    """DuPage should build WHERE with PROPSTNUM and PROPSTNAME."""
    mod = get_county("IL", "DuPage")
    parsed = {"house": "421", "street": "COUNTY FARM", "direction": "N", "suffix": "RD"}
    where = mod._build_where(parsed)
    assert "PROPSTNUM='421'" in where
    assert "PROPSTNAME" in where
    assert "COUNTY FARM" in where
    assert "PROPSTDIR" in where


def test_kendall_where_clause_uses_full_address():
    """Kendall should build WHERE using the full_address field."""
    mod = get_county("IL", "Kendall")
    parsed = {"house": "111", "street": "FOX", "direction": "W", "suffix": "ST"}
    where = mod._build_where(parsed)
    assert "site_address" in where
    assert "111" in where
    assert "FOX" in where


def test_dekalb_where_clause_uses_full_address():
    """DeKalb uses SITEADDRESS full_address field in WHERE clause."""
    mod = get_county("IL", "DeKalb")
    parsed = {"house": "200", "street": "1ST", "suffix": "ST"}
    where = mod._build_where(parsed)
    assert "SITEADDRESS" in where
    assert "200" in where
    assert "1ST" in where


def test_lake_where_clause_uses_full_address():
    """Lake County uses situs_addr_line_1_First as full address field."""
    mod = get_county("IL", "Lake")
    parsed = {"house": "500", "street": "GRAND", "suffix": "AVE"}
    where = mod._build_where(parsed)
    assert "situs_addr_line_1_First" in where
    assert "500" in where


def test_winnebago_where_clause_uses_address_components():
    """Winnebago should use STNO and STNAME for WHERE clause."""
    mod = get_county("IL", "Winnebago")
    parsed = {"house": "401", "street": "MAIN", "direction": "W", "suffix": "ST"}
    where = mod._build_where(parsed)
    assert "STNO='401'" in where
    assert "STNAME" in where
    assert "MAIN" in where
    assert "PREFIX" in where


def test_sangamon_where_clause_uses_qualified_fields():
    """Sangamon should use fully-qualified field names in WHERE clause."""
    mod = get_county("IL", "Sangamon")
    parsed = {"house": "300", "street": "SOUTH GRAND", "direction": "S", "suffix": "AVE"}
    where = mod._build_where(parsed)
    assert "PropHouseNo" in where
    assert "300" in where
    assert "PropStreet" in where
    assert "SOUTH GRAND" in where


def test_peoria_where_clause_uses_prop_street():
    """Peoria should use prop_street (full_address) for WHERE clause."""
    mod = get_county("IL", "Peoria")
    parsed = {"house": "123", "street": "ADAMS", "suffix": "ST"}
    where = mod._build_where(parsed)
    assert "prop_street" in where
    assert "123" in where
    assert "ADAMS" in where


# ── Mock ArcGIS response tests ──


def _make_mock_arcgis_response(features):
    """Helper: create a mock requests.get that returns an ArcGIS JSON response."""
    class MockResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"features": features}

    def mock_get(url, params=None, headers=None, timeout=None):
        return MockResp()

    return mock_get


def test_dupage_query_parses_response(monkeypatch):
    """DuPage module should extract fields from a mock ArcGIS response."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "PROPSTNUM": "421",
            "PROPSTDIR": "N",
            "PROPSTNAME": "COUNTY FARM",
            "PROPCLASS": "C1",
            "ACREAGE": 0.124,
            "PIN": "01-23-456-789",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    mod = get_county("IL", "DuPage")
    result = mod.query("421 N County Farm Rd")
    assert result["pin"] == "01-23-456-789"
    assert result["property_class"] == "C1"
    assert "421" in result["address"]


def test_kendall_query_parses_response(monkeypatch):
    """Kendall module should extract fields from a mock ArcGIS response."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "site_address": "111 W FOX ST",
            "pin": "02-01-200-010",
            "class": "200",
            "gross_acres": 0.11,
            "owner_name": "KENDALL LLC",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    mod = get_county("IL", "Kendall")
    result = mod.query("111 W Fox St")
    assert result["pin"] == "02-01-200-010"
    assert result["property_class"] == "200"
    assert result["owner_name"] == "KENDALL LLC"


def test_dekalb_query_parses_response(monkeypatch):
    """DeKalb module should extract fields from a mock ArcGIS response."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "ADDRESS_NUMBER": "200",
            "FULL_STREET_NAME": "N 1ST ST",
            "SITEADDRESS": "200 N 1ST ST",
            "PARCELID": "08-12-345-678",
            "CLASSCD": "100",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    mod = get_county("IL", "DeKalb")
    result = mod.query("200 N 1st St")
    assert result["pin"] == "08-12-345-678"
    assert result["property_class"] == "100"


def test_winnebago_query_parses_response(monkeypatch):
    """Winnebago module should extract address components from response."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "STNO": "401",
            "PREFIX": "W",
            "STNAME": "STATE",
            "SUFFIX": "ST",
            "PIN": "11-01-200-003",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    mod = get_county("IL", "Winnebago")
    result = mod.query("401 W State St")
    assert result["pin"] == "11-01-200-003"
    assert "401" in result["address"]
    assert "STATE" in result["address"]


def test_sangamon_query_parses_response(monkeypatch):
    """Sangamon module should extract fields using qualified field names."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "SOA.SANGIS.Reg_ptinfo.PropHouseNo": 300,
            "SOA.SANGIS.Reg_ptinfo.PropDir": "S",
            "SOA.SANGIS.Reg_ptinfo.PropStreet": "GRAND AVE",
            "SOA.SANGIS.Parcel_Poly.PIN": "14-29.0-100-001",
            "SOA.SANGIS.Reg_ptinfo.ClassCode": "200",
            "SOA.SANGIS.Parcel_Poly.TOTACRES": 0.25,
            "SOA.SANGIS.Reg_ptinfo.Owner1": "SANGAMON LLC",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    mod = get_county("IL", "Sangamon")
    result = mod.query("300 S Grand Ave")
    assert result["pin"] == "14-29.0-100-001"
    assert result["property_class"] == "200"
    assert result["owner_name"] == "SANGAMON LLC"
    assert "300" in result["address"]


def test_peoria_query_parses_response_with_sqft_and_year(monkeypatch):
    """Peoria module should extract building sqft and year_built from response."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "prop_street": "123 ADAMS ST",
            "total_living_area": 1850,
            "Acres": 0.15,
            "year_built": 1965,
            "PropClass": "RESIDENTIAL",
            "PIN": "18-07-300-002",
            "owner_name": "PEORIA HOMES INC",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    mod = get_county("IL", "Peoria")
    result = mod.query("123 Adams St")
    assert result["pin"] == "18-07-300-002"
    assert result["building_sqft"] == 1850.0
    assert result["year_built"] == 1965
    assert result["property_class"] == "RESIDENTIAL"
    assert result["owner_name"] == "PEORIA HOMES INC"


def test_kankakee_query_parses_response_with_lat_lon(monkeypatch):
    """Kankakee module should extract latitude/longitude from response."""
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "site_address": "189 E COURT ST",
            "pin": "16-05-100-001",
            "use_code": "200",
            "gross_acres": 0.11,
            "owner1_name": "SMITH JOHN",
            "latitude": 41.1137,
            "longitude": -87.8612,
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))
    # Prevent actual OSM call since building_sqft is 0 and lat/lon present
    monkeypatch.setattr(base_mod, "_estimate_sqft_from_osm", lambda lat, lon: {
        "building_sqft": 2200.0, "building_sqft_source": "osm_footprint",
        "building_sqft_confidence": "moderate",
    })

    mod = get_county("IL", "Kankakee")
    result = mod.query("189 E Court St")
    assert result["latitude"] == 41.1137
    assert result["longitude"] == -87.8612
    assert result["building_sqft"] == 2200.0
    assert result["building_sqft_source"] == "osm_footprint"


# ── No-match and error handling tests ──


@pytest.mark.parametrize("state,county", [
    ("IL", "DuPage"), ("IL", "Lake"), ("IL", "Kane"), ("IL", "Kendall"),
    ("IL", "Kankakee"), ("IL", "DeKalb"),
])
def test_no_match_returns_empty_dict(monkeypatch, state, county):
    """When ArcGIS returns no features, query() should return {}."""
    import tools.counties._base as base_mod
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response([]))

    mod = get_county(state, county)
    result = mod.query("99999 Nonexistent Blvd")
    assert result == {}


@pytest.mark.parametrize("state,county", [
    ("IL", "DuPage"), ("IL", "Lake"), ("IL", "Kankakee"),
])
def test_timeout_raises_for_caller_to_handle(monkeypatch, state, county):
    """Network timeout should propagate so get_property_data can fall back to CSV."""
    import tools.counties._base as base_mod
    import requests as req_lib

    def mock_timeout(url, params=None, headers=None, timeout=None):
        raise req_lib.exceptions.Timeout("Connection timed out")

    monkeypatch.setattr(base_mod.requests, "get", mock_timeout)

    mod = get_county(state, county)
    with pytest.raises(req_lib.exceptions.Timeout):
        mod.query("421 N County Farm Rd")


# ── Integration: get_property_data county dispatch ──


def test_property_data_dispatches_to_dupage(monkeypatch):
    """get_property_data should dispatch DuPage ZIPs to the DuPage county module."""
    from tools import property as prop_mod
    import tools.counties._base as base_mod

    features = [{
        "attributes": {
            "PROPSTNUM": "421",
            "PROPSTDIR": "N",
            "PROPSTNAME": "COUNTY FARM",
            "PROPCLASS": "C1",
            "ACREAGE": 0.124,
            "PIN": "01-23-456-789",
        }
    }]
    monkeypatch.setattr(base_mod.requests, "get", _make_mock_arcgis_response(features))

    result = prop_mod.get_property_data("421 N County Farm Rd 60515", state="IL")
    assert result["status"] == "found"
    assert result["source"] == "live_dupage"
    assert result["county"] == "DuPage"
    assert result["pin"] == "01-23-456-789"


def test_property_data_falls_through_to_cook_without_zip(monkeypatch):
    """Without a ZIP, IL addresses should fall through to Cook (legacy dispatch)."""
    from tools import property as prop_mod

    def mock_cook(addr):
        return {
            "address": addr,
            "building_sqft": 1500.0,
            "lot_size": "3000",
            "zoning": "",
            "property_class": "211",
            "year_built": 1950,
            "pin": "1234567890",
            "source_dataset": "residential_characteristics",
        }

    monkeypatch.setattr(prop_mod, "_query_cook", mock_cook)
    result = prop_mod.get_property_data("100 Main St", state="IL")
    assert result["status"] == "found"
    assert result["source"] == "live_cook"


def test_property_data_county_fallback_csv(monkeypatch):
    """County module failure should fall back to county-specific CSV."""
    from tools import property as prop_mod
    import tools.counties._base as base_mod
    import requests as req_lib

    def mock_timeout(url, params=None, headers=None, timeout=None):
        raise req_lib.exceptions.Timeout("timeout")

    monkeypatch.setattr(base_mod.requests, "get", mock_timeout)

    result = prop_mod.get_property_data("421 N County Farm Rd 60515", state="IL")
    assert result["status"] == "found"
    assert result["source"] == "dupage_parcels.csv.fallback"
    assert result.get("live_fallback") is True


def test_property_data_offline_uses_csv():
    """Offline mode should bypass live queries and use CSV fallback."""
    from tools import property as prop_mod

    result = prop_mod.get_property_data("421 N County Farm Rd", county="DuPage", state="IL", offline=True)
    assert result["status"] == "found"
    assert result["source"] == "dupage_parcels.csv"


# ── Definitions auto-generation test ──


def test_definitions_include_county_list():
    """get_property_data tool description should list available counties."""
    from tools.definitions import get_tool_definitions

    defs = {d["name"]: d for d in get_tool_definitions()}
    desc = defs["get_property_data"]["description"]
    assert "DuPage" in desc or "Dupage" in desc
    assert "Cook" in desc
    assert "DeKalb" in desc or "Dekalb" in desc


# ── ArcGISFieldMap dataclass tests ──


def test_field_map_default_empty():
    """Default ArcGISFieldMap should have all empty strings."""
    fm = ArcGISFieldMap()
    assert fm.address_number == ""
    assert fm.building_sqft == ""
    assert fm.pin == ""


def test_field_map_custom():
    """ArcGISFieldMap should accept custom field names."""
    fm = ArcGISFieldMap(address_number="HOUSE_NO", pin="PARCEL_ID")
    assert fm.address_number == "HOUSE_NO"
    assert fm.pin == "PARCEL_ID"
