"""Deterministic evaluation of a grid: status, readings and issues (docs/schematics.md §4–§6)."""

from .graph import UnionFind, assign_nets, to_graph, unused_wires
from .grid import METER_TYPES
from .solver import solve

RESOLUTION = {"voltmeter": 0.01, "ammeter": 0.0001}
DECIMALS = {"voltmeter": 2, "ammeter": 4}

# Most severe first (docs/schematics.md §6). Issues missing from ISSUE_STATUS (unused_wire)
# are reported but never set the status.
STATUS_ORDER = ["short_circuit", "no_source", "overcurrent", "meter_misuse", "open_circuit", "floating_part", "bypassed"]
# Every status, worst first: progress is a move to the right (used for offering hints).
STATUS_RANK = [*STATUS_ORDER, "misplaced", "near_target", "solved"]
ISSUE_STATUS = {
    "short_circuit": "short_circuit",
    "no_source": "no_source",
    "overcurrent": "overcurrent",
    "ammeter_parallel": "meter_misuse",
    "voltmeter_series": "meter_misuse",
    "open_circuit": "open_circuit",
    "floating_part": "floating_part",
    "bypassed": "bypassed",
}


def round_reading(value: float, meter_type: str) -> float:
    return round(value, DECIMALS[meter_type]) + 0.0  # + 0.0 turns -0.0 into 0.0


def default_tolerance(value: float, meter_type: str) -> float:
    return max(0.02 * abs(value), RESOLUTION[meter_type])


def evaluate(grid: dict, settings: dict | None = None) -> dict:
    """Evaluate a format-valid grid. Returns {status, readings, issues}: the graph checks and
    solve (evaluate_graph), plus one `unused_wire` issue per leftover wire piece, found on the grid."""
    graph, pin_points = to_graph(grid)
    result = evaluate_graph(graph, pin_points, settings)
    # Leftover wire pieces don't change the circuit, so they don't change the status either.
    for wire in unused_wires(grid):
        ends = {tuple(p) for segment in wire["segments"] for p in segment}
        result["issues"].append({"code": "unused_wire", "component_ids": [], "wire_ids": [wire["id"]],
                                 "pins": [], "points": [list(p) for p in sorted(ends)]})
    return result


