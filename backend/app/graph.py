"""Grid → graph conversion (docs/schematics.md §2)."""

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
