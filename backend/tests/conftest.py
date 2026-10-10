"""Shared test helpers: example specs and a fake Claude client."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import load_config
from app.task_spec import ALL_PIN_NAMES
from app.usage_log import UsageLog

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"


def load_example(name: str = "voltage_divider") -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def as_claude_output(spec: dict) -> dict:
    """Shape a spec as Claude's structured output would: null placeholders included."""
    spec = copy.deepcopy(spec)
    for c in spec["complete_board"]["components"]:
        c.setdefault("value", None)
        c["pins"] = {name: c["pins"].get(name) for name in ALL_PIN_NAMES}
    for d in spec["decoys"]:
        d.setdefault("value", None)
    return spec


def text_response(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


def tool_response(draft: dict, tool_id="tool_1"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=tool_id, name="validate_grid", input=draft)],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=800, output_tokens=400, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


class FakeClaude:
    """Returns scripted responses in order and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def with_options(self, **_):
        return self

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def usage_log(tmp_path, config):
    return UsageLog.from_config({**config, "logs": {"enabled": True, "dir": "logs"}}, tmp_path, "test")


def tutor_reply(text="Follow the path from the source. Where does it stop?", highlights=None, kind="question"):
    """A TutorMessage as Claude's structured output would produce it."""
    return text_response({
        "meta": {"principle": "closed_loop", "highlights": highlights or [], "hint_level": 2, "misconception": None},
        "chat": {"kind": kind, "text": text},
    })


def example_level(name="voltage_divider"):
    from app.task_spec import build_level, validate
    spec = load_example(name)
    return build_level(spec, 1, validate(spec)["board"]), spec


# A permissive curriculum level the example tasks fit, so generation-loop tests stay about the loop.
ANY_LEVEL = {
    "level": 1, "concept": "test", "goal": "test", "circuit": "test", "tasks": 2,
    "grid": {"columns": [12, 12], "rows": [8, 8]},
    "removed": {"wires": [0, 30], "parts": [0, 5]}, "decoys": [0, 5], "targets": [1, 2],
}


@pytest.fixture
def any_level(monkeypatch):
    import app.task_generation as generation
    monkeypatch.setattr(generation, "position", lambda skill_level: (ANY_LEVEL, 1))
    monkeypatch.setattr(generation, "pick_grid", lambda rules: {"columns": 12, "rows": 8})
    return ANY_LEVEL
