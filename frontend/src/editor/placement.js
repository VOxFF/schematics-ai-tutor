// Placing parts and wire pieces on the grid (docs/gui.md §4). Pure functions: they compute
// the points a placement would occupy, whether it fits, and the resulting board; lift a placed
// element off the board so it can be dragged elsewhere; and rotate or remove a selected one.

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

// The task's wire palette (docs/schematics.md §3): straight pieces always, the other shapes only
// when `shapes` (Level.wire_shapes) lists them. Without it, an older level, the full palette.
export const wirePalette = (shapes) =>
  shapes ? WIRE_PALETTE.filter((w) => w.shape === "straight" || shapes.includes(w.shape)) : WIRE_PALETTE;

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

// Segments of a dragged wire item: a palette piece (`shape`) or a placed wire picked up from
// the board (`segments` relative to its anchor), rotated `rotation` quarter turns.
export function itemSegments(item, rotation, anchor) {
  if (!item.segments) return wireSegments(item.shape, rotation, anchor);
  const at = (p) => {
    const [dx, dy] = rotate(p, rotation);
    return [anchor[0] + dx, anchor[1] + dy];
  };
  return item.segments.map(([a, b]) => [at(a), at(b)]);
}

// Body point of a placed component.
export function bodyOf(component) {
  const [dx, dy] = DIRECTIONS[component.orientation];
  const first = component.pins[PIN_NAMES[component.type][0]];
  return [first[0] - dx, first[1] - dy];
}

// Pick up a placed element: the drag item, its starting rotation and anchor, and the board
// without it. Null for fixed parts and for wires that came with the task (`startBoard`).
export function lift(board, hit, startBoard) {
  if (hit.kind === "component") {
    const c = board.components.find((x) => x.id === hit.id);
    if (!c || c.fixed) return null;
    const item = { kind: "part", id: c.id, type: c.type };
    if (c.value != null) item.value = c.value;
    return { item, rotation: c.orientation, anchor: bodyOf(c),
             base: { ...board, components: board.components.filter((x) => x !== c) } };
  }
  const w = board.wires.find((x) => x.id === hit.id);
  if (!w || startBoard?.wires?.some((x) => x.id === w.id)) return null;
  const anchor = w.segments[0][0];
  const relative = (p) => [p[0] - anchor[0], p[1] - anchor[1]];
  return { item: { kind: "wire", id: w.id, segments: w.segments.map(([a, b]) => [relative(a), relative(b)]) },
           rotation: 0, anchor, base: { ...board, wires: board.wires.filter((x) => x !== w) } };
}

function occupancy(board) {
  const parts = new Map(); // point -> component id (pins and bodies)
  const bodies = new Set();
  for (const c of board.components) {
    const [first, second] = PIN_NAMES[c.type].map((n) => c.pins[n]);
    const body = bodyOf(c);
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
  const segments = itemSegments(item, rotation, point);
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
  // A wire moved on the board keeps its id; a new piece gets the next one.
  return { ...board, wires: [...board.wires, { id: item.id ?? nextWireId(board), segments: p.segments }] };
}

// The selected element `selection` ({ kind: "component" | "wire", id }) turned a quarter
// clockwise in place (a part around its body, a wire piece around its anchor). Null when
// it isn't editable or the turned element doesn't fit.
export function rotateSelected(board, selection, startBoard) {
  const lifted = lift(board, selection, startBoard);
  if (!lifted) return null;
  const rotation = lifted.item.kind === "part" ? nextOrientation(lifted.rotation) : 1;
  return place(lifted.base, lifted.item, lifted.anchor, rotation);
}

// The board without the selected element: a part goes back to the inventory, a wire piece
// is deleted. Null when it isn't editable.
export function removeSelected(board, selection, startBoard) {
  const lifted = lift(board, selection, startBoard);
  if (!lifted) return null;
  if (lifted.item.kind === "wire") return lifted.base;
  const { kind: _kind, ...part } = lifted.item;
  return { ...lifted.base, inventory: [...lifted.base.inventory, part] };
}
