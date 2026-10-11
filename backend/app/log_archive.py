"""Log files in parts, and their archive: gzip into history/, oldest deleted over a size cap.

Every log is a family of JSON-lines files, `<prefix>-<run id>.<part>.jsonl`. The archive rolls
each open log to its next part, compresses every closed part into `history/`, and deletes the
oldest history files until the history fits its budget. It runs at startup, when a part grows
past `max_file_mb`, and nightly at `nightly_utc` (docs/deployment.md §5).
"""

import asyncio
import gzip
import os
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

MB = 1024 * 1024
PART = re.compile(r"^(?P<stem>.+)\.(?P<part>\d+)\.jsonl(?:\.gz)?$")


class LogFile:
    """One log family for one run, written in parts. Thread-safe."""

    def __init__(self, directory: Path, prefix: str, run_id: str, *, max_bytes: int | None = None,
                 on_full=None, first_part: int = 1):
        self.directory = directory
        self.stem = f"{prefix}-{run_id}"
        self.part = first_part
        self.max_bytes = max_bytes
        self.on_full = on_full  # called once when the current part passes max_bytes
        self.size = 0
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.directory / f"{self.stem}.{self.part:03d}.jsonl"

    def write(self, line: str) -> None:
        data = line if line.endswith("\n") else line + "\n"
        with self._lock:
            with open(self.path, "a") as f:
                f.write(data)
            was_full = self.full
            self.size += len(data.encode())
            just_full = not was_full and self.full
        if just_full and self.on_full:
            self.on_full()

    @property
    def full(self) -> bool:
        return self.max_bytes is not None and self.size > self.max_bytes

    def roll(self) -> Path | None:
        """Start the next part; returns the closed part, or None when the current one is empty."""
        with self._lock:
            if not self.path.exists():
                return None
            closed = self.path
            self.part += 1
            self.size = 0
            return closed


class LogArchive:
    def __init__(self, directory: Path, *, history_dir: str = "history", max_file_mb: float = 20,
                 history_max_mb: float = 200, nightly_utc: str | None = None):
        self.directory = directory
        self.history = directory / history_dir
        self.max_file_bytes = int(max_file_mb * MB)
        self.history_max_bytes = int(history_max_mb * MB)
        self.nightly_utc = nightly_utc
        self.logs: list[LogFile] = []
        self.on_archived = None  # called with the result of each archive, e.g. to log it
        self._lock = threading.Lock()  # one archive at a time
        self._pending_lock = threading.Lock()  # never held long: writers take it
        self._pending = False
        self.history.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: dict, root: Path) -> "LogArchive | None":
        """The archive for the logs directory, or None when logging is off.
        SCHEMATICS_LOGS_DIR overrides `logs.dir` (the Fly volume, docs/deployment.md §5)."""
        logs = config.get("logs") or {}
        if not logs.get("enabled"):
            return None
        directory = Path(os.environ.get("SCHEMATICS_LOGS_DIR") or root / logs.get("dir", "logs"))
        directory.mkdir(parents=True, exist_ok=True)
        return cls(directory, history_dir=logs.get("history_dir", "history"),
                   max_file_mb=logs.get("max_file_mb", 20), history_max_mb=logs.get("history_max_mb", 200),
                   nightly_utc=logs.get("nightly_utc"))

    def open(self, prefix: str, run_id: str) -> LogFile:
        """A log in this directory. A run id seen before (e.g. a code reload) continues at its next part."""
        stem = f"{prefix}-{run_id}"
        parts = [int(m["part"]) for p in (*self.directory.iterdir(), *self.history.iterdir())
                 if (m := PART.match(p.name)) and m["stem"] == stem]
        log = LogFile(self.directory, prefix, run_id, max_bytes=self.max_file_bytes,
                      on_full=lambda: self.archive_soon("size"), first_part=max(parts, default=0) + 1)
        self.logs.append(log)
        return log

    def archive(self, reason: str) -> dict:
        """Roll every open log, gzip every closed part into history/, then delete the oldest history
        files until it fits. Closed parts include ones left by earlier runs."""
        with self._lock:
            with self._pending_lock:
                self._pending = False
            for log in self.logs:
                log.roll()
            current = {log.path for log in self.logs}
            archived = []
            for path in sorted(self.directory.glob("*.jsonl")):
                if path not in current:
                    archived.append(self._compress(path))
            deleted = self._prune(keep=set(archived))
            result = {"reason": reason, "archived": [p.name for p in archived], "deleted": deleted,
                      "history_bytes": sum(p.stat().st_size for p in self.history.glob("*.gz"))}
        if self.on_archived:
            self.on_archived(result)
        return result

    def archive_soon(self, reason: str) -> None:
        """Archive in a background thread, off the request path; at most one waiting at a time."""
        with self._pending_lock:
            if self._pending:
                return
            self._pending = True
        threading.Thread(target=self.archive, args=(reason,), daemon=True, name="log-archive").start()

    def _compress(self, path: Path) -> Path:
        target = self.history / f"{path.name}.gz"
        with open(path, "rb") as src, gzip.open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        stat = path.stat()
        os.utime(target, (stat.st_atime, stat.st_mtime))  # history sorts by when the part was written
        path.unlink()
        return target

    def _prune(self, keep: set[Path]) -> list[str]:
        files = sorted(self.history.glob("*.gz"), key=lambda p: (p.stat().st_mtime, p.name))
        total = sum(p.stat().st_size for p in files)
        deleted = []
        for path in files:
            if total <= self.history_max_bytes:
                break
            if path in keep:
                continue
            total -= path.stat().st_size
            path.unlink()
            deleted.append(path.name)
        return deleted

    def seconds_until_nightly(self, now: datetime | None = None) -> float | None:
        if not self.nightly_utc:
            return None
        now = now or datetime.now(timezone.utc)
        hour, minute = (int(x) for x in self.nightly_utc.split(":"))
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        return (at - now).total_seconds()

    async def nightly(self) -> None:
        """Archive once a day at nightly_utc, until cancelled."""
        while (delay := self.seconds_until_nightly()) is not None:
            await asyncio.sleep(delay)
            await asyncio.to_thread(self.archive, "nightly")
