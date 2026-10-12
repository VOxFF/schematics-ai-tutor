"""Loads the root config.yaml (docs/design.md §7) and ratelimiting.yaml (§6)."""

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def config_path() -> Path:
    return Path(os.environ.get("SCHEMATICS_CONFIG", REPO_ROOT / "config.yaml"))


def rate_limits_path() -> Path:
    return Path(os.environ.get("SCHEMATICS_RATELIMITS", REPO_ROOT / "ratelimiting.yaml"))


def load_config(path: Path | None = None) -> dict:
    """config.yaml, with ratelimiting.yaml under `rate_limits`."""
    with open(path or config_path()) as f:
        config = yaml.safe_load(f) or {}
    with open(rate_limits_path()) as f:
        config["rate_limits"] = yaml.safe_load(f) or {}
    return config
