"""Repository integrity checks, run by ./check.sh locally and in CI.

Checks: markdown links and anchors, config.yaml and ratelimiting.yaml vs. the documented defaults,
the layout snapshot in docs/design.md, secrets, stale design terms, and the
readable JSON format of tracked .json files.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.jsonfmt import dumps  # noqa: E402
DESIGN = ROOT / "docs" / "design.md"

# Terms from superseded design decisions that must not reappear in the docs.
STALE_TERMS = [
    "breadboard",
    "liveHighlights",
    "backend/config.yaml",
    "goal_met",
    "tutor.delta",
    "same_strip",
    "floating_component",
    "HoleId",
    "slotAt",
    "MAX_CONDITION",
    "check.yml",  # renamed ci.yml when deploys moved before the merge
    "claude_calls_per_day",  # the budget is in dollars: claude_budget.usd_per_day
    "tutor_calls_per_session_per_min",  # ratelimiting.yaml: tutor.calls_per_session_per_min
    "grid_max_points",  # ratelimiting.yaml: grid.max_points
]
# Split so this file doesn't match its own secret scan.
KEY_PATTERN = re.compile("sk-" + r"ant-[A-Za-z0-9_\-]{8,}")
FORBIDDEN_PATHS = [
    re.compile(r"^backend/keys/(?!README\.md$)"),
    re.compile(r"^\.env$"),
    re.compile(r"^logs/"),
    re.compile(r"^\.run/"),
]

errors: list[str] = []


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.split()


def slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def check_links(md_files: list[str]) -> None:
    for name in md_files:
        path = ROOT / name
        for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text()):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, anchor = target.partition("#")
            linked = (path.parent / file_part).resolve() if file_part else path
            if not linked.exists():
                errors.append(f"{name}: broken link {target}")
            elif anchor and linked.suffix == ".md":
                headings = re.findall(r"^#+ (.+)$", linked.read_text(), re.M)
                if anchor not in {slug(h) for h in headings}:
                    errors.append(f"{name}: missing anchor {target}")


def check_config() -> None:
    match = re.search(r"## 6\. Configuration.*?```yaml\n(.*?)```", DESIGN.read_text(), re.S)
    if not match:
        errors.append("docs/design.md: no config block in §5")
        return
    documented = yaml.safe_load(match.group(1))
    actual = yaml.safe_load((ROOT / "config.yaml").read_text())
    for section, value in documented.items():
        if section == "pricing":  # the doc shows an excerpt only
            continue
        if actual.get(section) != value:
            errors.append(f"config.yaml: section '{section}' differs from docs/design.md §6")
    for section in actual:
        if section not in documented:
            errors.append(f"config.yaml: section '{section}' is not documented in docs/design.md §6")


def check_rate_limits() -> None:
    """ratelimiting.yaml must match the block in docs/design.md §5 exactly."""
    match = re.search(r"### Rate limits.*?```yaml\n(.*?)```", DESIGN.read_text(), re.S)
    if not match:
        errors.append("docs/design.md: no ratelimiting.yaml block in §4")
        return
    if yaml.safe_load(match.group(1)) != yaml.safe_load((ROOT / "ratelimiting.yaml").read_text()):
        errors.append("ratelimiting.yaml differs from docs/design.md §5")


def check_layout(tracked: list[str]) -> None:
    match = re.search(r"## 8\. Repository layout.*?```text\n(.*?)```", DESIGN.read_text(), re.S)
    if not match:
        errors.append("docs/design.md: no layout snapshot in §7")
        return
    stack: list[str] = []
    listed_top: set[str] = set()
    for line in match.group(1).splitlines()[1:]:  # skip the repo-name line
        m = re.match(r"^((?:│   |    )*)[├└]── (\S+)", line)
        if not m:
            continue
        depth = len(m.group(1)) // 4
        name = m.group(2).rstrip("/")
        stack = stack[:depth] + [name]
        path = "/".join(stack)
        if depth == 0:
            listed_top.add(name)
        if "(gitignored)" in line:
            continue
        if not any(t == path or t.startswith(path + "/") for t in tracked):
            errors.append(f"docs/design.md §8: '{path}' is in the snapshot but not in the repo")
    for top in {t.split("/")[0] for t in tracked}:
        if top not in listed_top:
            errors.append(f"docs/design.md §8: '{top}' is in the repo but missing from the snapshot")


def check_secrets(tracked: list[str]) -> None:
    for name in tracked:
        if any(p.search(name) for p in FORBIDDEN_PATHS):
            errors.append(f"secrets: '{name}' must not be tracked")
        path = ROOT / name
        try:
            if KEY_PATTERN.search(path.read_text()):
                errors.append(f"secrets: '{name}' contains something that looks like an API key")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            pass


def check_stale_terms(md_files: list[str]) -> None:
    for name in md_files:
        text = (ROOT / name).read_text().lower()
        for term in STALE_TERMS:
            if term.lower() in text:
                errors.append(f"{name}: stale term '{term}'")


# Files written by tools in their own format (npm rewrites these on every install).
TOOL_MANAGED_JSON = {"package.json", "package-lock.json"}


def check_json_format(tracked: list[str]) -> None:
    for name in tracked:
        if name.endswith(".json") and Path(name).name not in TOOL_MANAGED_JSON:
            text = (ROOT / name).read_text()
            if text != dumps(json.loads(text)):
                errors.append(f"{name}: not in the readable JSON format (backend/app/jsonfmt.py)")


def main() -> int:
    tracked = tracked_files()
    md_files = [t for t in tracked if t.endswith(".md")]
    check_links(md_files)
    check_config()
    check_rate_limits()
    check_layout(tracked)
    check_secrets(tracked)
    check_stale_terms(md_files)
    check_json_format(tracked)
    for e in errors:
        print(f"FAIL {e}")
    print(f"integrity: {len(errors)} problem(s)" if errors else "integrity: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
