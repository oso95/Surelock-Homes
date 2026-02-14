from tools.capacity import calculate_max_capacity


def test_calculate_mn_capacity_formula():
    result = calculate_max_capacity(1100, "MN")
    assert result["max_legal_capacity"] == 20
    assert result["regulation"] == "MN Rules 9503.0155"
    assert result["building_sqft"] == 1100.0


def test_calculate_il_custom_ratio():
    result = calculate_max_capacity(1000, "IL", usable_ratio=0.7)
    assert result["state"] == "IL"
    assert result["max_legal_capacity"] == 20
    assert result["regulation"] == "IL DCFS Part 407"

