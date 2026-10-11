"""Reply composer: turns Claude's validated reply into the chat message (docs/design.md §4).

Claude judges the learner and reports score changes and new topics; the composer bounds them:
changes of ±1 per reply, scores within 0-3, `explained` never down, at most one topic taught
per reply, at most one new topic. It also adds the icon for the message's kind, for a
`knowledge` message the taught topic's name as a title, and the spans of the learner's topics
in the text, which the chat shows in bold.
"""

import re

from .learner_profile import MAX_SCORE, add, find, join, load_catalog, sanitize, topic_entry
from .tutor import location_talk

ICONS = {
    "praise": "🎉",
    "nudge": "👉",
    "feedback": "💡",
    "question": "❓",
    "knowledge": "📘",
    "hint": "🔑",
}
MAX_UPDATES = 3  # topics whose scores change in one reply


def _variants(topic: dict) -> set[str]:
    """How a topic may appear in a text: its name without a unit in brackets or a leading "In"
    ("Ohm (Ω)" → "Ohm", "In series" → "series"), and its id with spaces."""
    name = re.sub(r"\s*\(.*?\)", "", topic["name"]).strip()
    name = re.sub(r"^in\s+", "", name, flags=re.IGNORECASE)
    return {v for v in (name, topic["id"].replace("_", " ")) if len(v) >= 3}


def term_spans(text: str, profile: dict) -> list[list[int]]:
    """[start, end] of the first mention of each profile topic in `text`, longest names first,
    whole words only, plurals included. Offsets count UTF-16 code units, as JavaScript strings do."""
    topics = profile["topics"]
    if not topics:
        return []
    groups = []
    for i, topic in enumerate(topics):
        variants = sorted(_variants(topic), key=len, reverse=True)
        alternatives = "|".join(re.escape(v).replace("'", "['’]") for v in variants)
        groups.append(f"(?P<t{i}>(?:{alternatives})(?:e?s)?)")
    # Longer names first, so "voltage source" wins over "voltage".
    order = sorted(range(len(topics)), key=lambda i: -max(map(len, _variants(topics[i])), default=0))
    pattern = re.compile(r"\b(?:" + "|".join(groups[i] for i in order) + r")\b", re.IGNORECASE)
    spans, seen = [], set()
    for match in pattern.finditer(text):
        if match.lastgroup not in seen:
            seen.add(match.lastgroup)
            spans.append([_utf16(text, match.start()), _utf16(text, match.end())])
    return spans


def _utf16(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


def _delta(value, low: int, high: int) -> int:
    return min(max(value, low), high) if isinstance(value, int) and not isinstance(value, bool) else 0


def _bring(profile: dict, topic_id, skill_level: int) -> dict | None:
    """A topic in the profile, or a catalog topic Claude brings forward (it joins the profile)."""
    if not isinstance(topic_id, str):
        return None
    topic = find(profile, topic_id)
    if topic is None and topic_id in load_catalog():
        entry = topic_entry(load_catalog()[topic_id], source="catalog", introduced=skill_level)
        if entry and add(profile, entry):
            topic = entry
    return topic


def compose(message: dict, profile: dict, skill_level: int) -> tuple[dict, list[dict]]:
    """Apply the reply's topic changes to `profile` (in place) and return (chat message, dropped),
    where `dropped` lists what was refused, for the log."""
    meta, dropped = message.get("meta", {}), []

    # A new topic first, so the reply's score changes can name it.
    new = meta.get("new_topic")
    if new:
        catalog = load_catalog().get(new.get("id")) if isinstance(new, dict) else None
        entry = (topic_entry(catalog, source="catalog", introduced=skill_level) if catalog
                 else topic_entry(new, source="claude", introduced=skill_level))
        if not entry or (not add(profile, entry) and not find(profile, entry["id"])):
            dropped.append({"new_topic": new})

    taught, seen = None, set()
    for update in meta.get("topic_updates") or []:
        topic_id = update.get("topic") if isinstance(update, dict) else None
        if topic_id in seen or len(seen) >= MAX_UPDATES:
            dropped.append(update)
            continue
        topic = _bring(profile, topic_id, skill_level)
        if topic is None:
            dropped.append(update)
            continue
        seen.add(topic_id)
        understanding = _delta(update.get("understanding"), -1, 1)
        explained = _delta(update.get("explained"), 0, 1)
        if explained and taught:
            dropped.append({"topic": topic_id, "explained": explained})  # one topic taught per reply
            explained = 0
        topic["understanding"] = min(max(topic["understanding"] + understanding, 0), MAX_SCORE)
        topic["explained"] = min(topic["explained"] + explained, MAX_SCORE)
        if explained:
            taught = topic

    chat = message["chat"]
    kind = chat["kind"]
    title = taught["name"] if kind == "knowledge" and taught else None
    return {"kind": kind, "icon": ICONS.get(kind, "💬"), "title": title, "text": chat["text"],
            "terms": term_spans(chat["text"], profile)}, dropped


def welcome(level: dict, profile, skill_level: int) -> dict:
    """The chat message for a new task: the generator's `welcome`, or a plain line when it has
    none or describes locations. It's `knowledge` when the task brings topics new to the learner,
    else `feedback`. The learner's profile (as the browser sent it) only marks the terms; the
    session adds the task's topics for real when it starts."""
    profile = sanitize(profile)
    new_topics = join(profile, level, level.get("board") or {}, skill_level)
    text = level.get("welcome") or ""
    if not text or location_talk(text):
        text = f"New task: {level.get('title', 'a new circuit')}. Let's see what you make of it!"
    kind = "knowledge" if new_topics else "feedback"
    return {"kind": kind, "icon": ICONS[kind], "title": None, "text": text, "terms": term_spans(text, profile)}
