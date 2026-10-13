"""Reply composer: bounded profile changes, new topics, icon and title."""

from app.reply_composer import ICONS, compose, term_spans, welcome
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
    assert set(ICONS) == set(KINDS) | {"guide"}  # the guide is canned, never Claude's kind


def test_changes_are_clamped_and_explained_never_goes_down():
    p = profile("current", "voltage")
    chat, dropped = compose(reply(updates=[{"topic": "current", "understanding": 5, "explained": -3},
                                           {"topic": "voltage", "understanding": -9, "explained": 0}]), p, 2)
    assert scores(p, "current") == (2, 0) and scores(p, "voltage") == (0, 0) and dropped == []
    assert chat == {"kind": "question", "icon": ICONS["question"], "title": None,
                    "text": "An ammeter has almost no resistance.", "formula": None, "terms": []}


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


def test_a_welcome_without_text_or_with_location_talk_falls_back_to_a_plain_line():
    level = {"title": "Close the loop", "welcome": "Check row 3 first.", "board": {"components": [], "inventory": []}}
    message = welcome(level, None, 1)
    assert message["text"] == "New task: Close the loop. Let's see what you make of it!"
    assert message["kind"] == "knowledge"  # a new learner meets the level-1 topics
    assert welcome({**level, "welcome": ""}, None, 1)["text"].startswith("New task: Close the loop.")


def test_paragraphs_are_tidied_and_the_formula_passes_through():
    p = profile("current")
    message = reply()
    message["chat"]["text"] = "\n  Current is the flow.  \n\n\n\nIt needs a loop.\n"
    message["chat"]["formula"] = [r"I = \frac{V}{R}"]
    chat, _ = compose(message, p, 2)
    assert chat["text"] == "Current is the flow.\n\nIt needs a loop."
    assert chat["formula"] == [r"I = \frac{V}{R}"]
    assert chat["terms"] == [[0, 7]]


def test_latex_in_the_text_is_written_like_the_board_labels():
    message = reply()
    message["chat"]["text"] = r"Here R_2 is the one you choose, and V_{R2} is what $R_{\text{total}}$ splits; keep snake_case."
    message["chat"]["formula"] = [r"V_{R2} = V \cdot \frac{R_2}{R_1 + R_2}"]
    chat, _ = compose(message, profile(), 4)
    assert chat["text"] == "Here R2 is the one you choose, and VR2 is what Rtotal splits; keep snake_case."
    assert chat["formula"] == [r"V_{R2} = V \cdot \frac{R_2}{R_1 + R_2}"]  # the formula keeps its LaTeX


def test_the_guide_is_canned_and_bolds_the_learners_topics():
    from app.reply_composer import guide
    p = profile("hint")
    chat = guide(p)
    assert chat["kind"] == "guide" and chat["title"] == "How it works" and chat["formula"] is None
    start, end = chat["terms"][0]  # UTF-16 offsets, as JavaScript counts: the emojis take two
    assert chat["text"].encode("utf-16-le")[2 * start:2 * end].decode("utf-16-le") == "Hint"
    assert p == profile("hint")  # no profile changes
