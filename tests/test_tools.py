from tools.providers import search_childcare_providers
from tools.property import get_property_data
from tools.capacity import calculate_max_capacity
from tools.business_reg import check_business_registration
from tools.geocoding import geocode_address


def test_search_childcare_by_zip_mn_offline():
    results = search_childcare_providers(state="MN", zip="55401", offline=True)
    assert isinstance(results, list)
    assert results[0]["name"] == "Maple Street Family Child Center"
    assert all(r.get("source") == "fallback" for r in results)


def test_search_childcare_online_no_fixtures(monkeypatch):
    """Online mode must never return fixture data when live fetch and cache both fail."""
    from tools import providers

    # Simulate live fetch failure
    def _fail_mn():
        raise ConnectionError("site unreachable")

    def _fail_il():
        raise ConnectionError("site unreachable")

    monkeypatch.setattr(providers, "_load_mn_live_records", _fail_mn)
    monkeypatch.setattr(providers, "_load_il_live_records", _fail_il)

    # Ensure no stale cache exists for this test
    monkeypatch.setattr(providers, "_load_stale_cache", lambda state_key: [])

    results_mn = search_childcare_providers(state="MN", zip="55401", offline=False)
    results_il = search_childcare_providers(state="IL", zip="60623", offline=False)
    assert results_mn == []
    assert results_il == []


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


# ── Socrata property lookup tests ──


def test_socrata_address_to_pin_parses_address(monkeypatch):
    """_socrata_address_to_pin builds correct query from parsed address."""
    from tools import property as prop_mod

    captured = {}

    def mock_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params

        class MockResp:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"pin": "16272040100000"}]

        return MockResp()

    monkeypatch.setattr(prop_mod.requests, "get", mock_get)
    pin = prop_mod._socrata_address_to_pin("4129 W Cermak Rd")
    assert pin == "16272040100000"
    assert "prop_address_full" in captured["params"]["$where"]


def test_socrata_residential_returns_sqft(monkeypatch):
    """_socrata_residential returns building characteristics from the API response."""
    from tools import property as prop_mod

    def mock_get(url, params=None, timeout=None):
        class MockResp:
            def raise_for_status(self):
                pass

            def json(self):
                return [
                    {
                        "char_bldg_sf": "2234.0",
                        "char_land_sf": "4166.0",
                        "char_yrblt": "1908.0",
                        "class": "211",
                        "char_type_resd": "Single Family",
                    }
                ]

        return MockResp()

    monkeypatch.setattr(prop_mod.requests, "get", mock_get)
    result = prop_mod._socrata_residential("16272040100000")
    assert result["building_sqft"] == 2234.0
    assert result["year_built"] == 1908
    assert result["property_class"] == "211"


def test_socrata_commercial_dashed_pin(monkeypatch):
    """_socrata_commercial converts PIN to dashed format for the commercial dataset."""
    from tools import property as prop_mod

    captured = {}

    def mock_get(url, params=None, timeout=None):
        captured["params"] = params

        class MockResp:
            def raise_for_status(self):
                pass

            def json(self):
                return []

        return MockResp()

    monkeypatch.setattr(prop_mod.requests, "get", mock_get)
    prop_mod._socrata_commercial("16222300200000")
    assert captured["params"]["keypin"] == "16-22-230-020-0000"


def test_socrata_assessed_exempt_property(monkeypatch):
    """_socrata_assessed returns class EX and zero values for exempt properties."""
    from tools import property as prop_mod

    def mock_get(url, params=None, timeout=None):
        class MockResp:
            def raise_for_status(self):
                pass

            def json(self):
                return [
                    {
                        "class": "EX",
                        "mailed_bldg": "0.0",
                        "mailed_land": "0.0",
                        "mailed_tot": "0.0",
                        "township_name": "SOUTH CHICAGO",
                    }
                ]

        return MockResp()

    monkeypatch.setattr(prop_mod.requests, "get", mock_get)
    result = prop_mod._socrata_assessed("16222300200000")
    assert result["property_class"] == "EX"
    assert result["assessed_total"] == 0.0


