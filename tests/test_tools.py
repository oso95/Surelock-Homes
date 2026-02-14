from tools.providers import search_childcare_providers
from tools.property import get_property_data
from tools.capacity import calculate_max_capacity
from tools.business_reg import check_business_registration
from tools.geocoding import geocode_address


def test_search_childcare_by_zip_mn():
    results = search_childcare_providers(state="MN", zip="55401")
    assert isinstance(results, list)
    assert results[0]["name"] == "Maple Street Family Child Center"


def test_property_lookup_matches_dataset():
    result = get_property_data("100 Birch Ave", state="MN")
    assert result["status"] == "found"
    assert result["building_sqft"] == 1100.0


def test_business_registration_agent_reverse_lookup():
    result = check_business_registration("Michelle Davis", "IL", search_type="agent")
    assert isinstance(result, list)
    assert len(result) >= 2
    assert any(item.get("registered_agent") == "Michelle Davis" for item in result)


def test_geocode_fallback_returns_coordinates():
    result = geocode_address("100 Birch Ave")
    assert result["status"] in {"fallback", "ok", "not_found", "error"}
    assert "lat" in result
    assert "lng" in result

