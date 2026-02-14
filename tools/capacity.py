from __future__ import annotations

def calculate_max_capacity(
    building_sqft: float,
    state: str,
    usable_ratio: float = 0.65,
) -> dict:
    if building_sqft is None:
        raise ValueError("building_sqft is required")
    if state not in {"MN", "IL"}:
        raise ValueError("state must be MN or IL")
    if usable_ratio <= 0:
        raise ValueError("usable_ratio must be greater than zero")

    sqft_per_child = 35
    usable_sqft = float(building_sqft) * float(usable_ratio)
    max_legal_capacity = int(usable_sqft // sqft_per_child)
    regulation = "MN Rules 9503.0155" if state == "MN" else "IL DCFS Part 407"
    return {
        "building_sqft": float(building_sqft),
        "usable_ratio": usable_ratio,
        "usable_sqft": usable_sqft,
        "sqft_per_child_required": sqft_per_child,
        "max_legal_capacity": max_legal_capacity,
        "state": state,
        "regulation": regulation,
        "calculation": f"{building_sqft} * {usable_ratio} = {usable_sqft} usable sqft / {sqft_per_child} = {max_legal_capacity} children max",
    }