def test_query_cook_three_tier_fallback(monkeypatch):
    """_query_cook falls through residential → commercial → assessed values."""
    from tools import property as prop_mod

    call_log = []

    def mock_addr(addr):
        call_log.append("addr")
        return "16222300200000"

    def mock_res(pin):
        call_log.append("res")
        return {}  # no residential data

    def mock_com(pin):
        call_log.append("com")
        return {}  # no commercial data

    def mock_assessed(pin):
        call_log.append("assessed")
        return {"property_class": "EX", "assessed_total": 0.0}

    monkeypatch.setattr(prop_mod, "_socrata_address_to_pin", mock_addr)
    monkeypatch.setattr(prop_mod, "_socrata_residential", mock_res)
    monkeypatch.setattr(prop_mod, "_socrata_commercial", mock_com)
    monkeypatch.setattr(prop_mod, "_socrata_assessed", mock_assessed)

    result = prop_mod._query_cook("1512 S Pulaski Rd")
    assert call_log == ["addr", "res", "com", "assessed"]
    assert result["pin"] == "16222300200000"
    assert result["property_class"] == "EX"
    assert result["source_dataset"] == "assessed_values"


def test_get_property_data_cook_live_passes_pin(monkeypatch):
    """get_property_data returns PIN and source_dataset from live Cook query."""
    from tools import property as prop_mod

    def mock_cook(addr):
        return {
            "address": addr,
            "building_sqft": 2234.0,
            "lot_size": "4166",
            "zoning": "",
            "property_class": "211",
            "year_built": 1908,
            "pin": "16272040100000",
            "source_dataset": "residential_characteristics",
        }

    monkeypatch.setattr(prop_mod, "_query_cook", mock_cook)
    result = get_property_data("4129 W Cermak Rd", state="IL")
    assert result["status"] == "found"
    assert result["source"] == "live_cook"
    assert result["pin"] == "16272040100000"
    assert result["source_dataset"] == "residential_characteristics"
    assert result["building_sqft"] == 2234.0


# ── Business registration tests ──


def test_business_reg_not_found_returns_live_probe(monkeypatch):
    """When no CSV match, the probe should report status (blocked or available)."""
    from tools import business_reg as br

    def mock_get(url, timeout=None):
        class MockResp:
            status_code = 403

        return MockResp()

    monkeypatch.setattr(br.requests, "get", mock_get)
    result = check_business_registration("NonExistentBiz123", "IL")
    assert result["status"] == "not_found"
    probe = result.get("live_probe", {})
    assert probe.get("status") == "blocked"
    assert "403" in probe.get("note", "")


# ── Licensing stale cache fallback test ──


def test_licensing_uses_stale_cache_on_live_failure(monkeypatch):
    """licensing.py should fall back to stale cache when DCFS is down."""
    from tools import licensing
    from tools import providers

    def _fail_il():
        raise ConnectionError("DCFS unreachable")

    # Must patch in both modules since licensing imports directly
    monkeypatch.setattr(providers, "_load_il_live_records", _fail_il)
    monkeypatch.setattr(licensing, "_load_il_live_records", _fail_il)

    stale_records = [
        {
            "name": "Test Provider",
            "address": "123 Main St",
            "city": "Chicago",
            "zip": "60623",
            "capacity": "50",
            "license_type": "Child Care Center",
            "status": "Licensed",
            "state": "IL",
        }
    ]
    monkeypatch.setattr(providers, "_load_stale_cache", lambda sk: stale_records if sk == "IL" else [])
    monkeypatch.setattr(licensing, "_load_stale_cache", lambda sk: stale_records if sk == "IL" else [])

    result = licensing.check_licensing_status("Test Provider", "IL")
    assert result["status"] == "found"
    assert result["provider_name"] == "Test Provider"


# ── Radius/miles filtering tests ──


def test_radius_exact_zip_match_default():
    """Default radius (5 miles) should return exact ZIP matches only."""
    results = search_childcare_providers(state="MN", zip="55401", radius_miles=5, offline=True)
    assert all(r.get("zip") == "55401" for r in results)


def test_zip_plus4_matches_base_zip(monkeypatch):
    """ZIP+4 format (e.g. 55454-1208) should match base ZIP 55454."""
    from tools import providers

    records = [
        {"name": "Provider Exact", "address": "1 St", "city": "Minneapolis", "zip": "55454",
         "capacity": 10, "license_type": "CC", "status": "Active", "state": "MN"},
        {"name": "Provider Plus4", "address": "2 St", "city": "Minneapolis", "zip": "55454-1208",
         "capacity": 20, "license_type": "FCC", "status": "Active", "state": "MN"},
        {"name": "Provider Other", "address": "3 St", "city": "Minneapolis", "zip": "55401",
         "capacity": 30, "license_type": "CC", "status": "Active", "state": "MN"},
    ]

    monkeypatch.setattr(providers, "_load_mn_live_records", lambda: records)
    monkeypatch.setattr(providers, "_enrich_mn_with_parentaware", lambda p: p)

    results = search_childcare_providers(state="MN", zip="55454", radius_miles=5, offline=False)
    names = {r["name"] for r in results}
    assert "Provider Exact" in names
    assert "Provider Plus4" in names  # ZIP+4 must match
    assert "Provider Other" not in names


