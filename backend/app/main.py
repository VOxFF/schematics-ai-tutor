"""FastAPI entry point. REST lives under /api; the WebSocket session will be /ws/session."""

import asyncio
import os
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime

import anthropic
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.requests import HTTPConnection
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import REPO_ROOT, config_path, load_config
from .session import Session
from .task_cache import TaskCache
from .task_generation import generate_task
from .usage_log import UsageLog


class References(OrderedDict):
    """Reference solutions (complete boards) of generated levels, by level id. Never sent to the browser."""

    def __init__(self, limit: int = 1000):
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self.limit:
            self.popitem(last=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    # start.sh sets one run id per ./start.sh, so code reloads keep writing to the same file.
    run_id = os.environ.get("SCHEMATICS_RUN_ID") or datetime.now().strftime("%Y%m%d-%H%M%S")
    usage_log = UsageLog.from_config(config, REPO_ROOT, run_id)
    app.state.config = config
    app.state.usage_log = usage_log
    app.state.references = References()
    # The SDK reads ANTHROPIC_API_KEY from the environment; without it, Claude features are off.
    app.state.claude = anthropic.AsyncAnthropic() if os.environ.get("ANTHROPIC_API_KEY") else None
    app.state.task_cache = task_cache(app.state.claude, config, usage_log)
    usage_log.event("server_started", run_id=run_id, pid=os.getpid(), config=str(config_path()),
                    claude=app.state.claude is not None, pregeneration=app.state.task_cache is not None)
    if app.state.task_cache:
        app.state.task_cache.fill_first_task_pool()  # new learners don't wait at Start
    yield
    if app.state.task_cache:
        app.state.task_cache.close()
    usage_log.summary()
    usage_log.event("server_stopped", pid=os.getpid())


def task_cache(claude, config: dict, usage_log: UsageLog) -> TaskCache | None:
    """Pre-generation (docs/design.md §3), or None without Claude or when it's turned off."""
    settings = config.get("pregeneration", {})
    if claude is None or not settings.get("enabled", True):
        return None

    async def produce(progress: dict):
        return await generate_task(claude, config, usage_log, skill_level=progress["skill_level"],
                                   history=progress["history"])

    return TaskCache(produce, first_task_pool=settings.get("first_task_pool", 2),
                     max_entries=settings.get("max_entries", 50), ttl_s=settings.get("ttl_s", 3600),
                     usage_log=usage_log)


app = FastAPI(title="Schematics AI Tutor", lifespan=lifespan)


# HTTPConnection covers both HTTP requests and WebSockets.
def get_config(conn: HTTPConnection) -> dict:
    return conn.app.state.config


def get_usage_log(conn: HTTPConnection) -> UsageLog:
    return conn.app.state.usage_log


def get_claude(conn: HTTPConnection):
    return conn.app.state.claude


def get_references(conn: HTTPConnection) -> dict:
    return conn.app.state.references


def get_task_cache(conn: HTTPConnection) -> TaskCache | None:
    return getattr(conn.app.state, "task_cache", None)  # absent when the app runs without its lifespan


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
    references: dict = Depends(get_references),
    cache: TaskCache | None = Depends(get_task_cache),
) -> dict:
    """The task for this progress as a Level: pre-generated when the cache has one, else generated
    now. The task after it is then generated in the background (docs/design.md §3)."""
    if claude is None:
        raise HTTPException(503, "Claude is not configured: set ANTHROPIC_API_KEY or backend/keys/apikey.txt")
    progress = {"skill_level": body.skill_level, "history": body.history}
    if cache is not None:
        result = await cache.get(progress)
    else:
        result = await generate_task(claude, config, usage_log, skill_level=body.skill_level, history=body.history)
    if result.level is None:
        message = f"Sorry, I couldn't create a valid task after {result.attempts} attempts. Please try again."
        raise HTTPException(502, {"message": message, "attempts": result.attempts, "errors": result.errors})
    references[result.level["id"]] = result.spec["complete_board"]
    return {
        "level": result.level,
        "difficulty": result.spec["difficulty"],
        "rationale": result.spec["rationale"],
        "attempts": result.attempts,
    }


@app.websocket("/ws/session")
async def session_socket(
    websocket: WebSocket,
    config: dict = Depends(get_config),
    usage_log: UsageLog = Depends(get_usage_log),
    claude=Depends(get_claude),
    references: dict = Depends(get_references),
    cache: TaskCache | None = Depends(get_task_cache),
) -> None:
    await websocket.accept()

    async def send(message: dict) -> None:
        try:
            await websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass  # the learner left; nothing to deliver to

    session = Session(send, config=config, claude=claude, usage_log=usage_log, references=references,
                      task_cache=cache)
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                await session.handle(message)
            else:
                await session.error("bad_message", "messages must be JSON objects")
    except WebSocketDisconnect:
        pass
    finally:
        for task in session.tasks:
            task.cancel()
        if session.tasks:
            await asyncio.gather(*session.tasks, return_exceptions=True)


# The deployed image serves the built frontend from the same origin (Dockerfile). Locally the Vite
# dev server serves it, and there is no build. Mounted last, so /api and /ws take precedence.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
