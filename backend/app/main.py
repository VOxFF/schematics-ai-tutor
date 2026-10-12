"""FastAPI entry point. REST lives under /api, the learning session is the WebSocket /ws/session."""

import asyncio
import os
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.requests import HTTPConnection
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import fallback
from .claude_status import ClaudeStatus, GuardedClaude, available
from .config import REPO_ROOT, config_path, load_config
from .log_archive import LogArchive
from .rate_limits import RateLimiter, client_ip
from .reply_composer import welcome
from .research import ResearchLog
from .session import Session
from .task_cache import TaskCache, solved
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
    # Logs: archive what earlier runs left, then archive by size and nightly (docs/deployment.md §5).
    archive = LogArchive.from_config(config, REPO_ROOT)
    usage_log = UsageLog.from_config(config, REPO_ROOT, run_id, archive)
    nightly = None
    if archive:
        archive.on_archived = lambda result: usage_log.event("logs_archived", **result)
        await asyncio.to_thread(archive.archive, "startup")
        nightly = asyncio.create_task(archive.nightly())
    # Rate limits and the daily Claude budget (ratelimiting.yaml, docs/design.md §6).
    limits = RateLimiter.from_settings(config.get("rate_limits", {}))
    usage_log.on_cost = limits.budget.spend
    app.state.limits = limits
    app.state.config = config
    app.state.usage_log = usage_log
    app.state.references = References()
    # Learner experience research, with consent (docs/design.md §5); None when it's off.
    app.state.research_log = ResearchLog.from_config(config, REPO_ROOT, usage_log)
    # The SDK reads ANTHROPIC_API_KEY from the environment; without it, Claude features are off.
    # Wrapped, so an outage marks Claude down for `claude.down_s` (docs/design.md §6).
    status = ClaudeStatus(config.get("claude", {}).get("down_s", 300), usage_log)
    app.state.claude = (GuardedClaude(anthropic.AsyncAnthropic(), status)
                        if os.environ.get("ANTHROPIC_API_KEY") else None)
    app.state.task_cache = task_cache(app.state.claude, config, usage_log, limits)
    usage_log.event("server_started", run_id=run_id, pid=os.getpid(), config=str(config_path()),
                    claude=app.state.claude is not None, pregeneration=app.state.task_cache is not None)
    if app.state.task_cache:
        app.state.task_cache.fill_first_task_pool()  # new learners don't wait at Start
    yield
    if app.state.task_cache:
        app.state.task_cache.close()
    if nightly:
        nightly.cancel()
    usage_log.summary()
    usage_log.event("server_stopped", pid=os.getpid())


def task_cache(claude, config: dict, usage_log: UsageLog, limits: RateLimiter) -> TaskCache | None:
    """Pre-generation (docs/design.md §3), or None without Claude or when it's turned off."""
    settings = config.get("pregeneration", {})
    if claude is None or not settings.get("enabled", True):
        return None

    async def produce(progress: dict):
        return await generate_task(claude, config, usage_log, skill_level=progress["skill_level"],
                                   history=progress["history"])

    return TaskCache(produce, first_task_pool=settings.get("first_task_pool", 2),
                     max_entries=settings.get("max_entries", 50), ttl_s=settings.get("ttl_s", 3600),
                     usage_log=usage_log,
                     allow_background=lambda: limits.claude_allowed(background=True) and available(claude))


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


def get_research_log(conn: HTTPConnection) -> ResearchLog | None:
    return getattr(conn.app.state, "research_log", None)  # absent when the app runs without its lifespan


def get_limits(conn: HTTPConnection) -> RateLimiter:
    # Without the lifespan (tests), fresh limits from ratelimiting.yaml, without the budget's state file.
    limits = getattr(conn.app.state, "limits", None)
    return limits if limits is not None else RateLimiter(load_config().get("rate_limits", {}))


@app.middleware("http")
async def rest_rate_limit(request: Request, call_next):
    """REST requests per IP; the health check is exempt (Fly polls it, and ./smoke.sh)."""
    path = request.url.path
    limits = getattr(request.app.state, "limits", None)  # set by the lifespan
    if limits is not None and path.startswith("/api/") and path != "/api/health":
        ip = client_ip(request)
        if not limits.rest.allow(ip):
            retry = int(limits.rest.retry_after(ip)) + 1
            return JSONResponse({"detail": "Too many requests; try again shortly."}, status_code=429,
                                headers={"Retry-After": str(retry)})
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    # The deployed commit, set by the deploy workflows; lets ./smoke.sh confirm the new release is live.
    return {"status": "ok", "commit": os.environ.get("SCHEMATICS_COMMIT")}


