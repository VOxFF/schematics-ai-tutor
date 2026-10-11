"""Usage and cost log: one JSON-lines log per backend run, under logs/, written in parts and
archived by log_archive.py (`run-<run id>.<part>.jsonl`).

Each line is one event. Claude calls carry the token usage reported by the API
and a cost estimate from the `pricing` table in config.yaml.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .log_archive import LogArchive, LogFile

USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
# Usage field -> pricing key (USD per million tokens).
PRICE_KEYS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}


class UsageLog:
    def __init__(self, file: LogFile | None, pricing: dict | None = None):
        self.file = file
        self.pricing = pricing or {}
        self._lock = threading.Lock()
        self.totals = {"claude_calls": 0, **{f: 0 for f in USAGE_FIELDS}, "cost_usd": 0.0}

    @classmethod
    def from_config(cls, config: dict, root: Path, run_id: str, archive: LogArchive | None = None) -> "UsageLog":
        """The run's log, archived by `archive`; without one (e.g. live tests), a plain log in logs.dir."""
        logs = config.get("logs") or {}
        if not logs.get("enabled"):
            return cls(None)
        if archive is None:
            directory = root / logs.get("dir", "logs")
            directory.mkdir(parents=True, exist_ok=True)
            return cls(LogFile(directory, "run", run_id), config.get("pricing"))
        return cls(archive.open("run", run_id), config.get("pricing"))

    @property
    def enabled(self) -> bool:
        return self.file is not None

    @property
    def path(self) -> Path | None:
        """The current part."""
        return self.file.path if self.file else None

    def event(self, kind: str, **fields) -> None:
        if not self.enabled:
            return
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": kind, **fields}
        self.file.write(json.dumps(record))

    def cost_usd(self, model: str, usage: dict) -> float | None:
        """Estimated cost of one call; None when the model has no pricing entry."""
        price = self.pricing.get(model)
        if price is None:
            return None
        return sum(usage.get(field, 0) * price.get(key, 0) for field, key in PRICE_KEYS.items()) / 1e6

    def claude_call(self, *, purpose: str, model: str, usage: dict, session_id: str | None = None, **extra) -> None:
        """Record one Claude API call. `usage` uses the API's usage field names."""
        usage = {f: int(usage.get(f) or 0) for f in USAGE_FIELDS}
        cost = self.cost_usd(model, usage)
        with self._lock:
            self.totals["claude_calls"] += 1
            for f in USAGE_FIELDS:
                self.totals[f] += usage[f]
            self.totals["cost_usd"] += cost or 0.0
        self.event(
            "claude_call",
            purpose=purpose,
            model=model,
            session_id=session_id,
            usage=usage,
            cost_usd=None if cost is None else round(cost, 6),
            **extra,
        )

    def summary(self) -> None:
        self.event("run_summary", pid=os.getpid(), **{**self.totals, "cost_usd": round(self.totals["cost_usd"], 6)})
