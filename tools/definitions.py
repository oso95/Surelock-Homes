from __future__ import annotations

from tools.providers import PROVIDER_REGISTRY
from tools.licensing import LICENSING_REGISTRY
from tools.capacity import CAPACITY_REGISTRY


def get_tool_definitions():
    provider_states = sorted(PROVIDER_REGISTRY.keys())
    licensing_states = sorted(LICENSING_REGISTRY.keys())
    capacity_states = sorted(CAPACITY_REGISTRY.keys())

    return [
        {
            "name": "search_childcare_providers",
            "description": "Search for licensed childcare providers in a target area. Returns all providers with their name, address, licensed capacity, license type, and license status.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "state": {"type": "string", "enum": provider_states},
                    "zip": {"type": "string", "description": "5-digit ZIP code"},
                    "radius_miles": {"type": "number", "default": 5},
                },
                "required": ["state"],
            },
        },
        {
            "name": "get_property_data",
            "description": "Get building and parcel data for a specific address from county GIS records. Returns building square footage, lot size, zoning classification, property class, and year built.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "Full street address"},
                    "county": {"type": "string", "description": "County name (optional, helps with lookup)"},
                    "state": {"type": "string"},
                },
                "required": ["address", "state"],
            },
        },
        {
            "name": "get_street_view",
            "description": "Capture Google Street View images of a location from multiple angles. Returns JPEG images that can be analyzed visually.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "headings": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 360},
                        "default": [0, 90, 180, 270],
                        "description": "Camera headings in degrees (0=north, 90=east)",
                    },
                    "size": {"type": "string", "default": "640x480"},
                },
                "required": ["address"],
            },
        },
        {
            "name": "get_places_info",
            "description": "Get Google Places data for an address. Returns current business type, operating status, rating, review count, and recent reviews if available.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "name": {"type": "string", "description": "Business or provider name to search for (improves match accuracy)"},
                },
                "required": ["address"],
            },
        },
        {
            "name": "check_licensing_status",
            "description": "Look up detailed licensing information for a childcare provider from state DHS records. Returns license dates, capacity, violation history, conditions, and inspection records.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "provider_name": {"type": "string"},
                    "state": {"type": "string", "enum": licensing_states},
                    "address": {"type": "string", "description": "For disambiguation if multiple matches"},
                },
                "required": ["provider_name", "state"],
            },
        },
        {
            "name": "check_business_registration",
            "description": "Look up business entity registration with Secretary of State. Returns incorporation date, registered agent name, entity type, status, and registered address. Can also search by agent name to find all entities associated with a person.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Business name OR person name (for agent search)"},
                    "state": {"type": "string"},
                    "search_type": {
                        "type": "string",
                        "enum": ["business", "agent"],
                        "default": "business",
                        "description": "Search by business name or by registered agent name",
                    },
                },
                "required": ["name", "state"],
            },
        },
        {
            "name": "calculate_max_capacity",
            "description": "Calculate the maximum legal childcare capacity for a building based on square footage and state building code requirements. Shows full calculation.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "building_sqft": {"type": "number"},
                    "state": {"type": "string", "enum": capacity_states},
                    "usable_ratio": {
                        "type": "number",
                        "default": 0.65,
                        "description": "Estimated ratio of usable childcare space to total building sqft",
                    },
                },
                "required": ["building_sqft", "state"],
            },
        },
        {
            "name": "geocode_address",
            "description": "Validate and standardize an address. Returns coordinates, formatted address, and whether the address is valid.",
            "input_schema": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]},
        },
    ]
