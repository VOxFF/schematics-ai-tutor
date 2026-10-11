"""Reply composer: bounded profile changes, new topics, icon and title."""

from app.reply_composer import ICONS, compose, term_spans
from app.tutor import KINDS


def profile(*topics):
    return {"topics": [{"id": t, "name": t.title(), "type": "term", "definition": "A test topic.", "introduced": 1,
                        "understanding": 1, "explained": 0, "source": "catalog"} for t in topics]}


def reply(kind="question", updates=None, new_topic=None):
    return {"meta": {"topic_updates": updates or [], "new_topic": new_topic},
            "chat": {"kind": kind, "text": "An ammeter has almost no resistance."}}


def scores(p, topic_id):
    t = next(t for t in p["topics"] if t["id"] == topic_id)
    return t["understanding"], t["explained"]


def test_every_kind_has_an_icon():
    assert set(ICONS) == set(KINDS)


def test_changes_are_clamped_and_explained_never_goes_down():
    p = profile("current", "voltage")
    chat, dropped = compose(reply(updates=[{"topic": "current", "understanding": 5, "explained": -3},
                                           {"topic": "voltage", "understanding": -9, "explained": 0}]), p, 2)
    assert scores(p, "current") == (2, 0) and scores(p, "voltage") == (0, 0) and dropped == []
    assert chat == {"kind": "question", "icon": ICONS["question"], "title": None,
                    "text": "An ammeter has almost no resistance.", "terms": []}


def test_scores_stay_within_zero_to_three():
    p = profile("current")
    for _ in range(5):
        compose(reply(updates=[{"topic": "current", "understanding": 1, "explained": 1}]), p, 2)
    assert scores(p, "current") == (3, 3)


def test_knowledge_teaches_one_topic_and_takes_its_name_as_title():
    p = profile("current", "voltage")
    chat, dropped = compose(reply("knowledge", [{"topic": "current", "understanding": 0, "explained": 1},
                                                {"topic": "voltage", "understanding": 0, "explained": 1}]), p, 2)
    assert chat["title"] == "Current" and chat["icon"] == ICONS["knowledge"]
    assert scores(p, "current") == (1, 1) and scores(p, "voltage") == (1, 0)
    assert dropped == [{"topic": "voltage", "explained": 1}]


def test_unknown_and_repeated_topics_are_dropped_and_catalog_topics_join():
    p = profile("current")
    _, dropped = compose(reply(updates=[{"topic": "nonsense", "understanding": 1, "explained": 0},
                                        {"topic": "current", "understanding": 1, "explained": 0},
                                        {"topic": "current", "understanding": 1, "explained": 0},
                                        {"topic": "short_circuit", "understanding": -1, "explained": 0}]), p, 4)
    assert [d["topic"] for d in dropped] == ["nonsense", "current"]
    assert scores(p, "current") == (2, 0)
    joined = next(t for t in p["topics"] if t["id"] == "short_circuit")
    assert joined["introduced"] == 4 and joined["source"] == "catalog" and joined["understanding"] == 0


def test_claude_adds_a_topic_and_teaches_it():
    p = profile("current")
    new = {"id": "conductor", "name": "Conductor", "type": "term", "definition": "A material current flows through easily."}
    chat, dropped = compose(reply("knowledge", [{"topic": "conductor", "understanding": 0, "explained": 1}], new), p, 3)
    assert chat["title"] == "Conductor" and dropped == []
    added = p["topics"][-1]
    assert added["source"] == "claude" and added["introduced"] == 3 and added["explained"] == 1


def test_a_bad_new_topic_is_dropped():
    p = profile("current")
    _, dropped = compose(reply(new_topic={"id": "Bad Id", "name": "x", "type": "term", "definition": "x"}), p, 3)
    assert len(p["topics"]) == 1 and dropped == [{"new_topic": {"id": "Bad Id", "name": "x", "type": "term",
                                                                "definition": "x"}}]


def test_topic_terms_are_marked_once_each_longest_first():
    p = {"topics": [{"id": i, "name": n, "type": "term", "definition": "x", "introduced": 1, "understanding": 0,
                     "explained": 0, "source": "catalog"}
                    for i, n in [("voltage", "Voltage"), ("voltage_source", "Voltage source"), ("ohm", "Ohm (Ω)"),
                                 ("series", "In series"), ("ohms_law", "Ohm's law"), ("current", "Current")]]}
    text = "🔋 The voltage source pushes current; voltage splits in series. Ohm’s law uses ohms. Currents add."
    marked = [text.encode("utf-16-le")[2 * a:2 * b].decode("utf-16-le") for a, b in term_spans(text, p)]
    assert marked == ["voltage source", "current", "voltage", "series", "Ohm’s law", "ohms"]