class GenerateTaskRequest(BaseModel):
    skill_level: int = Field(1, ge=1)
    history: list[dict] = Field(default_factory=list, description="TaskSummary entries, oldest first")
    profile: dict | None = Field(None, description="LearnerProfile, to compose the welcome message")


@app.post("/api/tasks/generate")
async def generate(
    body: GenerateTaskRequest,
    request: Request,
    config: dict = Depends(get_config),
    usage_log: UsageLog = Depends(get_usage_log),
    claude=Depends(get_claude),
    references: dict = Depends(get_references),
    cache: TaskCache | None = Depends(get_task_cache),
    limits: RateLimiter = Depends(get_limits),
) -> dict:
    """The task for this progress as a Level: pre-generated when the cache has one, else generated
    now. The task after it is then generated in the background (docs/design.md §3). When Claude
    is down, refused or fails, a task from the fallback pack (docs/design.md §6)."""
    progress = {"skill_level": body.skill_level, "history": body.history}
    # Why Claude can't generate now, if it can't: the pack is served instead of waiting or failing.
    if claude is None:
        reason = "no_claude"
    elif not available(claude):
        reason = "claude_down"
    elif not limits.claude_allowed():
        reason = "claude_budget"
    elif not limits.generations.allow(client_ip(request)):
        reason = "rate_limited"
    else:
        reason = None
    # A pre-generated task is served even when Claude can't generate: it is already paid for.
    if cache is not None:
        result = await cache.get(progress, produce=reason is None)
    elif reason is None:
        result = await generate_task(claude, config, usage_log, skill_level=body.skill_level, history=body.history)
    else:
        result = None
    source = "generated"
    if result is None or result.level is None:
        failed = result
        result = fallback.pick(body.skill_level, body.history, config, usage_log)
        usage_log.event("generation_fallback", skill_level=body.skill_level, reason=reason or "generation_failed",
                        served=result is not None)
        if result is None:  # no pack for this skill level: the learner can retry
            message = "Sorry, I couldn't create a task right now. Please try again."
            raise HTTPException(502, {"message": message, "attempts": getattr(failed, "attempts", 0),
                                      "errors": getattr(failed, "errors", [])})
        source = "fallback"
        if cache is not None:  # the next task is generated ahead if Claude allows it by then
            cache.pregenerate(solved(progress, result.level))
    result.level["source"] = source  # kept with the level, so the research records show it
    references[result.level["id"]] = result.spec["complete_board"]
    return {
        "level": result.level,
        "welcome": welcome(result.level, body.profile, body.skill_level),
        "difficulty": result.spec["difficulty"],
        "rationale": result.spec["rationale"],
        "attempts": result.attempts,
        "source": source,
    }


@app.websocket("/ws/session")
async def session_socket(
    websocket: WebSocket,
    config: dict = Depends(get_config),
    usage_log: UsageLog = Depends(get_usage_log),
    claude=Depends(get_claude),
    references: dict = Depends(get_references),
    cache: TaskCache | None = Depends(get_task_cache),
    limits: RateLimiter = Depends(get_limits),
    research_log: ResearchLog | None = Depends(get_research_log),
) -> None:
    await websocket.accept()
    ip = client_ip(websocket)
    if not limits.session_opened(ip):
        # Policy violation (1008): the client waits longer before reconnecting (tutorSession.js).
        usage_log.event("session_refused", reason="rate_limited")
        await websocket.send_json({"type": "error", "code": "rate_limited", "request_id": None,
                                   "message": "Too many sessions from your network; reconnecting shortly."})
        await websocket.close(code=1008)
        return

    async def send(message: dict) -> None:
        try:
            await websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass  # the learner left; nothing to deliver to

    session = Session(send, config=config, claude=claude, usage_log=usage_log, references=references,
                      task_cache=cache, limits=limits, research_log=research_log)
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
        limits.session_closed(ip)
        for task in session.tasks:
            task.cancel()
        if session.tasks:
            await asyncio.gather(*session.tasks, return_exceptions=True)


# The deployed image serves the built frontend from the same origin (Dockerfile). Locally the Vite
# dev server serves it, and there is no build. Mounted last, so /api and /ws take precedence.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
