// Builds the three.js scene graph for a grid board. Every grid element is its own node:
// a THREE.Group named by id, with userData { kind, id }, ready for picking and highlights.
import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { BAND_COLORS, resistorBands } from "./colorCode.js";
import { CELL, THEME } from "./theme.js";

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

function label(text, className, x = 0, y = 0) {
  const element = document.createElement("div");
  element.className = className;
  element.textContent = text;
  const object = new CSS2DObject(element);
  object.position.set(x, y, 0);
  return object;
}

// Symbol in a local frame: body at the origin, first pin at (+CELL, 0), second at (-CELL, 0).
function symbol(component) {
  const g = new THREE.Group();
  const lead = (from, to) => g.add(rect(Math.abs(to - from), 2.5, THEME.ink, (from + to) / 2, 0, 0.1));
  g.add(disc(3.5, THEME.ink, CELL, 0, 0.3), disc(3.5, THEME.ink, -CELL, 0, 0.3)); // pins

  if (component.type === "resistor") {
    lead(CELL, 22);
    lead(-22, -CELL);
    g.add(rect(46, 18, THEME.ink, 0, 0, 0.1), rect(43, 15, THEME.resistorBody, 0, 0, 0.2));
    // W and N rotate the symbol by 180° / 90°; mirror the bands so the code always reads
    // left to right or top to bottom, with the gold tolerance band last.
    const mirror = component.orientation === "W" || component.orientation === "N" ? -1 : 1;
    (resistorBands(component.value) ?? []).forEach((band, i) => {
      const x = -12 + i * 7 + (i === 3 ? 5 : 0);
      g.add(rect(4, 15, new THREE.Color(BAND_COLORS[band]), mirror * x, 0, 0.3));
    });
  } else if (component.type === "voltage_source") {
    lead(CELL, 5);
    lead(-5, -CELL);
    g.add(rect(2.5, 30, THEME.ink, 5, 0, 0.2)); // long plate: positive
    g.add(rect(5, 16, THEME.ink, -5, 0, 0.2)); // short plate: negative
    g.add(label("+", "editor-plus", 14, 14));
  } else {
    lead(CELL, 16);
    lead(-16, -CELL);
    g.add(disc(16, THEME.meterFill, 0, 0, 0.1), ring(14.5, 17, THEME.ink, 0.2));
    g.add(label(component.type === "ammeter" ? "A" : "V", "editor-meter-letter"));
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
  node.add(label(`${component.id}${valueText}`.trim(), "editor-label", vertical ? 30 : 0, vertical ? 0 : -24));
  if (READING_UNITS[component.type]) {
    const text = reading == null ? "--" : `${reading} ${READING_UNITS[component.type]}`;
    node.add(label(text, "editor-reading", vertical ? -36 : 0, vertical ? 0 : 26));
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
    const segment = rect(pa.distanceTo(pb), 3, THEME.wire, (pa.x + pb.x) / 2, (pa.y + pb.y) / 2);
    segment.rotation.z = Math.atan2(pb.y - pa.y, pb.x - pa.x);
    node.add(segment);
    points.add(a.join(",")).add(b.join(","));
  }
  for (const key of points) {
    const p = toWorld(key.split(",").map(Number));
    node.add(disc(2.5, THEME.wire, p.x, p.y, 0.1)); // round joints
  }
  return node;
}

function gridNode(columns, rows) {
  const node = new THREE.Group();
  node.name = "grid";
  node.userData = { kind: "grid" };
  const dots = new THREE.InstancedMesh(
    new THREE.CircleGeometry(1.6, 12),
    new THREE.MeshBasicMaterial({ color: THEME.dot }),
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
