from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from agent.loop import run_investigation
from config import FRONTEND_DIR
from tools.definitions import get_tool_definitions

app = FastAPI(title="Surelock Homes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Simple in-memory rate limiter
_rate_limit_store: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60


def _is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    timestamps = _rate_limit_store[client_ip]
    _rate_limit_store[client_ip] = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
        return True
    _rate_limit_store[client_ip].append(now)
    return False


app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


class InvestigateRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    max_turns: int = Field(default=8, ge=1, le=20)
    offline: bool = True

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tool-definitions")
def tool_definitions() -> List[Dict[str, Any]]:
    return get_tool_definitions()


@app.post("/api/investigate")
def investigate(payload: InvestigateRequest, request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )
    return run_investigation(
        payload.query,
        max_turns=payload.max_turns,
        offline=payload.offline,
    )


@app.get("/", response_class=FileResponse)
def serve_index() -> Path:
    return FRONTEND_DIR / "index.html"
