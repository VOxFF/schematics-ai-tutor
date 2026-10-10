"""FastAPI entry point. REST lives under /api; the WebSocket session will be /ws/session."""

import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI

from .config import REPO_ROOT, config_path, load_config
from .usage_log import UsageLog


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    # start.sh sets one run id per ./start.sh, so code reloads keep writing to the same file.
    run_id = os.environ.get("SCHEMATICS_RUN_ID") or datetime.now().strftime("%Y%m%d-%H%M%S")
    usage_log = UsageLog.from_config(config, REPO_ROOT, run_id)
    app.state.config = config
    app.state.usage_log = usage_log
    usage_log.event("server_started", run_id=run_id, pid=os.getpid(), config=str(config_path()))
    yield
    usage_log.summary()
    usage_log.event("server_stopped", pid=os.getpid())


app = FastAPI(title="Schematics AI Tutor", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