def test_radius_expanded_zip_prefix(monkeypatch):
    """radius_miles > 5 should expand to nearby ZIPs with same 3-digit prefix."""
    from tools import providers

    records = [
        {"name": "Provider A", "address": "1 St", "city": "Chicago", "zip": "60623",
         "capacity": 10, "license_type": "CC", "status": "Active", "state": "IL"},
        {"name": "Provider B", "address": "2 St", "city": "Chicago", "zip": "60608",
         "capacity": 20, "license_type": "CC", "status": "Active", "state": "IL"},
        {"name": "Provider C", "address": "3 St", "city": "Evanston", "zip": "60201",
         "capacity": 30, "license_type": "CC", "status": "Active", "state": "IL"},
    ]

    monkeypatch.setattr(providers, "_load_il_live_records", lambda: records)

    # Radius 5: exact ZIP only
    exact = search_childcare_providers(state="IL", zip="60623", radius_miles=5, offline=False)
    assert len(exact) == 1
    assert exact[0]["name"] == "Provider A"

    # Radius 15: same 3-digit prefix (606xx)
    nearby = search_childcare_providers(state="IL", zip="60623", radius_miles=15, offline=False)
    assert len(nearby) == 2
    names = {r["name"] for r in nearby}
    assert "Provider A" in names
    assert "Provider B" in names
    assert "Provider C" not in names  # 602xx is different prefix


# ── Centralized config tests ──


def test_settings_has_timeout_fields():
    """Settings dataclass should have all centralized timeout fields."""
    from config import load_settings

    s = load_settings()
    assert hasattr(s, "gis_timeout_seconds")
    assert hasattr(s, "google_api_timeout_seconds")
    assert hasattr(s, "socrata_timeout_seconds")
    assert hasattr(s, "probe_timeout_seconds")
    assert hasattr(s, "cache_max_age_hours")
    assert hasattr(s, "rate_limit_max")
    assert hasattr(s, "rate_limit_window")
    assert s.gis_timeout_seconds > 0
    assert s.google_api_timeout_seconds > 0


# ── ParentAware MN enrichment tests ──


def test_mn_provider_enrichment_parentaware(monkeypatch):
    """ParentAware enrichment should populate capacity for MN providers."""
    from tools import providers

    fake_mn_records = [
        {
            "name": "Sunshine Child Care",
            "address": "123 Main St",
            "city": "Minneapolis",
            "zip": "55401",
            "capacity": 0,
            "license_type": "Licensed Family",
            "status": "Active",
            "state": "MN",
            "license_number": "300123",
            "source": "live",
        }
    ]

    def mock_load_mn():
        return fake_mn_records

    monkeypatch.setattr(providers, "_load_mn_live_records", mock_load_mn)

    def mock_parentaware(name):
        return [
            {
                "id": 999,
                "name": "Sunshine Child Care",
                "licenseId": "300123",
                "licensedCapacity": 45,
                "licenseStatus": "Licensed",
                "ageRange": "0-12",
                "acceptsCCAP": True,
            }
        ]

    monkeypatch.setattr(providers, "_query_parentaware_by_name", mock_parentaware)

    results = search_childcare_providers(state="MN", zip="55401", offline=False)
    assert len(results) >= 1
    assert results[0]["capacity"] == 45
    assert results[0].get("license_status") == "Licensed"
    assert results[0].get("age_range") == "0-12"


def test_mn_licensing_live_parentaware(monkeypatch):
    """check_licensing_status should return capacity for MN via ParentAware."""
    from tools import licensing

    def mock_parentaware(name):
        return [
            {
                "name": "New Horizon Academy",
                "licenseId": "400456",
                "licensedCapacity": 139,
                "licenseStatus": "Licensed",
                "licenseType": "Child Care Center",
                "ageRange": "6 weeks - 12 years",
                "acceptsCCAP": True,
            }
        ]

    monkeypatch.setattr(licensing, "_query_parentaware_by_name", mock_parentaware)

    result = licensing.check_licensing_status("New Horizon Academy", state="MN")
    assert result["status"] == "found"
    assert result["capacity"] == 139
    assert result["license_status"] == "Licensed"
    assert result.get("age_range") == "6 weeks - 12 years"


