"""FastAPI entry point. REST lives under /api; the WebSocket session will be /ws/session."""

from fastapi import FastAPI

app = FastAPI(title="Schematics AI Tutor")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
