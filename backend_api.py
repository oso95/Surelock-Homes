from __future__ import annotations

import json
import time
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from agent.loop import run_investigation, run_investigation_stream
from config import FRONTEND_DIR, load_settings
from tools.definitions import get_tool_definitions

app = FastAPI(title="Surelock Homes API")
logger = logging.getLogger(__name__)

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
    offline: bool = False

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v


@app.get("/api/health")
def health() -> Dict[str, Any]:
    settings = load_settings()
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "google_maps_configured": bool(settings.google_maps_api_key),
    }


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
    try:
        return run_investigation(
            payload.query,
            max_turns=payload.max_turns,
            offline=payload.offline,
        )
    except RuntimeError as exc:
        logger.warning("Investigation runtime error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "status": "dependency_unavailable"},
        )
    except Exception:
        logger.exception("Investigation failed unexpectedly.")
        return JSONResponse(
            status_code=500,
            content={"detail": "Investigation failed. Check API keys and network connectivity.", "status": "unexpected_error"},
        )


def _sse_generator(
    query: str,
    max_turns: int,
    offline: bool = False,
) -> Generator[str, None, None]:
    try:
        for event in run_investigation_stream(query, max_turns=max_turns, offline=offline):
            yield f"data: {json.dumps(event, default=str)}\n\n"
    except Exception as exc:
        logger.exception("Streaming generator error for query %s", query)
        error_msg = str(exc).strip() or "Unexpected stream failure."
        if len(error_msg) > 240:
            error_msg = error_msg[:240] + "..."
        yield f"data: {json.dumps({'event': 'error', 'error': error_msg, 'query': query}, default=str)}\n\n"
        yield f"data: {json.dumps({'event': 'complete', 'payload': {'query': query, 'mode': 'agent', 'status': 'error', 'error': error_msg}}, default=str)}\n\n"


@app.post("/api/investigate/stream")
def investigate_stream(payload: InvestigateRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )
    try:
        return StreamingResponse(
            _sse_generator(payload.query, payload.max_turns, offline=payload.offline),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception:
        logger.exception("Streaming investigation failed.")
        return JSONResponse(
            status_code=500,
            content={"detail": "Streaming investigation failed. Check input and server logs.", "status": "unexpected_error"},
        )


@app.get("/", response_class=FileResponse)
def serve_index() -> Path:
    return FRONTEND_DIR / "index.html"