def test_mn_enrichment_failure_graceful(monkeypatch):
    """ParentAware timeout should not crash — capacity stays 0."""
    from tools import providers
    import requests as req_lib

    fake_mn_records = [
        {
            "name": "Timeout Provider",
            "address": "456 Oak St",
            "city": "St Paul",
            "zip": "55101",
            "capacity": 0,
            "license_type": "Licensed Family",
            "status": "Active",
            "state": "MN",
            "license_number": "500789",
            "source": "live",
        }
    ]

    def mock_load_mn():
        return fake_mn_records

    monkeypatch.setattr(providers, "_load_mn_live_records", mock_load_mn)

    def mock_parentaware_timeout(name):
        raise req_lib.exceptions.Timeout("ParentAware timed out")

    monkeypatch.setattr(providers, "_query_parentaware_by_name", mock_parentaware_timeout)

    results = search_childcare_providers(state="MN", zip="55101", offline=False)
    assert len(results) >= 1
    assert results[0]["capacity"] == 0  # stays 0, no crash


def test_mn_enrichment_address_fallback(monkeypatch):
    """When license_number is missing, enrichment should match by address."""
    from tools import providers

    fake_mn_records = [
        {
            "name": "New Horizon Academy",
            "address": "111 Marquette Ave",
            "city": "Minneapolis",
            "zip": "55401",
            "capacity": 0,
            "license_type": "Child Care Center",
            "status": "Active",
            "state": "MN",
            "license_number": "",  # missing — simulates old cache
            "source": "live",
        }
    ]

    def mock_load_mn():
        return fake_mn_records

    monkeypatch.setattr(providers, "_load_mn_live_records", mock_load_mn)

    # Return multiple results (chain provider) — only one matches the address
    def mock_parentaware(name):
        return [
            {
                "name": "New Horizon Academy Conway St Paul",
                "licenseId": "801668",
                "licensedCapacity": 138,
                "licenseStatus": "Active License",
                "address": {"line1": "1385 Conway St", "line2": "Saint Paul, MN 55106"},
            },
            {
                "name": "New Horizon Academy Marquette Minneapolis",
                "licenseId": "801679",
                "licensedCapacity": 139,
                "licenseStatus": "Active License",
                "address": {"line1": "111 Marquette Ave", "line2": "Minneapolis, MN 55401"},
            },
            {
                "name": "New Horizon Academy Roseville",
                "licenseId": "801683",
                "licensedCapacity": 108,
                "licenseStatus": "Active License",
                "address": {"line1": "3050 Centre Pointe Dr Ste 900", "line2": "Roseville, MN 55113"},
            },
        ]

    monkeypatch.setattr(providers, "_query_parentaware_by_name", mock_parentaware)

    results = search_childcare_providers(state="MN", zip="55401", offline=False)
    assert len(results) >= 1
    assert results[0]["capacity"] == 139  # matched by address, not license
    assert results[0].get("license_status") == "Active License"


def test_mn_licensing_address_extraction(monkeypatch):
    """MN licensing lookup should extract line1 from ParentAware nested address."""
    from tools import licensing

    def mock_parentaware(name):
        return [
            {
                "name": "New Horizon Academy Marquette Minneapolis",
                "licenseId": "801679",
                "licensedCapacity": 139,
                "licenseStatus": "Active License",
                "licenseType": "Child Care Center",
                "ageRange": "6 weeks - 12 years",
                "acceptsCCAP": True,
                "address": {"line1": "111 Marquette Ave", "line2": "Minneapolis, MN 55401"},
            }
        ]

    monkeypatch.setattr(licensing, "_query_parentaware_by_name", mock_parentaware)

    result = licensing.check_licensing_status(
        "New Horizon Academy", state="MN", address="111 Marquette Ave"
    )
    assert result["status"] == "found"
    assert result["capacity"] == 139


# ── Address parsing: trailing direction tests ──


def test_parse_address_trailing_direction():
    """_parse_address should extract trailing direction after suffix."""
    from tools.property import _parse_address

    parsed = _parse_address("404 Cedar Ave S")
    assert parsed["house"] == "404"
    assert parsed["street"] == "CEDAR"
    assert parsed["suffix"] == "AVE"
    assert parsed["direction"] == "S"


def test_parse_address_leading_direction_unchanged():
    """_parse_address should still handle leading direction correctly."""
    from tools.property import _parse_address

    parsed = _parse_address("1512 S Pulaski Rd")
    assert parsed["house"] == "1512"
    assert parsed["direction"] == "S"
    assert parsed["street"] == "PULASKI"
    assert parsed["suffix"] == "RD"


