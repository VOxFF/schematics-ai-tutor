"""TaskSpec: Claude's task proposal (docs/contract.md §2.2).

This module holds the JSON schema used for Claude's structured output, the
normalization of that output, the format checks, and the derivation of the
learner's task grid. Electrical checks (solvability, target values) belong to
the evaluator and are not done here.
"""

import uuid

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


def check_format(spec: dict, grid_limits: dict | None = None) -> list[str]:
    """Format errors in a normalized TaskSpec; empty when it is well formed."""
    errors = []
    board = spec.get("complete_board") or {}
    complete = {**board, "inventory": [], "targets": {}}
    errors += [f"complete_board: {e}" for e in validate_grid(complete)]

    limits = grid_limits or {}
    size = board.get("grid") or {}
    max_side = limits.get("grid_max_points")
    if max_side and (size.get("columns", 0) > max_side or size.get("rows", 0) > max_side):
        errors.append(f"complete_board: grid larger than {max_side} x {max_side}")
    if limits.get("grid_max_components") and len(board.get("components", [])) > limits["grid_max_components"]:
        errors.append("complete_board: too many components")
    if limits.get("grid_max_wires") and len(board.get("wires", [])) > limits["grid_max_wires"]:
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
        elif mid in spec.get("removed_ids", []):
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


def derive_task_board(spec: dict) -> dict:
    """The learner's starting grid: removed parts go to the inventory, removed wires disappear."""
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
        # Target values are computed by the evaluator (next step); until then they are null.
        "targets": {mid: {"value": None} for mid in spec["target_meter_ids"]},
    }


def build_level(spec: dict, skill_level: int) -> dict:
    """A `Level` for the frontend (docs/contract.md, data model)."""
    return {
        "id": f"gen-{uuid.uuid4().hex[:8]}",
        "order": skill_level,
        "title": spec["title"],
        "concept": spec["concept"],
        "intro": spec["intro"],
        "board": derive_task_board(spec),
    }
