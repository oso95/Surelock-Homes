"""County property data module registry with auto-discovery."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tools.counties._base import CountyModule

logger = logging.getLogger(__name__)

# Maps (state, county_name_upper) → CountyModule instance
COUNTY_REGISTRY: Dict[Tuple[str, str], CountyModule] = {}


def register(module: CountyModule) -> None:
    """Register a county module instance in the global registry."""
    key = (module.state.upper(), module.county_name.upper())
    COUNTY_REGISTRY[key] = module


def get_county(state: str, county: str) -> Optional[CountyModule]:
    """Look up a registered county module by state and county name."""
    return COUNTY_REGISTRY.get((state.upper(), county.upper()))


def get_counties_for_state(state: str) -> List[CountyModule]:
    """Return all registered county modules for a given state."""
    st = state.upper()
    return [mod for (s, _), mod in COUNTY_REGISTRY.items() if s == st]


def get_county_registry() -> Dict[Tuple[str, str], CountyModule]:
    """Return the full registry dict."""
    return COUNTY_REGISTRY


def _auto_discover() -> None:
    """Import all sibling modules so their register() calls execute."""
    package_dir = Path(__file__).resolve().parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        if info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"tools.counties.{info.name}")
        except Exception:
            logger.warning("Failed to import county module %s", info.name, exc_info=True)


_auto_discover()
