"""TaskSpec: Claude's task proposal (docs/contract.md §2.2).

This module holds the JSON schema used for Claude's structured output, the
normalization of that output, the validation stages (docs/schematics.md §3),
target computation, and the derivation of the learner's task grid.
"""

import uuid

from .evaluate import RESOLUTION, evaluate
from .curriculum import check_centered, check_level
from .graph import assign_nets, to_graph
from .grid import METER_TYPES, PIN_NAMES, validate_grid

COMPONENT_TYPES = sorted(PIN_NAMES)
ALL_PIN_NAMES = sorted({name for names in PIN_NAMES.values() for name in names})

_POINT = {"type": "array", "items": {"type": "integer"}}
_NULLABLE_POINT = {"anyOf": [_POINT, {"type": "null"}]}
_NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_COMPONENT = _object({
    "id": {"type": "string"},
    "type": {"type": "string", "enum": COMPONENT_TYPES},
    "value": _NULLABLE_NUMBER,
    "fixed": {"type": "boolean"},
    "orientation": {"type": "string", "enum": ["N", "E", "S", "W"]},
    # Every pin name is listed; the ones that don't apply to the type are null.
    "pins": _object({name: _NULLABLE_POINT for name in ALL_PIN_NAMES}),
})
_WIRE = _object({"id": {"type": "string"}, "segments": {"type": "array", "items": {"type": "array", "items": _POINT}}})
_INVENTORY_ITEM = _object({"id": {"type": "string"}, "type": {"type": "string", "enum": COMPONENT_TYPES}, "value": _NULLABLE_NUMBER})

TASK_SPEC_SCHEMA = _object({
    "concept": {"type": "string"},
    "title": {"type": "string"},
    "intro": {"type": "string"},
    "complete_board": _object({
        "grid": _object({"columns": {"type": "integer"}, "rows": {"type": "integer"}}),
        "components": {"type": "array", "items": _COMPONENT},
        "wires": {"type": "array", "items": _WIRE},
    }),
    "removed_ids": {"type": "array", "items": {"type": "string"}},
    "decoys": {"type": "array", "items": _INVENTORY_ITEM},
    "target_meter_ids": {"type": "array", "items": {"type": "string"}},
    "difficulty": {"type": "integer"},
    "rationale": {"type": "string"},
})


def normalize(spec: dict) -> dict:
    """Drop the null placeholders that the structured-output schema requires."""
    spec = dict(spec)
    board = dict(spec.get("complete_board") or {})
    components = []
    for c in board.get("components", []):
        c = {k: v for k, v in c.items() if not (k == "value" and v is None)}
        c["pins"] = {k: v for k, v in (c.get("pins") or {}).items() if v is not None}
        components.append(c)
    board["components"] = components
    spec["complete_board"] = board
    spec["decoys"] = [{k: v for k, v in d.items() if not (k == "value" and v is None)} for d in spec.get("decoys", [])]
    return spec


