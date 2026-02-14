from pathlib import Path

from config import current_utc_date


def load_system_prompt() -> str:
    path = Path(__file__).resolve().parents[1] / "surelock-homes-system-prompt.md"
    text = path.read_text(encoding="utf-8")
    return text.replace("{dynamic_date}", current_utc_date())

