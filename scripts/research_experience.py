"""Learner experience report: the 🔔 feedback conversations from the research records
(docs/design.md §5), per learner, as Markdown.

Reads the local research/ folder (./research.sh pull fills it from the server). Writes the report
to research/experience.md, which stays out of git like the records, and prints it.

Usage: python3 scripts/research_experience.py [research dir]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(folder: Path) -> list[dict]:
    records = []
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a line cut short by a crash or the size cap
    return sorted(records, key=lambda r: r.get("ts", ""))


def threads(records: list[dict]) -> tuple[str, list[dict]]:
    """The learner's name and their feedback threads: {ts, level, turns, end}."""
    name, level, found, current = "Anonymous", None, [], None
    for r in records:
        if r.get("type") == "session":
            name = r.get("name") or name
            level = ((r.get("level") or {}).get("curriculum") or {}).get("level")
        if r.get("type") != "experience":
            continue
        if r.get("prompt"):
            current = {"ts": r["ts"], "level": level, "turns": [("tutor", r.get("text", ""), "")], "end": "open"}
            found.append(current)
        elif current is None:
            continue
        elif "closed" in r:
            current["end"] = f"closed: {r['closed']}"
            current = None
        else:
            note = "handed to the tutor" if r.get("handoff") else ""
            current["turns"].append((r.get("role", "?"), r.get("text", ""), note))
            if r.get("done"):
                current["end"] = "finished"
                current = None
    return name, found


def report(directory: Path) -> str:
    learners = sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []
    lines = ["# Learner experience", ""]
    total = 0
    for folder in learners:
        name, found = threads(load(folder))
        if not found:
            continue
        total += len(found)
        lines += [f"## {name}", "", f"Learner `{folder.name}`, {len(found)} check-in(s).", ""]
        for t in found:
            when = t["ts"][:16].replace("T", " ") + " UTC"
            lines += [f"### {when}, Level {t['level'] or '?'} ({t['end']})", ""]
            for role, text, note in t["turns"]:
                who = "🔔 Tutor" if role == "tutor" else "Learner"
                lines.append(f"- **{who}:** {text}" + (f" _({note})_" if note else ""))
            lines.append("")
    if not total:
        lines.append("No feedback conversations yet.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "research"
    text = report(directory)
    if directory.is_dir():
        (directory / "experience.md").write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