def check_format(spec: dict, grid_limits: dict | None = None, removed_targets_allowed: bool = False) -> list[str]:
    """Format errors in a normalized TaskSpec; empty when it is well formed."""
    errors = []
    board = spec.get("complete_board") or {}
    complete = {**board, "inventory": [], "targets": {}}
    errors += [f"complete_board: {e}" for e in validate_grid(complete)]

    limits = grid_limits or {}
    size = board.get("grid") or {}
    max_side = limits.get("max_points")
    if max_side and (size.get("columns", 0) > max_side or size.get("rows", 0) > max_side):
        errors.append(f"complete_board: grid larger than {max_side} x {max_side}")
    if limits.get("max_components") and len(board.get("components", [])) > limits["max_components"]:
        errors.append("complete_board: too many components")
    if limits.get("max_wires") and len(board.get("wires", [])) > limits["max_wires"]:
        errors.append("complete_board: too many wire pieces")

    components = {c.get("id"): c for c in board.get("components", [])}
    wire_ids = {w.get("id") for w in board.get("wires", [])}
    for rid in spec.get("removed_ids", []):
        if rid in components:
            if components[rid].get("fixed"):
                errors.append(f"removed_ids: {rid} is fixed and can't be removed")
        elif rid not in wire_ids:
            errors.append(f"removed_ids: {rid} is not a component or wire of the complete board")
    if not spec.get("removed_ids"):
        errors.append("removed_ids: at least one part or wire must be removed")

    if not spec.get("target_meter_ids"):
        errors.append("target_meter_ids: at least one target meter is required")
    for mid in spec.get("target_meter_ids", []):
        meter = components.get(mid)
        if meter is None or meter.get("type") not in METER_TYPES:
            errors.append(f"target_meter_ids: {mid} is not a meter on the complete board")
        elif mid in spec.get("removed_ids", []) and not removed_targets_allowed:
            errors.append(f"target_meter_ids: {mid} is removed, so it can't be a target")

    if not isinstance(spec.get("difficulty"), int) or not 1 <= spec["difficulty"] <= 5:
        errors.append("difficulty: must be an integer from 1 to 5")
    for field in ("concept", "title", "intro"):
        if not str(spec.get(field) or "").strip():
            errors.append(f"{field}: must not be empty")

    if not errors:
        # Target values are still null here, so the task grid is checked without them.
        task = {**derive_task_board(spec), "targets": {}}
        errors += [f"task grid: {e}" for e in validate_grid(task)]
    return errors


def derive_task_board(spec: dict, targets: dict | None = None) -> dict:
    """The learner's starting grid: removed parts go to the inventory, removed wires disappear.

    `targets` are the computed target values; without them, values are null.
    """
    board = spec["complete_board"]
    removed = set(spec.get("removed_ids", []))
    components = [c for c in board["components"] if c["id"] not in removed]
    inventory = [
        {k: c[k] for k in ("id", "type", "value") if k in c}
        for c in board["components"] if c["id"] in removed
    ] + list(spec.get("decoys", []))
    return {
        "grid": dict(board["grid"]),
        "components": components,
        "inventory": sorted(inventory, key=lambda item: item["id"]),
        "wires": [w for w in board["wires"] if w["id"] not in removed],
        "targets": targets or {mid: {"value": None} for mid in spec["target_meter_ids"]},
    }


def complete_grid(spec: dict) -> dict:
    return {**spec["complete_board"], "inventory": [], "targets": {}}


def check_solved_board(spec: dict, settings: dict | None = None) -> tuple[list[str], dict]:
    """Stage 2: the complete board is a working circuit; returns (errors, target values)."""
    result = evaluate(complete_grid(spec), settings)
    errors = []
    if result["issues"]:
        problems = ", ".join(f"{i['code']} ({', '.join(i['component_ids'] or i.get('wire_ids', [])) or 'circuit'})" for i in result["issues"])
        errors.append(f"complete board is not a working circuit: {problems}")
    types = {c["id"]: c["type"] for c in spec["complete_board"]["components"]}
    targets = {}
    for mid in spec["target_meter_ids"]:
        reading = result["readings"].get(mid)
        if reading is None or abs(reading) < RESOLUTION[types[mid]]:
            errors.append(f"target meter {mid} reads {reading}; a target must read a non-zero value")
        else:
            targets[mid] = {"value": reading}
    return errors, targets


def check_reconstruction(spec: dict, task_board: dict) -> list[str]:
    """Stage 3a: the complete board is exactly the task board plus the removed elements."""
    errors = []
    complete = spec["complete_board"]
    removed = set(spec["removed_ids"])
    task_components = {c["id"]: c for c in task_board["components"]}
    task_wires = {w["id"]: w for w in task_board["wires"]}
    inventory = {i["id"]: i for i in task_board["inventory"]}
    for c in complete["components"]:
        if c["id"] in removed:
            item = inventory.get(c["id"])
            if item is None or item["type"] != c["type"] or item.get("value") != c.get("value"):
                errors.append(f"removed part {c['id']} is not in the inventory with the same type and value")
        elif task_components.get(c["id"]) != c:
            errors.append(f"part {c['id']} differs between the task board and the complete board")
    for w in complete["wires"]:
        if w["id"] not in removed and task_wires.get(w["id"]) != w:
            errors.append(f"wire {w['id']} differs between the task board and the complete board")
    complete_ids = {c["id"] for c in complete["components"]} | {w["id"] for w in complete["wires"]}
    extra = (set(task_components) | set(task_wires)) - complete_ids
    if extra:
        errors.append(f"task board has elements not in the complete board: {sorted(extra)}")
    return errors


