import { describe, expect, test } from "vitest";
import * as THREE from "three";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { resistorBands } from "./colorCode.js";
import { buildBoard, toWorld } from "./scene.js";
import { CELL, STYLE } from "./style.js";

describe("resistor color bands", () => {
  test.each([
    [20, ["red", "black", "black", "gold"]],
    [60, ["blue", "black", "black", "gold"]],
    [120, ["brown", "red", "brown", "gold"]],
    [4700, ["yellow", "violet", "red", "gold"]],
    [5, ["green", "black", "gold", "gold"]],
    [1, ["brown", "black", "gold", "gold"]],
  ])("%s ohm", (ohms, bands) => {
    expect(resistorBands(ohms)).toEqual(bands);
  });

  test("values that can't be drawn", () => {
    expect(resistorBands(0)).toBeNull();
    expect(resistorBands(-5)).toBeNull();
  });
});

describe("scene graph", () => {
  // A real board: the voltage divider example's complete circuit.
  const example = JSON.parse(readFileSync(resolve(process.cwd(), "../backend/data/examples/voltage_divider.json"), "utf8"));
  const board = { ...example.complete_board, inventory: [], targets: {} };

  test("every component and wire is its own named node", () => {
    const root = buildBoard(board, { VM1: 4 });
    const kinds = Object.fromEntries(root.children.map((n) => [n.name, n.userData.kind]));
    expect(kinds.grid).toBe("grid");
    for (const c of board.components) expect(kinds[c.id]).toBe("component");
    for (const w of board.wires) expect(kinds[w.id]).toBe("wire");
    expect(root.children).toHaveLength(1 + board.components.length + board.wires.length);
  });

  test("components sit on their body point and meters show readings", () => {
    const root = buildBoard(board, { VM1: 4 });
    const r1 = root.getObjectByName("R1"); // pins [5,3]-[7,3], body [6,3]
    expect([r1.position.x, r1.position.y]).toEqual([6 * CELL, -3 * CELL]);
    const texts = [];
    root.getObjectByName("VM1").traverse((o) => o.isCSS2DObject && texts.push(o.element.textContent));
    expect(texts).toContain("4 V");
    const r1Texts = [];
    r1.traverse((o) => o.isCSS2DObject && r1Texts.push(o.element.textContent));
    expect(r1Texts).toEqual(expect.arrayContaining(["R1", "40 Ω"]));
  });

  test("grid coordinates map to world space with row 1 at the top", () => {
    expect(toWorld([1, 1]).toArray()).toEqual([CELL, -CELL, 0]);
    expect(toWorld([12, 8]).y).toBeLessThan(toWorld([12, 1]).y);
  });
});

describe("band order on screen", () => {
  // World x (or -y for vertical) of each band, in reading order.
  const bandPositions = (orientation, pins) => {
    const board = {
      grid: { columns: 12, rows: 8 }, wires: [],
      components: [{ id: "R1", type: "resistor", value: 40, fixed: true, orientation, pins }],
    };
    const r1 = buildBoard(board).getObjectByName("R1");
    r1.updateMatrixWorld(true);
    const bands = [];
    r1.traverse((o) => o.isMesh && o.geometry.parameters?.width === STYLE.resistor.band_width && bands.push(o.getWorldPosition(new THREE.Vector3())));
    return bands;
  };

  test.each([
    ["E", { a: [7, 3], b: [5, 3] }, "x"],
    ["W", { a: [5, 3], b: [7, 3] }, "x"],
    ["S", { a: [6, 4], b: [6, 2] }, "-y"],
    ["N", { a: [6, 2], b: [6, 4] }, "-y"],
  ])("%s: digit bands first, gold last, reading left→right or top→bottom", (orientation, pins, axis) => {
    const order = bandPositions(orientation, pins).map((p) => (axis === "x" ? p.x : -p.y));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });
});

describe("schematic style", () => {
  test("the YAML style is loaded", () => {
    expect(STYLE.wire.thickness).toBeGreaterThan(0);
    expect(STYLE.meter.voltmeter_fill).toMatch(/^#[0-9a-f]{6}$/i);
  });

  test("sizes and colors come from the style", () => {
    const board = {
      grid: { columns: 12, rows: 8 },
      wires: [{ id: "W1", segments: [[[1, 1], [2, 1]]] }],
      components: [{ id: "V1", type: "voltage_source", value: 12, fixed: true, orientation: "N",
                     pins: { positive: [3, 3], negative: [3, 5] } }],
    };
    const root = buildBoard(board);
    const segment = root.getObjectByName("W1").children[0];
    expect(segment.geometry.parameters.height).toBe(STYLE.wire.thickness);

    const plates = [];
    root.getObjectByName("V1").traverse((o) => o.isMesh && o.geometry.parameters?.height === STYLE.battery.long_plate && plates.push(o));
    expect("#" + plates[0].material.color.getHexString()).toBe(STYLE.battery.positive_color.toLowerCase());

    const signs = [];
    root.getObjectByName("V1").traverse((o) => o.isCSS2DObject && signs.push(o.element.textContent));
    expect(signs).toEqual(expect.arrayContaining(["+", "−"]));
  });
});

describe("labels", () => {
  const labels = (node) => {
    const out = [];
    node.traverse((o) => o.isCSS2DObject && o.element.firstChild?.classList?.contains("editor-label") || o.isCSS2DObject && o.element.firstChild?.classList?.contains("editor-reading")
      ? out.push({ text: o.element.textContent, x: Math.round(o.position.x), y: Math.round(o.position.y),
                   rotated: o.element.firstChild.style.transform.includes("rotate") })
      : null);
    return out;
  };
  const one = (component, readings = {}) =>
    buildBoard({ grid: { columns: 12, rows: 8 }, wires: [], components: [component] }, readings).getObjectByName(component.id);

  test("horizontal part: ID above, value below, not rotated", () => {
    const [id, value] = labels(one({ id: "R1", type: "resistor", value: 40, orientation: "E", pins: { a: [7, 3], b: [5, 3] } }));
    expect(id).toMatchObject({ text: "R1", x: 0, rotated: false });
    expect(value).toMatchObject({ text: "40 Ω", x: 0, rotated: false });
    expect(id.y).toBeGreaterThan(0);
    expect(value.y).toBeLessThan(0);
  });

  test("vertical part: ID left, value right, both rotated", () => {
    const [id, value] = labels(one({ id: "V1", type: "voltage_source", value: 12, orientation: "N", pins: { positive: [3, 3], negative: [3, 5] } }));
    expect(id).toMatchObject({ text: "V1", y: 0, rotated: true });
    expect(value).toMatchObject({ text: "12 V", y: 0, rotated: true });
    expect(id.x).toBeLessThan(0);
    expect(value.x).toBeGreaterThan(0);
  });

  test("vertical meter: the ID rotates, the reading stays horizontal", () => {
    const [id, reading] = labels(one({ id: "AM1", type: "ammeter", orientation: "S", pins: { positive: [9, 5], negative: [9, 3] } }, { AM1: 0.2 }));
    expect(id).toMatchObject({ text: "AM1", rotated: true });
    expect(reading).toMatchObject({ text: "0.2 A", rotated: false });
    expect(id.x).toBeLessThan(0);
    expect(reading.x).toBeGreaterThan(0);
  });
});
