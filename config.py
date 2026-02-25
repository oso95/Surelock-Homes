from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
SCRIPTS_DIR = ROOT_DIR / "scripts"
OUTPUT_DIR = ROOT_DIR / "output"
FRONTEND_DIR = ROOT_DIR / "frontend"

for path in (DATA_DIR, SCRIPTS_DIR, OUTPUT_DIR, FRONTEND_DIR):
    path.mkdir(exist_ok=True)

_env_path = ROOT_DIR / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000")
    openrouter_app_name: str = os.getenv("OPENROUTER_APP_NAME", "Surelock Homes")
    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic")
    model: str = os.getenv("MODEL", "claude-opus-4-6-20250514")
    thinking_budget_tokens: int = _env_int("THINKING_BUDGET_TOKENS", 10000)
    llm_max_context_chars: int = _env_int("LLM_MAX_CONTEXT_CHARS", 1000000)
    max_tokens: int = _env_int("MAX_TOKENS", 16000)
    tool_timeout_seconds: int = _env_int("TOOL_TIMEOUT_SECONDS", 30)
    gis_timeout_seconds: int = _env_int("GIS_TIMEOUT_SECONDS", 8)
    google_api_timeout_seconds: int = _env_int("GOOGLE_API_TIMEOUT_SECONDS", 5)
    socrata_timeout_seconds: int = _env_int("SOCRATA_TIMEOUT_SECONDS", 10)
    probe_timeout_seconds: int = _env_int("PROBE_TIMEOUT_SECONDS", 10)
    cache_max_age_hours: int = _env_int("CACHE_MAX_AGE_HOURS", 12)
    rate_limit_max: int = _env_int("RATE_LIMIT_MAX", 10)
    rate_limit_window: int = _env_int("RATE_LIMIT_WINDOW", 60)


def load_settings() -> Settings:
    provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", ""),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000"),
        openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "Surelock Homes"),
        llm_provider=provider,
        model=os.getenv("MODEL", "claude-opus-4-6-20250514"),
        thinking_budget_tokens=_env_int("THINKING_BUDGET_TOKENS", 10000),
        llm_max_context_chars=_env_int("LLM_MAX_CONTEXT_CHARS", 1000000),
        max_tokens=_env_int("MAX_TOKENS", 16000),
        tool_timeout_seconds=_env_int("TOOL_TIMEOUT_SECONDS", 30),
        gis_timeout_seconds=_env_int("GIS_TIMEOUT_SECONDS", 8),
        google_api_timeout_seconds=_env_int("GOOGLE_API_TIMEOUT_SECONDS", 5),
        socrata_timeout_seconds=_env_int("SOCRATA_TIMEOUT_SECONDS", 10),
        probe_timeout_seconds=_env_int("PROBE_TIMEOUT_SECONDS", 10),
        cache_max_age_hours=_env_int("CACHE_MAX_AGE_HOURS", 12),
        rate_limit_max=_env_int("RATE_LIMIT_MAX", 10),
        rate_limit_window=_env_int("RATE_LIMIT_WINDOW", 60),
    )


def current_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
