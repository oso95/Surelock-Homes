from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.loop import run_investigation
from config import FRONTEND_DIR
from tools.definitions import get_tool_definitions

app = FastAPI(title="Surelock Homes API")

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


class InvestigateRequest(BaseModel):
    query: str
    max_turns: int = 8
    offline: bool = True


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tool-definitions")
def tool_definitions() -> List[Dict[str, Any]]:
    return get_tool_definitions()


@app.post("/api/investigate")
def investigate(payload: InvestigateRequest) -> Dict[str, Any]:
    return run_investigation(
        payload.query,
        max_turns=payload.max_turns,
        offline=payload.offline,
    )


@app.get("/", response_class=FileResponse)
def serve_index() -> Path:
    return FRONTEND_DIR / "index.html"

