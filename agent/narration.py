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
        sections = [
            "# Investigation Narrative",
        ]
        if self.narration:
            sections.extend(f"- {line}" for line in self.narration)
        elif self.assistant_text:
            sections.extend(f"- {line}" for line in self.assistant_text)
        else:
            sections.append("- No narration available.")
        sections.extend(["", "## Thinking Trace", ""])
        sections.extend(f"- {line}" for line in self.thinking or ["Thinking not captured (offline mode)."])
        sections.extend(["", "## Tool Calls", ""])
        if not self.tool_calls:
            sections.append("No tool calls were executed.")
        else:
            for item in self.tool_calls:
                sections.append(f"- {item['tool']}: args={item['arguments']}")
        return "\n".join(sections)

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
