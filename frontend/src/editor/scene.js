// Builds the three.js scene graph for a grid board. Every grid element is its own node:
// a THREE.Group named by id, with userData { kind, id }, ready for picking and highlights.
import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { BAND_COLORS, resistorBands } from "./colorCode.js";
import { CELL, STYLE } from "./style.js";

const PIN_NAMES = {
  voltage_source: ["positive", "negative"],
  resistor: ["a", "b"],
  voltmeter: ["positive", "negative"],
  ammeter: ["positive", "negative"],
};
// Direction the first pin points from the body, in grid units (row grows downward).
const DIRECTIONS = { N: [0, -1], S: [0, 1], E: [1, 0], W: [-1, 0] };
const UNITS = { voltage_source: "V", resistor: "Ω" };
const READING_UNITS = { voltmeter: "V", ammeter: "A" };

export const toWorld = ([col, row]) => new THREE.Vector3(col * CELL, -row * CELL, 0);

function rect(width, height, color, x = 0, y = 0, z = 0) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), new THREE.MeshBasicMaterial({ color }));
  mesh.position.set(x, y, z);
  return mesh;
}

function disc(radius, color, x = 0, y = 0, z = 0) {
  const mesh = new THREE.Mesh(new THREE.CircleGeometry(radius, 32), new THREE.MeshBasicMaterial({ color }));
  mesh.position.set(x, y, z);
  return mesh;
}

function ring(inner, outer, color, z = 0) {
  const mesh = new THREE.Mesh(new THREE.RingGeometry(inner, outer, 48), new THREE.MeshBasicMaterial({ color }));
  mesh.position.z = z;
  return mesh;
}

// HTML label at (x, y). CSS2DRenderer overwrites the outer element's transform to position it,
// so rotation goes on an inner span; `vertical` turns the text 90° to read bottom to top.
function label(text, className, x = 0, y = 0, size = STYLE.labels.size, vertical = false, anchorLeft = false) {
  const element = document.createElement("div");
  const inner = document.createElement("span");
  inner.className = className;
  inner.textContent = text;
  inner.style.fontSize = `${size}px`;
  inner.style.display = "inline-block";
  if (vertical) inner.style.transform = "rotate(-90deg)";
  // Anchor by the left edge instead of the center (horizontal text beside a vertical part).
  if (anchorLeft) inner.style.transform = "translateX(50%)";
  element.append(inner);
  const object = new CSS2DObject(element);
  object.position.set(x, y, 0);
  return object;
}

// Symbol in a local frame: body at the origin, first pin at (+CELL, 0), second at (-CELL, 0).
// Sizes and colors come from schematic-style.yaml.
function symbol(component) {
  const { pin, outline, resistor, battery, meter } = STYLE;
  const g = new THREE.Group();
  const lead = (from, to) => g.add(rect(Math.abs(to - from), pin.lead_thickness, pin.color, (from + to) / 2, 0, 0.1));
  g.add(disc(pin.connector_radius, pin.color, CELL, 0, 0.3), disc(pin.connector_radius, pin.color, -CELL, 0, 0.3));

  if (component.type === "resistor") {
    const half = resistor.length / 2;
    lead(CELL, half);
    lead(-half, -CELL);
    const t = outline.thickness * 2;
    g.add(rect(resistor.length, resistor.height, outline.color, 0, 0, 0.1));
    g.add(rect(resistor.length - t, resistor.height - t, resistor.fill, 0, 0, 0.2));
    // W and N rotate the symbol by 180° / 90°; mirror the bands so the code always reads
    // left to right or top to bottom, with the gold tolerance band last.
    const mirror = component.orientation === "W" || component.orientation === "N" ? -1 : 1;
    const step = resistor.length / 6;
    (resistorBands(component.value) ?? []).forEach((band, i) => {
      const x = -resistor.length / 2 + step * (i + 1) + (i === 3 ? step * 0.6 : 0);
      g.add(rect(resistor.band_width, resistor.height - t, BAND_COLORS[band], mirror * x, 0, 0.3));
    });
  } else if (component.type === "voltage_source") {
    const half = battery.gap / 2;
    lead(CELL, half);
    lead(-half, -CELL);
    g.add(rect(battery.long_plate_thickness, battery.long_plate, battery.positive_color, half, 0, 0.2));
    g.add(rect(battery.short_plate_thickness, battery.short_plate, battery.negative_color, -half, 0, 0.2));
    // Signs next to their plates, both on the same side of the lead (docs/images/battery-sketch.png):
    // + beside the long (positive) plate, − beside the short one, the plates between them.
    const along = half + battery.sign_plate_offset;
    g.add(label("+", "editor-sign editor-plus", along, battery.sign_wire_offset, battery.sign_size));
    g.add(label("−", "editor-sign editor-minus", -along, battery.sign_wire_offset, battery.sign_size));
  } else {
    lead(CELL, meter.radius);
    lead(-meter.radius, -CELL);
    const fill = component.type === "ammeter" ? meter.ammeter_fill : meter.voltmeter_fill;
    g.add(disc(meter.radius, outline.color, 0, 0, 0.1), disc(meter.radius - meter.outline_thickness, fill, 0, 0, 0.2));
    g.add(label(component.type === "ammeter" ? "A" : "V", "editor-meter-letter", 0, 0, meter.letter_size));
  }
  return g;
}
function componentNode(component, reading) {
  const [first, second] = PIN_NAMES[component.type].map((name) => component.pins[name]);
  const [dx, dy] = DIRECTIONS[component.orientation];
  const body = [first[0] - dx, first[1] - dy];

  const node = new THREE.Group();
  node.name = component.id;
  node.userData = { kind: "component", id: component.id, type: component.type };
  node.position.copy(toWorld(body)).setZ(2);
  const shape = symbol(component);
  shape.name = "symbol";
  shape.rotation.z = Math.atan2(-dy, dx); // grid y points down, world y points up
  node.add(shape);

  const vertical = dx === 0;
  const valueText = component.value != null ? ` ${component.value} ${UNITS[component.type] ?? ""}` : "";
  // Labels live in their own parent node: the ID on one side, the value (or a meter's live
  // reading) on the other — above / below a horizontal part, left / right of a vertical one.
  // Labels of vertical parts are rotated 90°, except meter readings, which stay horizontal.
  const labels = new THREE.Group();
  labels.name = "labels";
  const halfSize = {
    resistor: STYLE.resistor.height / 2,
    voltage_source: STYLE.battery.long_plate / 2,
  }[component.type] ?? STYLE.meter.radius;
  const clearance = halfSize + STYLE.labels.gap;
  const [idX, idY] = vertical ? [-clearance, 0] : [0, clearance];
  const [otherX, otherY] = vertical ? [clearance, 0] : [0, -clearance];
  const add = (name, object) => {
    object.name = name;
    labels.add(object);
  };
  add("id", label(component.id, "editor-label", idX, idY, STYLE.labels.size, vertical));
  if (READING_UNITS[component.type]) {
    const text = reading == null ? "--" : `${reading} ${READING_UNITS[component.type]}`;
    // Beside a vertical part the reading stays horizontal, anchored by its left edge.
    add("reading", label(text, "editor-reading", otherX, otherY, STYLE.labels.size, false, vertical));
  } else if (valueText) {
    add("value", label(valueText.trim(), "editor-label editor-value", otherX, otherY, STYLE.labels.size, vertical));
  }
  node.add(labels);
  return node;
}