def test_parse_address_no_direction():
    """_parse_address without any direction should return empty direction."""
    from tools.property import _parse_address

    parsed = _parse_address("100 Birch Ave")
    assert parsed["house"] == "100"
    assert parsed["street"] == "BIRCH"
    assert parsed["suffix"] == "AVE"
    assert parsed["direction"] == ""


def test_hennepin_suffix_query_uses_wildcard(monkeypatch):
    """_query_hennepin should use LIKE '% AVE%' (not '% AVE') for suffix filter."""
    from tools import property as prop_mod

    captured = {}

    def mock_get(url, params=None, timeout=None):
        captured["params"] = params

        class MockResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"features": []}

        return MockResp()

    monkeypatch.setattr(prop_mod.requests, "get", mock_get)
    prop_mod._query_hennepin("404 Cedar Ave S")
    where = captured["params"]["where"]
    assert "LIKE '% AVE%'" in where  # wildcard after suffix
    assert "LIKE '% AVE'" not in where  # NOT exact ending


# ── Turn budget in system prompt test ──


def test_system_prompt_includes_turn_budget():
    """load_system_prompt should inject turn budget when max_turns is provided."""
    from agent.prompt import load_system_prompt

    prompt_with = load_system_prompt(target_state="MN", target_zip="55401", max_turns=25)
    assert "TURN BUDGET" in prompt_with
    assert "25 turns" in prompt_with
    assert "23" in prompt_with  # 25 - 2 reserved for report

    prompt_without = load_system_prompt(target_state="MN", target_zip="55401")
    assert "TURN BUDGET" not in prompt_without


# ── Continuation nudge: report-already-written detection ──


def test_nudge_suppressed_after_report_with_good_coverage():
    """_continuation_nudge returns None if report written AND coverage is sufficient."""
    from agent.loop import _continuation_nudge

    providers = [{"name": f"P{i}", "address": f"{i} St"} for i in range(50)]
    # Simulate investigating 40 out of 50 (80% coverage — sufficient)
    tool_calls = [
        {"tool": "search_childcare_providers", "arguments": {}, "status": "ok", "result": providers},
    ]
    for i in range(40):
        tool_calls.append({"tool": "get_property_data", "arguments": {"address": f"{i} St"}, "status": "ok", "result": {}})

    report_text = [
        "INVESTIGATION REPORT\n\nPROVIDER DOSSIERS\n\nPATTERN ANALYSIS\n\n"
        "EXPOSURE ESTIMATE\n\nCONFIDENCE CALIBRATION\n\nInvestigation complete."
    ]
    nudge = _continuation_nudge(tool_calls, 10, 25, assistant_text=report_text)
    assert nudge is None  # good coverage + report → stop cleanly


def test_nudge_continues_after_premature_report():
    """_continuation_nudge tells agent to continue if report written but coverage is poor."""
    from agent.loop import _continuation_nudge

    providers = [{"name": f"P{i}", "address": f"{i} St"} for i in range(50)]
    # Only 5 out of 50 investigated (10% coverage — poor)
    tool_calls = [
        {"tool": "search_childcare_providers", "arguments": {}, "status": "ok", "result": providers},
        {"tool": "get_property_data", "arguments": {"address": "1 St"}, "status": "ok", "result": {}},
    ]

    report_text = [
        "INVESTIGATION REPORT\n\nPROVIDER DOSSIERS\n\nPATTERN ANALYSIS\n\n"
        "EXPOSURE ESTIMATE\n\nCONFIDENCE CALIBRATION\n\nInvestigation complete."
    ]
    nudge = _continuation_nudge(tool_calls, 5, 25, assistant_text=report_text)
    assert nudge is not None
    assert "only investigated 1 out of 50" in nudge
    assert "ADDENDUM" in nudge


def test_nudge_without_report_shows_progress():
    """_continuation_nudge shows progress when no report written and coverage is low."""
    from agent.loop import _continuation_nudge

    providers = [{"name": f"P{i}", "address": f"{i} St"} for i in range(50)]
    tool_calls = [
        {"tool": "search_childcare_providers", "arguments": {}, "status": "ok", "result": providers},
        {"tool": "get_property_data", "arguments": {"address": "1 St"}, "status": "ok", "result": {}},
    ]

    nudge = _continuation_nudge(tool_calls, 5, 25, assistant_text=["Let me investigate..."])
    assert nudge is not None
    assert "1 out of 50" in nudge
    assert "20 turns remaining" in nudge
    assert "DO NOT write the final report" in nudge
