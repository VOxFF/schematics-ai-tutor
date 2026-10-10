"""Format validation for the `grid` document (docs/schematics.md §1)."""

from collections import Counter

PIN_NAMES = {
    "voltage_source": ("positive", "negative"),
    "resistor": ("a", "b"),
    "voltmeter": ("positive", "negative"),
    "ammeter": ("positive", "negative"),
}
METER_TYPES = {"voltmeter", "ammeter"}
# Direction the first pin points, seen from the body. Row 1 is the top row.
DIRECTIONS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


class InvalidGrid(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def component_points(component: dict) -> tuple[tuple, tuple, tuple]:
    """Return (first pin, body, second pin) points of a component."""
    first_name, second_name = PIN_NAMES[component["type"]]
    first = tuple(component["pins"][first_name])
    dx, dy = DIRECTIONS[component["orientation"]]
    body = (first[0] - dx, first[1] - dy)
    return first, body, tuple(component["pins"][second_name])


def wire_shape(segments: list) -> str | None:
    """Classify a wire piece as straight, corner, T or plus; None if invalid."""
    segs = {frozenset(map(tuple, s)) for s in segments}
    if len(segs) != len(segments) or not 1 <= len(segs) <= 4:
        return None
    if len(segs) == 1:
        return "straight"
    counts = Counter(p for s in segs for p in s)
    centers = [p for p, k in counts.items() if k == len(segs)]
    if len(centers) != 1:
        return None
    cx, cy = centers[0]
    arms = {(q[0] - cx, q[1] - cy) for s in segs for q in s if q != centers[0]}
    if len(arms) != len(segs):
        return None
    if len(segs) == 2:
        (ax, ay), (bx, by) = arms
        return "corner" if ax * bx + ay * by == 0 else None
    return "T" if len(segs) == 3 else "plus"


def validate_grid(grid: dict, allow_null_targets: bool = False) -> list[str]:
    """Return the list of format errors; empty when the grid is valid.

    `allow_null_targets` accepts targets whose value is still null, as in boards saved by
    learners before target values were computed; such a target simply can't be met.
    """
    errors: list[str] = []
    try:
        columns, rows = grid["grid"]["columns"], grid["grid"]["rows"]
    except (KeyError, TypeError):
        return ["grid: missing columns/rows"]

    def inside(p) -> bool:
        return (
            isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(v, int) for v in p)
            and 1 <= p[0] <= columns and 1 <= p[1] <= rows
        )

    ids: set[str] = set()

    def claim(item_id) -> None:
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"invalid id {item_id!r}")
        elif item_id in ids:
            errors.append(f"duplicate id {item_id}")
        ids.add(item_id)

    def check_value(item: dict) -> None:
        kind, value = item["type"], item.get("value")
        if kind == "resistor" and not (isinstance(value, (int, float)) and value > 0):
            errors.append(f"{item['id']}: resistor needs a positive value in ohms")
        if kind == "voltage_source" and not isinstance(value, (int, float)):
            errors.append(f"{item['id']}: voltage_source needs a value in volts")

    occupied: dict[tuple, str] = {}
    bodies: set[tuple] = set()
    meter_ids: dict[str, str] = {}

    for c in grid.get("components", []):
        cid = c.get("id")
        claim(cid)
        if c.get("type") not in PIN_NAMES:
            errors.append(f"{cid}: unknown type {c.get('type')!r}")
            continue
        check_value(c)
        if c["type"] in METER_TYPES:
            meter_ids[cid] = c["type"]
        names = PIN_NAMES[c["type"]]
        pins = c.get("pins", {})
        if set(pins) != set(names):
            errors.append(f"{cid}: pins must be {list(names)}")
            continue
        if c.get("orientation") not in DIRECTIONS:
            errors.append(f"{cid}: orientation must be one of N, E, S, W")
            continue
        if not all(inside(pins[n]) for n in names):
            errors.append(f"{cid}: pin outside the grid")
            continue
        first, body, second = component_points(c)
        dx, dy = DIRECTIONS[c["orientation"]]
        if second != (body[0] - dx, body[1] - dy):
            errors.append(
                f"{cid}: pins must be 2 apart in a straight line, "
                f"with {names[0]} pointing {c['orientation']}"
            )
            continue
        bodies.add(body)
        for p in (first, body, second):
            if p in occupied:
                errors.append(f"{cid}: overlaps {occupied[p]} at {list(p)}")
            occupied[p] = cid

    for item in grid.get("inventory", []):
        claim(item.get("id"))
        if item.get("type") not in PIN_NAMES:
            errors.append(f"{item.get('id')}: unknown type {item.get('type')!r}")
            continue
        check_value(item)
        if item["type"] in METER_TYPES:
            meter_ids[item["id"]] = item["type"]

    for w in grid.get("wires", []):
        wid = w.get("id")
        claim(wid)
        segments = w.get("segments", [])
        bad = False
        for s in segments:
            if not (isinstance(s, (list, tuple)) and len(s) == 2 and all(inside(p) for p in s)):
                errors.append(f"{wid}: segment {s} has a point outside the grid")
                bad = True
            elif abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]) != 1:
                errors.append(f"{wid}: segment {s} must join orthogonal neighbors")
                bad = True
            else:
                for p in map(tuple, s):
                    if p in bodies:
                        errors.append(f"{wid}: passes through the body of {occupied[p]} at {list(p)}")
                        bad = True
        if not bad and wire_shape(segments) is None:
            errors.append(f"{wid}: segments must form a straight, corner, T or + piece")

    for meter_id, target in grid.get("targets", {}).items():
        if meter_id not in meter_ids:
            errors.append(f"target {meter_id}: not a meter in components or inventory")
        if not isinstance(target, dict):
            errors.append(f"target {meter_id}: must be an object")
        elif target.get("value") is None and allow_null_targets:
            continue
        elif not isinstance(target.get("value"), (int, float)):
            errors.append(f"target {meter_id}: needs a numeric value")
        elif "tolerance" in target and not (
            isinstance(target["tolerance"], (int, float)) and target["tolerance"] >= 0
        ):
            errors.append(f"target {meter_id}: tolerance must be a non-negative number")

    return errors
