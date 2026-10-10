"""FastAPI entry point. REST lives under /api; the WebSocket session will be /ws/session."""

import os
from contextlib import asynccontextmanager
from datetime import datetime

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .config import REPO_ROOT, config_path, load_config
from .task_generation import generate_task
from .usage_log import UsageLog


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    # start.sh sets one run id per ./start.sh, so code reloads keep writing to the same file.
    run_id = os.environ.get("SCHEMATICS_RUN_ID") or datetime.now().strftime("%Y%m%d-%H%M%S")
    usage_log = UsageLog.from_config(config, REPO_ROOT, run_id)
    app.state.config = config
    app.state.usage_log = usage_log
    # The SDK reads ANTHROPIC_API_KEY from the environment; without it, Claude features are off.
    app.state.claude = anthropic.AsyncAnthropic() if os.environ.get("ANTHROPIC_API_KEY") else None
    usage_log.event("server_started", run_id=run_id, pid=os.getpid(), config=str(config_path()),
                    claude=app.state.claude is not None)
    yield
    usage_log.summary()
    usage_log.event("server_stopped", pid=os.getpid())


app = FastAPI(title="Schematics AI Tutor", lifespan=lifespan)


def get_config(request: Request) -> dict:
    return request.app.state.config


def get_usage_log(request: Request) -> UsageLog:
    return request.app.state.usage_log


def get_claude(request: Request):
    return request.app.state.claude


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


class GenerateTaskRequest(BaseModel):
    skill_level: int = Field(1, ge=1)
    history: list[dict] = Field(default_factory=list, description="TaskSummary entries, oldest first")


@app.post("/api/tasks/generate")
async def generate(
    body: GenerateTaskRequest,
    config: dict = Depends(get_config),
    usage_log: UsageLog = Depends(get_usage_log),
    claude=Depends(get_claude),
) -> dict:
    """Ask Claude for the next task and return it as a Level (pipeline endpoint)."""
    if claude is None:
        raise HTTPException(503, "Claude is not configured: set ANTHROPIC_API_KEY or backend/keys/apikey.txt")
    result = await generate_task(claude, config, usage_log, skill_level=body.skill_level, history=body.history)
    if result.level is None:
        message = f"Sorry, I couldn't create a valid task after {result.attempts} attempts. Please try again."
        raise HTTPException(502, {"message": message, "attempts": result.attempts, "errors": result.errors})
    return {
        "level": result.level,
        "difficulty": result.spec["difficulty"],
        "rationale": result.spec["rationale"],
        "attempts": result.attempts,
    }