def evaluate_graph(graph: dict, pin_points: dict, settings: dict | None = None) -> dict:
    settings = settings or {}
    near_ratio = settings.get("near_target_ratio", 0.10)
    max_power = settings.get("resistor_max_power_w", 5)

    components = {c["id"]: c for c in graph["components"]}
    nets = assign_nets(graph)
    connected = {pin for edge in graph["edges"] for pin in edge}
    issues: list[dict] = []

    def issue(code: str, component_ids, pins) -> None:
        pins = list(pins)
        issues.append({
            "code": code,
            "component_ids": sorted(set(component_ids)),
            "pins": pins,
            "points": [list(pin_points[p]) for p in pins if p in pin_points],
        })

    def pin(cid: str, index: int) -> str:
        return f"{cid}.{components[cid]['pins'][index]}"

    sources = sorted(cid for cid, c in components.items() if c["type"] == "voltage_source")
    ammeters = [cid for cid, c in components.items() if c["type"] == "ammeter"]
    voltmeters = [cid for cid, c in components.items() if c["type"] == "voltmeter"]
    meters = [cid for cid, c in components.items() if c["type"] in METER_TYPES]

    if not sources:
        issue("no_source", [], [])

    # A source whose pins are joined through wires and ammeters only is shorted.
    zero_ohm = UnionFind()
    for cid in ammeters:
        zero_ohm.union(nets[pin(cid, 0)], nets[pin(cid, 1)])
    shorted = [s for s in sources if zero_ohm.find(nets[pin(s, 0)]) == zero_ohm.find(nets[pin(s, 1)])]
    for s in shorted:
        issue("short_circuit", [s], [pin(s, 0), pin(s, 1)])

    for cid, c in components.items():
        dangling = [f"{cid}.{name}" for name in c["pins"] if f"{cid}.{name}" not in connected]
        if dangling:
            issue("floating_part", [cid], dangling)
        elif c["type"] != "voltage_source" and nets[pin(cid, 0)] == nets[pin(cid, 1)]:
            issue("bypassed", [cid], [pin(cid, 0), pin(cid, 1)])

    resistor_spans = {
        frozenset((nets[pin(cid, 0)], nets[pin(cid, 1)])): cid
        for cid, c in components.items() if c["type"] == "resistor" and nets[pin(cid, 0)] != nets[pin(cid, 1)]
    }
    for cid in ammeters:
        across = resistor_spans.get(frozenset((nets[pin(cid, 0)], nets[pin(cid, 1)])))
        if across:
            issue("ammeter_parallel", [cid, across], [pin(cid, 0), pin(cid, 1)])

    readings: dict[str, float | None] = {m: None for m in meters}
    if not sources:
        readings = {m: 0.0 for m in meters}
    elif not shorted:
        ground = nets[pin(sources[0], 1)]
        solution = solve(graph["components"], nets, ground)
        if solution is None:  # contradictory sources: effectively a short
            issue("short_circuit", sources, [p for s in sources for p in (pin(s, 0), pin(s, 1))])
        else:
            voltages, currents = solution
            # Conducting islands: nets joined through parts that carry current. A voltmeter
            # whose leads sit on different islands (e.g. one lead connected to nothing) has no
            # circuit through it and reads 0; the solver's tiny pull of floating nets to ground
            # would otherwise turn that into the full source voltage.
            islands = UnionFind()
            for cid, c in components.items():
                if c["type"] != "voltmeter":
                    islands.union(nets[pin(cid, 0)], nets[pin(cid, 1)])
            for m in meters:
                if components[m]["type"] == "voltmeter":
                    joined = islands.find(nets[pin(m, 0)]) == islands.find(nets[pin(m, 1)])
                    raw = voltages[nets[pin(m, 0)]] - voltages[nets[pin(m, 1)]] if joined else 0.0
                else:
                    raw = currents[m]
                readings[m] = round_reading(raw, components[m]["type"])

            for cid, c in components.items():
                if c["type"] == "resistor":
                    drop = voltages[nets[pin(cid, 0)]] - voltages[nets[pin(cid, 1)]]
                    if drop * drop / c["value"] > max_power:
                        issue("overcurrent", [cid], [pin(cid, 0), pin(cid, 1)])

            if max(abs(currents[s]) for s in sources) < RESOLUTION["ammeter"]:
                blocking = []
                for vm in voltmeters:
                    if nets[pin(vm, 0)] == nets[pin(vm, 1)]:
                        continue
                    trial = solve(graph["components"], nets, ground, as_wire=frozenset({vm}))
                    if trial and max(abs(trial[1][s]) for s in sources) >= RESOLUTION["ammeter"]:
                        blocking.append(vm)
                for vm in blocking:
                    issue("voltmeter_series", [vm], [pin(vm, 0), pin(vm, 1)])
                if not blocking:
                    issue("open_circuit", sources, [p for s in sources for p in (pin(s, 0), pin(s, 1))])

    statuses = {ISSUE_STATUS.get(i["code"]) for i in issues}
    status = next((s for s in STATUS_ORDER if s in statuses), None)
    if status is None:
        status = target_status(graph, readings, near_ratio)
    return {"status": status, "readings": readings, "issues": issues}


def target_status(graph: dict, readings: dict, near_ratio: float) -> str:
    """solved / near_target / misplaced, for a circuit with no wiring issues."""
    types = {c["id"]: c["type"] for c in graph["components"] + graph.get("inventory", [])}
    near = False
    for meter, target in graph.get("targets", {}).items():
        value, reading = target["value"], readings.get(meter)
        if reading is None or value is None:
            return "misplaced"
        error = abs(reading - value)
        tolerance = target.get("tolerance", default_tolerance(value, types.get(meter, "voltmeter")))
        if error <= tolerance:
            continue
        if value != 0 and error <= near_ratio * abs(value):
            near = True
        else:
            return "misplaced"
    return "near_target" if near else "solved"
