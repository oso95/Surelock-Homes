from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class InvestigationNarration:
    query: str
    narration: List[str] = field(default_factory=list)
    thinking: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    assistant_text: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_narration(self, value: str) -> None:
        if value:
            self.narration.append(value)

    def add_thinking(self, value: str) -> None:
        if value:
            self.thinking.append(value)

    def add_tool_call(self, name: str, arguments: Dict[str, Any], result: Dict[str, Any]) -> None:
        self.tool_calls.append({"tool": name, "arguments": arguments, "result": result})

    def add_assistant_text(self, value: str) -> None:
        if value:
            self.assistant_text.append(value)

    def to_markdown(self) -> str:
        # Return only the narrative content.  Thinking trace and tool calls
        # are rendered in their own UI sections, so including them here would
        # cause duplication.  Prefer assistant_text (the LLM's full formatted
        # output) over the narration list (which loses formatting).
        if self.assistant_text:
            return "\n\n".join(self.assistant_text)
        if self.narration:
            return "\n\n".join(self.narration)
        return "No narrative available."

    def as_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "created_at": self.created_at,
            "narration": self.narration,
            "assistant_text": self.assistant_text,
            "thinking": self.thinking,
            "tool_calls": self.tool_calls,
            "summary_markdown": self.to_markdown(),
        }

    def save(self, output_dir: Path, run_id: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = self.as_dict()
        output_path = output_dir / f"{run_id}.json"
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return output_path