function wireNode(wire) {
  const node = new THREE.Group();
  node.name = wire.id;
  node.userData = { kind: "wire", id: wire.id };
  node.position.z = 1;
  const points = new Set();
  for (const [a, b] of wire.segments) {
    const pa = toWorld(a);
    const pb = toWorld(b);
    const segment = rect(pa.distanceTo(pb), STYLE.wire.thickness, STYLE.wire.color, (pa.x + pb.x) / 2, (pa.y + pb.y) / 2);
    segment.rotation.z = Math.atan2(pb.y - pa.y, pb.x - pa.x);
    node.add(segment);
    points.add(a.join(",")).add(b.join(","));
  }
  for (const key of points) {
    const p = toWorld(key.split(",").map(Number));
    node.add(disc(STYLE.grid.connected_hole_radius, STYLE.wire.color, p.x, p.y, 0.1)); // round joints
  }
  return node;
}

function gridNode(columns, rows) {
  const node = new THREE.Group();
  node.name = "grid";
  node.userData = { kind: "grid" };
  const dots = new THREE.InstancedMesh(
    new THREE.CircleGeometry(STYLE.grid.hole_radius, 12),
    new THREE.MeshBasicMaterial({ color: STYLE.grid.hole_color }),
    columns * rows,
  );
  const m = new THREE.Matrix4();
  let i = 0;
  for (let row = 1; row <= rows; row++) {
    for (let col = 1; col <= columns; col++) dots.setMatrixAt(i++, m.makeTranslation(col * CELL, -row * CELL, 0));
  }
  node.add(dots);
  return node;
}

// The whole board as one group: grid, wires and components, each a named node.
export function buildBoard(board, readings = {}) {
  const root = new THREE.Group();
  root.name = "board";
  root.add(gridNode(board.grid.columns, board.grid.rows));
  for (const wire of board.wires ?? []) root.add(wireNode(wire));
  for (const component of board.components ?? []) root.add(componentNode(component, readings[component.id]));
  return root;
}

// World-space rectangle covering the grid with half a cell of margin.
export function boardBounds(board) {
  return {
    left: CELL * 0.5,
    right: CELL * (board.grid.columns + 0.5),
    top: -CELL * 0.5,
    bottom: -CELL * (board.grid.rows + 0.5),
  };
}

export function disposeTree(object) {
  object.traverse((child) => {
    child.geometry?.dispose();
    child.material?.dispose();
    if (child.isCSS2DObject) child.element.remove();
  });
}

// Drop target colors (docs/gui.md §4): blue where the item fits, red where it doesn't.
const TARGET_OK = 0x0969da;
const TARGET_BAD = 0xcf222e;

// Ghost of a dragged item plus its target points, from a placement plan (placement.js).
export function previewNode(item, planned, rotation) {
  const node = new THREE.Group();
  node.name = "preview";
  let ghost;
  if (item.kind === "part") {
    const [first, second] = PIN_NAMES[item.type];
    ghost = componentNode({ id: item.id, type: item.type, value: item.value, orientation: rotation,
                            pins: { [first]: planned.points[0], [second]: planned.points[2] } });
  } else {
    ghost = wireNode({ id: "preview-wire", segments: planned.segments });
  }
  ghost.traverse((o) => {
    if (o.material) {
      o.material.transparent = true;
      o.material.opacity = 0.45;
    }
  });
  ghost.children = ghost.children.filter((c) => !c.isCSS2DObject); // no labels on the ghost
  ghost.traverse((o) => { o.children = o.children.filter((c) => !c.isCSS2DObject); });
  node.add(ghost);
  const blocked = new Set(planned.blocked.map((p) => p.join(",")));
  for (const p of planned.pins) {
    const w = toWorld(p);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(5, 8, 32),
      new THREE.MeshBasicMaterial({ color: planned.valid && !blocked.has(p.join(",")) ? TARGET_OK : TARGET_BAD }),
    );
    ring.position.set(w.x, w.y, 3);
    node.add(ring);
  }
  return node;
}
