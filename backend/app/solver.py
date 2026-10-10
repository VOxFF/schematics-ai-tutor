"""DC modified nodal analysis over the graph's nets (docs/schematics.md §5)."""

import numpy as np

GMIN = 1e-12  # siemens to ground on every net, keeps floating nets solvable
MAX_CONDITION = 1e12


def solve(
    components: list[dict],
    nets: dict[str, int],
    ground: int,
    as_wire: frozenset[str] = frozenset(),
) -> tuple[dict[int, float], dict[str, float]] | None:
    """Solve the circuit.

    Returns (net voltages, branch currents) or None when the system is singular,
    e.g. contradictory sources. Branch currents exist for voltage sources and
    ammeters, positive when current flows into `positive` and out of `negative`.
    Components listed in `as_wire` are treated as 0 V branches (ideal wires).
    """
    nodes = sorted(set(nets.values()) - {ground})
    index = {net: i for i, net in enumerate(nodes)}
    branches = [
        c for c in components
        if c["type"] in ("voltage_source", "ammeter") or c["id"] in as_wire
    ]
    n, m = len(nodes), len(branches)
    a = np.zeros((n + m, n + m))
    z = np.zeros(n + m)
    a[range(n), range(n)] = GMIN

    def stamp(net_p: int, net_n: int, g: float) -> None:
        for p, q, sign in ((net_p, net_p, 1), (net_n, net_n, 1), (net_p, net_n, -1), (net_n, net_p, -1)):
            if p != ground and q != ground:
                a[index[p], index[q]] += sign * g

    for c in components:
        if c["type"] == "resistor" and c["id"] not in as_wire:
            stamp(nets[f"{c['id']}.a"], nets[f"{c['id']}.b"], 1.0 / c["value"])

    for k, c in enumerate(branches):
        first, second = c["pins"]
        row = n + k
        for net, sign in ((nets[f"{c['id']}.{first}"], 1), (nets[f"{c['id']}.{second}"], -1)):
            if net != ground:
                a[index[net], row] += sign
                a[row, index[net]] += sign
        if c["type"] == "voltage_source" and c["id"] not in as_wire:
            z[row] = c["value"]

    try:
        x = np.linalg.solve(a, z)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(x)) or np.linalg.cond(a) > MAX_CONDITION:
        return None

    voltages = {ground: 0.0} | {net: float(x[index[net]]) for net in nodes}
    currents = {c["id"]: float(x[n + k]) for k, c in enumerate(branches)}
    return voltages, currents
