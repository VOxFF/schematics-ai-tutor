"""Usage and cost log: one JSON-lines file per backend run, under logs/.

Each line is one event. Claude calls carry the token usage reported by the API
and a cost estimate from the `pricing` table in config.yaml.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

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
    def __init__(self, path: Path | None, pricing: dict | None = None):
        self.path = path
        self.pricing = pricing or {}
        self._lock = threading.Lock()
        self.totals = {"claude_calls": 0, **{f: 0 for f in USAGE_FIELDS}, "cost_usd": 0.0}

    @classmethod
    def from_config(cls, config: dict, root: Path, run_id: str) -> "UsageLog":
        logs = config.get("logs") or {}
        if not logs.get("enabled"):
            return cls(None)
        directory = root / logs.get("dir", "logs")
        directory.mkdir(parents=True, exist_ok=True)
        return cls(directory / f"run-{run_id}.jsonl", config.get("pricing"))

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def event(self, kind: str, **fields) -> None:
        if not self.enabled:
            return
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": kind, **fields}
        with self._lock, open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")

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