def check_not_solved(task_board: dict, settings: dict | None = None) -> list[str]:
    """Stage 3b: the task board alone must not meet the targets."""
    if evaluate(task_board, settings)["status"] == "solved":
        return ["the task is already solved without the removed parts; remove something that matters"]
    return []


def signature(spec: dict) -> str:
    """A fingerprint of the complete circuit, independent of IDs and layout.

    Each net is described by the parts touching it ("resistor:60"); the sorted list of nets,
    plus the target meter types, identifies the circuit. Series and parallel versions of the
    same parts differ; moving parts around the grid does not.
    """
    graph, _ = to_graph(complete_grid(spec))
    nets = assign_nets(graph)
    label = {c["id"]: f"{c['type']}:{c.get('value', '')}" for c in graph["components"]}
    by_net: dict[int, list[str]] = {}
    for pin, net in nets.items():
        by_net.setdefault(net, []).append(label[pin.split(".")[0]])
    types = {c["id"]: c["type"] for c in graph["components"]}
    targets = sorted(types[m] for m in spec["target_meter_ids"])
    return "|".join(sorted(",".join(sorted(parts)) for parts in by_net.values())) + "|targets:" + ",".join(targets)


def check_not_repeat(spec: dict, recent_signatures) -> list[str]:
    """Stage 4: not the same circuit as a recent task."""
    if signature(spec) in set(recent_signatures):
        return ["this task repeats a recent one (same parts and connections); design a different circuit"]
    return []


def validate(spec: dict, grid_limits: dict | None = None, settings: dict | None = None,
             recent_signatures=(), level: dict | None = None) -> dict:
    """All validation stages for a normalized TaskSpec.

    `level` = {"rules", "task", "grid"} adds the curriculum checks (level fit, centering).
    Returns {"errors", "readings", "targets", "board"}; `board` is the learner's task grid
    with computed targets, present only when there are no errors.
    """
    rules = (level or {}).get("rules") or {}
    errors = check_format(spec, grid_limits, rules.get("removed_targets_allowed", False))
    if not errors and level:
        errors = check_level(spec, rules, level["task"], level["grid"]) + check_centered(spec)
    if errors:
        return {"errors": errors, "readings": {}, "targets": {}, "board": None}
    readings = evaluate(complete_grid(spec), settings)["readings"]
    errors, targets = check_solved_board(spec, settings)
    if errors:
        return {"errors": errors, "readings": readings, "targets": {}, "board": None}
    board = derive_task_board(spec, targets)
    errors = check_reconstruction(spec, board) + check_not_solved(board, settings) + check_not_repeat(spec, recent_signatures)
    return {"errors": errors, "readings": readings, "targets": targets, "board": None if errors else board}


def build_level(spec: dict, skill_level: int, board: dict | None = None, curriculum: dict | None = None) -> dict:
    """A `Level` for the frontend (docs/contract.md, data model)."""
    return {
        "curriculum": curriculum,  # {level, task, tasks, concept}; None outside the curriculum
        "id": f"gen-{uuid.uuid4().hex[:8]}",
        "order": skill_level,
        "title": spec["title"],
        "concept": spec["concept"],
        "intro": spec["intro"],
        "board": board or derive_task_board(spec),
        "difficulty": spec["difficulty"],
        # Stored in the learner's history (TaskSummary) for the next generation and the repeat check.
        "shape": shape(spec),
        "signature": signature(spec),
    }


def shape(spec: dict) -> str:
    """Short parts summary of the complete circuit, e.g. "V + 2R + VM"."""
    short = {"voltage_source": "V", "resistor": "R", "voltmeter": "VM", "ammeter": "AM"}
    counts: dict[str, int] = {}
    for c in spec["complete_board"]["components"]:
        counts[short[c["type"]]] = counts.get(short[c["type"]], 0) + 1
    return " + ".join(f"{n if n > 1 else ''}{key}" for key, n in counts.items())
