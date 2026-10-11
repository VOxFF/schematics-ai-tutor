"""Learner profile: the topics the learner has met, with two scores each (docs/design.md §4).

The browser keeps the profile and sends it with session.start, so everything here treats it
as untrusted input. Topics come from the catalog (backend/data/topics.yaml) or from Claude.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .curriculum import load_curriculum

TOPICS_PATH = Path(__file__).resolve().parents[1] / "data" / "topics.yaml"
TYPES = ("principle", "term")
SOURCES = ("catalog", "claude")
MAX_SCORE = 3
MAX_TOPICS = 80
MAX_NAME = 40
MAX_DEFINITION = 200
FOCUS_TOPICS = 8
RECENT_TOPICS = 5  # of the focus topics, how many are simply the most recent
TOPIC_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


@lru_cache(maxsize=1)
def load_catalog(path: Path = TOPICS_PATH) -> dict[str, dict]:
    """The catalog by topic ID."""
    return {t["id"]: t for t in yaml.safe_load(path.read_text())["topics"]}


def first_skill_level(curriculum_level: int, levels: list[dict] | None = None) -> int:
    """The skill level of a curriculum level's first task."""
    skill = 1
    for rules in levels or load_curriculum():
        if rules["level"] >= curriculum_level:
            break
        skill += rules["tasks"]
    return skill


def _score(value) -> int:
    return min(max(value, 0), MAX_SCORE) if isinstance(value, int) and not isinstance(value, bool) else 0


def _text(value, limit: int) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def topic_entry(raw, *, source: str, introduced: int) -> dict | None:
    """A profile entry from a catalog topic or Claude's new topic, or None if it isn't valid."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not TOPIC_ID.match(raw["id"]):
        return None
    name, definition = _text(raw.get("name"), MAX_NAME), _text(raw.get("definition"), MAX_DEFINITION)
    if not name or not definition or raw.get("type") not in TYPES:
        return None
    return {"id": raw["id"], "name": name, "type": raw["type"], "definition": definition,
            "introduced": introduced, "understanding": 0, "explained": 0, "source": source}


def sanitize(raw) -> dict:
    """A well-formed profile from whatever the browser sent; bad entries are dropped."""
    topics, seen = [], set()
    for item in (raw.get("topics") if isinstance(raw, dict) else None) or []:
        introduced = item.get("introduced") if isinstance(item, dict) else None
        source = item.get("source") if isinstance(item, dict) else None
        entry = topic_entry(item, source=source if source in SOURCES else "claude",
                            introduced=introduced if isinstance(introduced, int) and introduced >= 1 else 1)
        if entry and entry["id"] not in seen:
            entry["understanding"], entry["explained"] = _score(item.get("understanding")), _score(item.get("explained"))
            topics.append(entry)
            seen.add(entry["id"])
        if len(topics) >= MAX_TOPICS:
            break
    return {"topics": topics}


def find(profile: dict, topic_id: str) -> dict | None:
    return next((t for t in profile["topics"] if t["id"] == topic_id), None)


def add(profile: dict, entry: dict) -> bool:
    """Add a topic unless it's already there or the profile is full."""
    if find(profile, entry["id"]) or len(profile["topics"]) >= MAX_TOPICS:
        return False
    profile["topics"].append(entry)
    return True


def join(profile: dict, level: dict, board: dict, skill_level: int) -> list[str]:
    """Add the topics a task brings: its curriculum level's and earlier levels' topics, and the
    component types on its board. Returns the IDs that joined."""
    curriculum_level = (level.get("curriculum") or {}).get("level") or 1
    types = {c.get("type") for c in board.get("components", []) + board.get("inventory", [])}
    joined = []
    for topic in load_catalog().values():
        if "level" in topic and topic["level"] <= curriculum_level:
            introduced = min(skill_level, first_skill_level(topic["level"]))
        elif topic.get("component") in types:
            introduced = skill_level
        else:
            continue
        entry = topic_entry(topic, source="catalog", introduced=introduced)
        if entry and add(profile, entry):
            joined.append(entry["id"])
    return joined


def focus(profile: dict, skill_level: int) -> list[dict]:
    """The topics Claude sees: the most recent first, then older weak ones (understanding 0-1),
    then the rest, up to FOCUS_TOPICS."""
    by_recency = sorted(profile["topics"], key=lambda t: -t["introduced"])
    recent, older = by_recency[:RECENT_TOPICS], by_recency[RECENT_TOPICS:]
    weak = sorted((t for t in older if t["understanding"] <= 1), key=lambda t: t["understanding"])
    rest = [t for t in older if t["understanding"] > 1]
    picked = (recent + weak + rest)[:FOCUS_TOPICS]
    return [{"id": t["id"], "name": t["name"], "type": t["type"], "definition": t["definition"],
             "understanding": t["understanding"], "explained": t["explained"],
             "tasks_ago": max(skill_level - t["introduced"], 0)} for t in picked]
