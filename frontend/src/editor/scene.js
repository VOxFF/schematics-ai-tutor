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

function label(text, className, x = 0, y = 0, size = STYLE.labels.size) {
  const element = document.createElement("div");
  element.className = className;
  element.textContent = text;
  element.style.fontSize = `${size}px`;
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
    const off = battery.long_plate / 2 + 4;
    g.add(label("+", "editor-sign editor-plus", half + 6, off, battery.sign_size));
    g.add(label("−", "editor-sign editor-minus", -half - 6, off, battery.sign_size));
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
  shape.rotation.z = Math.atan2(-dy, dx); // grid y points down, world y points up
  node.add(shape);

  const vertical = dx === 0;
  const valueText = component.value != null ? ` ${component.value} ${UNITS[component.type] ?? ""}` : "";
  // Labels sit beside the symbol: right of vertical parts, below horizontal ones; readings opposite.
  const halfSize = {
    resistor: STYLE.resistor.height / 2,
    voltage_source: STYLE.battery.long_plate / 2,
  }[component.type] ?? STYLE.meter.radius;
  const clearance = halfSize + 12;
  node.add(label(`${component.id}${valueText}`.trim(), "editor-label", vertical ? clearance : 0, vertical ? 0 : -clearance));
  if (READING_UNITS[component.type]) {
    const text = reading == null ? "--" : `${reading} ${READING_UNITS[component.type]}`;
    node.add(label(text, "editor-reading", vertical ? -clearance - 6 : 0, vertical ? 0 : clearance));
  }
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
