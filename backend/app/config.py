"""Loads the root config.yaml (docs/design.md §5)."""

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def config_path() -> Path:
    return Path(os.environ.get("SCHEMATICS_CONFIG", REPO_ROOT / "config.yaml"))


def load_config(path: Path | None = None) -> dict:
    with open(path or config_path()) as f:
        return yaml.safe_load(f) or {}
