from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv()


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
SCRIPTS_DIR = ROOT_DIR / "scripts"
OUTPUT_DIR = ROOT_DIR / "output"
FRONTEND_DIR = ROOT_DIR / "frontend"

for path in (DATA_DIR, SCRIPTS_DIR, OUTPUT_DIR, FRONTEND_DIR):
    path.mkdir(exist_ok=True)


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
    model: str = os.getenv("MODEL", "claude-opus-4-6-20250514")
    thinking_budget_tokens: int = _env_int("THINKING_BUDGET_TOKENS", 10000)
    max_tokens: int = _env_int("MAX_TOKENS", 16000)
    tool_timeout_seconds: int = _env_int("TOOL_TIMEOUT_SECONDS", 30)


def load_settings() -> Settings:
    return Settings()


def current_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

