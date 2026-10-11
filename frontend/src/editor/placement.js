// Placing parts and wire pieces on the grid (docs/gui.md §4). Pure functions: they compute
// the points a placement would occupy, whether it fits, and the resulting board.

export const PIN_NAMES = {
  voltage_source: ["positive", "negative"],
  resistor: ["a", "b"],
  voltmeter: ["positive", "negative"],
  ammeter: ["positive", "negative"],
};
const DIRECTIONS = { N: [0, -1], E: [1, 0], S: [0, 1], W: [-1, 0] };
const ORIENTATIONS = ["E", "S", "W", "N"]; // R cycles clockwise

// Wire palette: arms from the piece's anchor point, before rotation. Row grows downward.
export const WIRE_SHAPES = {
  straight: [[1, 0]],
  corner: [[1, 0], [0, 1]],
  T: [[1, 0], [-1, 0], [0, 1]],
  plus: [[1, 0], [-1, 0], [0, 1], [0, -1]],
};
export const WIRE_PALETTE = [
  { key: "straight-h", label: "Straight (horizontal)", shape: "straight", rotation: 0 },
  { key: "straight-v", label: "Straight (vertical)", shape: "straight", rotation: 1 },
  { key: "corner", label: "Corner", shape: "corner", rotation: 0 },
  { key: "T", label: "T", shape: "T", rotation: 0 },
  { key: "plus", label: "+", shape: "plus", rotation: 0 },
];

export const nextOrientation = (o) => ORIENTATIONS[(ORIENTATIONS.indexOf(o) + 1) % 4];
export const key = ([c, r]) => `${c},${r}`;

const rotate = ([dx, dy], times) => {
  let v = [dx, dy];
  for (let i = 0; i < times % 4; i++) v = [-v[1], v[0]]; // 90° clockwise on screen
  return v;
};

// Points of a component placed with its body at `body`: [first pin, body, second pin].
export function componentPoints(body, orientation) {
  const [dx, dy] = DIRECTIONS[orientation];
  return [[body[0] + dx, body[1] + dy], body, [body[0] - dx, body[1] - dy]];
}

export function wireSegments(shape, rotation, anchor) {
  return WIRE_SHAPES[shape].map((arm) => {
    const [dx, dy] = rotate(arm, rotation);
    return [anchor, [anchor[0] + dx, anchor[1] + dy]];
  });
}

function occupancy(board) {
  const parts = new Map(); // point -> component id (pins and bodies)
  const bodies = new Set();
  for (const c of board.components) {
    const [first, second] = PIN_NAMES[c.type].map((n) => c.pins[n]);
    const [dx, dy] = DIRECTIONS[c.orientation];
    const body = [first[0] - dx, first[1] - dy];
    for (const p of [first, body, second]) parts.set(key(p), c.id);
    bodies.add(key(body));
  }
  const wirePoints = new Set(board.wires.flatMap((w) => w.segments.flat().map(key)));
  return { parts, bodies, wirePoints };
}

const inside = (board, [c, r]) => c >= 1 && r >= 1 && c <= board.grid.columns && r <= board.grid.rows;

// Where a dragged item would go, and whether it fits. item: {kind: "part", ...} or {kind: "wire", shape}.
export function plan(board, item, point, rotation) {
  const { parts, bodies, wirePoints } = occupancy(board);
  if (item.kind === "part") {
    const points = componentPoints(point, rotation);
    const blocked = points.filter((p) => !inside(board, p) || parts.has(key(p)));
    if (wirePoints.has(key(points[1]))) blocked.push(points[1]); // a wire can't pass under a body
    return { points, pins: [points[0], points[2]], valid: blocked.length === 0, blocked };
  }
  const segments = wireSegments(item.shape, rotation, point);
  const points = [...new Map(segments.flat().map((p) => [key(p), p])).values()];
  const blocked = points.filter((p) => !inside(board, p) || bodies.has(key(p)));
  return { points, pins: points, segments, valid: blocked.length === 0, blocked };
}

function nextWireId(board) {
  const numbers = board.wires.map((w) => Number(/^W(\d+)$/.exec(w.id)?.[1] ?? 0));
  return `W${Math.max(0, ...numbers) + 1}`;
}

// The board after dropping `item` at `point`, or null when it doesn't fit.
export function place(board, item, point, rotation) {
  const p = plan(board, item, point, rotation);
  if (!p.valid) return null;
  if (item.kind === "part") {
    const [first, second] = PIN_NAMES[item.type];
    const component = { id: item.id, type: item.type, fixed: false, orientation: rotation,
                        pins: { [first]: p.points[0], [second]: p.points[2] } };
    if (item.value != null) component.value = item.value;
    return {
      ...board,
      components: [...board.components, component],
      inventory: board.inventory.filter((i) => i.id !== item.id),
    };
  }
  return { ...board, wires: [...board.wires, { id: nextWireId(board), segments: p.segments }] };
}
