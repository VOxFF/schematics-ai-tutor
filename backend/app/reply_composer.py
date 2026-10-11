"""Reply composer: turns Claude's validated reply into the chat message (docs/design.md §4).

Claude judges the learner and reports score changes and new topics; the composer bounds them:
changes of ±1 per reply, scores within 0-3, `explained` never down, at most one topic taught
per reply, at most one new topic. It also adds the icon for the message's kind and, for a
`knowledge` message, the taught topic's name as a title.
"""

from .learner_profile import MAX_SCORE, add, find, load_catalog, topic_entry

ICONS = {
    "praise": "🎉",
    "nudge": "👉",
    "feedback": "💡",
    "question": "❓",
    "knowledge": "📘",
    "hint": "🔑",
}
MAX_UPDATES = 3  # topics whose scores change in one reply


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
    return {"kind": kind, "icon": ICONS.get(kind, "💬"), "title": title, "text": chat["text"]}, dropped
