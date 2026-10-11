"""Grid → graph conversion (docs/schematics.md §2), nets, and leftover wire pieces (§6)."""

from .grid import PIN_NAMES


class UnionFind:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b) -> None:
        self.parent[self.find(a)] = self.find(b)


def to_graph(grid: dict) -> tuple[dict, dict[str, tuple]]:
    """Distill a valid grid into a graph.

    Returns the `graph` document and a map from each pin reference to its grid
    point, used to translate graph-level findings back to the grid.
    """
    points = UnionFind()
    for wire in grid.get("wires", []):
        for a, b in wire["segments"]:
            points.union(tuple(a), tuple(b))

    pin_points: dict[str, tuple] = {}
    groups: dict = {}
    components = []
    for c in grid.get("components", []):
        names = PIN_NAMES[c["type"]]
        node = {"id": c["id"], "type": c["type"], "pins": list(names)}
        if "value" in c:
            node["value"] = c["value"]
        components.append(node)
        for name in names:
            ref = f"{c['id']}.{name}"
            point = tuple(c["pins"][name])
            pin_points[ref] = point
            groups.setdefault(points.find(point), []).append(ref)

    edges = []
    for pins in groups.values():
        pins = sorted(pins)
        edges += [[pins[0], other] for other in pins[1:]]

    graph = {
        "components": components,
        "inventory": list(grid.get("inventory", [])),
        "edges": sorted(edges),
        "targets": dict(grid.get("targets", {})),
    }
    return graph, pin_points


def _pin_groups(components: list[dict], wires: list[dict]) -> set[frozenset]:
    """Which pins the wires join: one set of pin references per group of two or more."""
    points = UnionFind()
    for wire in wires:
        for a, b in wire["segments"]:
            points.union(tuple(a), tuple(b))
    groups: dict = {}
    for c in components:
        for name in PIN_NAMES[c["type"]]:
            groups.setdefault(points.find(tuple(c["pins"][name])), set()).add(f"{c['id']}.{name}")
    return {frozenset(g) for g in groups.values() if len(g) > 1}


def unused_wires(grid: dict) -> list[dict]:
    """Wire pieces that connect nothing: removing them leaves every pin connection unchanged
    (a stray piece, a dead-end stub, or one of two pieces that duplicate a connection).
    Checked one piece at a time against the pieces still kept, newest first, so of two
    duplicates only the later one (the learner's, not the task's) counts."""
    components = grid.get("components", [])
    kept = list(grid.get("wires", []))
    groups = _pin_groups(components, kept)
    unused = []
    for wire in reversed(kept):
        rest = [w for w in kept if w is not wire]
        if _pin_groups(components, rest) == groups:
            kept = rest
            unused.append(wire)
    return unused[::-1]


def assign_nets(graph: dict) -> dict[str, int]:
    """Map every pin reference to a net number; pins in no edge get their own net."""
    pins = UnionFind()
    for c in graph["components"]:
        for name in c["pins"]:
            pins.find(f"{c['id']}.{name}")
    for a, b in graph["edges"]:
        pins.union(a, b)
    numbers: dict = {}
    return {ref: numbers.setdefault(pins.find(ref), len(numbers)) for ref in sorted(pins.parent)}
