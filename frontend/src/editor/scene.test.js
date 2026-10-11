import { describe, expect, test } from "vitest";
import * as THREE from "three";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { resistorBands } from "./colorCode.js";
import { HIGHLIGHT_Z, SELECTION_Z, boardBounds, buildBoard, drawHighlight, floatingNode, inventoryNode, layoutInventory, outline, pickAt, sceneBounds, slotAnchor, toWorld } from "./scene.js";
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

  test("picking on the board: parts over wires, wires by their thin segments, not the grid", () => {
    const board = JSON.parse(readFileSync(resolve(process.cwd(), "../backend/data/examples/voltage_divider.json"), "utf8")).complete_board;
    const root = buildBoard(board);
    const part = board.components.find((c) => c.type === "resistor");
    const pin = toWorld(Object.values(part.pins)[0]);
    expect(pickAt([root], pin.x, pin.y)).toMatchObject({ kind: "component", id: part.id });
    const [a, b] = board.wires[0].segments[0].map(toWorld);
    const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    expect(pickAt([root], mid.x, mid.y)).toMatchObject({ kind: "wire", id: board.wires[0].id });
    const off = Math.abs(a.x - b.x) > 0 ? [0, 6] : [6, 0]; // beside the wire, across its direction
    expect(pickAt([root], mid.x + off[0], mid.y + off[1])).toBeNull();
  });
});

describe("selection outline", () => {
  const board = { grid: { columns: 8, rows: 6 }, inventory: [], targets: {}, wires: [],
                  components: [{ id: "R1", type: "resistor", value: 20, fixed: false, orientation: "E", pins: { a: [4, 3], b: [2, 3] } }] };

  test("an outline copies every shape, grown and behind it, in the selection color", () => {
    const root = buildBoard(board);
    const node = root.getObjectByName("R1");
    const shapes = [];
    node.traverse((o) => o.isMesh && shapes.push(o));
    outline(node);
    const copies = [];
    node.traverse((o) => o.isMesh && o.userData.outline && copies.push(o));
    expect(copies).toHaveLength(shapes.length);
    expect(copies.every((c) => c.getWorldPosition(new THREE.Vector3()).z === SELECTION_Z)).toBe(true);
    expect(copies[0].material.color.getHexString()).toBe(STYLE.selection.color.slice(1));
    const body = copies.find((c) => c.geometry.parameters.width === STYLE.resistor.length + 2 * STYLE.selection.width);
    expect(body).toBeDefined();
  });

  test("the outline doesn't grow the element's hit area", () => {
    const root = buildBoard(board);
    outline(root.getObjectByName("R1"));
    const body = toWorld([3, 3]);
    expect(pickAt([root], body.x, body.y + STYLE.resistor.height / 2 + 1)).toBeNull();
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

describe("tutor highlights", () => {
  const board = { grid: { columns: 8, rows: 6 }, inventory: [], targets: {},
                  wires: [{ id: "W1", segments: [[[4, 3], [6, 3]]] }],
                  components: [{ id: "R1", type: "resistor", value: 20, fixed: false, orientation: "E", pins: { a: [4, 3], b: [2, 3] } }] };
  const copies = (node) => {
    const found = [];
    node.traverse((o) => o.isMesh && o.userData.outline && found.push(o));
    return found;
  };

  test("a component or wire highlight outlines it in the style's color, behind a selection outline", () => {
    const root = buildBoard(board);
    expect(drawHighlight(root, { target: { component: "R1" }, style: "error" })).toBe(true);
    expect(drawHighlight(root, { target: { wire: "W1" }, style: "success" })).toBe(true);
    const r1 = copies(root.getObjectByName("R1"));
    expect(r1[0].material.color.getHexString()).toBe(STYLE.highlight.error.slice(1));
    // One layer under every wire and part, and under the selection outline.
    const depths = [...r1, ...copies(root.getObjectByName("W1"))].map((c) => c.getWorldPosition(new THREE.Vector3()).z);
    expect(depths.every((z) => Math.abs(z - HIGHLIGHT_Z) < 1e-9)).toBe(true);
    expect(HIGHLIGHT_Z).toBeLessThan(SELECTION_Z);
    expect(SELECTION_Z).toBeLessThan(root.getObjectByName("W1").position.z);
    expect(copies(root.getObjectByName("W1"))[0].material.color.getHexString()).toBe(STYLE.highlight.success.slice(1));
  });

  test("on the selected element, the highlight goes around the selection outline", () => {
    const root = buildBoard(board);
    drawHighlight(root, { target: { component: "R1" }, style: "attention" }, { kind: "component", id: "R1" });
    const grown = STYLE.resistor.length + 2 * (STYLE.highlight.width + STYLE.selection.width);
    expect(copies(root.getObjectByName("R1")).some((c) => c.geometry.parameters.width === grown)).toBe(true);
  });

  test("a point highlight is a ring around the grid point, not pickable", () => {
    const root = buildBoard(board);
    drawHighlight(root, { target: { point: [7, 5] }, style: "attention" });
    const ring = root.children.find((o) => o.geometry?.type === "RingGeometry");
    expect(ring.position.x).toBe(toWorld([7, 5]).x);
    expect(ring.position.z).toBe(HIGHLIGHT_Z);
    expect(ring.material.color.getHexString()).toBe(STYLE.highlight.attention.slice(1));
    expect(pickAt([root], ring.position.x, ring.position.y)).toBeNull();
  });

  test("a highlight on a missing element draws nothing", () => {
    const root = buildBoard(board);
    expect(drawHighlight(root, { target: { component: "R9" }, style: "error" })).toBe(false);
    expect(drawHighlight(root, { target: { wire: "R1" }, style: "error" })).toBe(false);
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

describe("label nodes and battery signs", () => {
  const v1 = () => buildBoard({ grid: { columns: 12, rows: 8 }, wires: [], components: [
    { id: "V1", type: "voltage_source", value: 12, orientation: "N", pins: { positive: [3, 3], negative: [3, 5] } }] }).getObjectByName("V1");

  test("each part has a symbol node and a labels node with named labels", () => {
    const node = v1();
    expect(node.children.map((c) => c.name)).toEqual(["symbol", "labels"]);
    expect(node.getObjectByName("labels").children.map((c) => c.name)).toEqual(["id", "value"]);
  });

  test("battery signs sit beside their plates, on the same side of the lead, clear of the labels", () => {
    const node = v1(); // vertical: positive pin [3,3] above the body [3,4]
    node.updateMatrixWorld(true);
    const world = (o) => o.getWorldPosition(new THREE.Vector3());
    const signs = {};
    node.getObjectByName("symbol").traverse((o) => o.isCSS2DObject && (signs[o.element.textContent] = world(o)));
    const body = new THREE.Vector3(3 * CELL, -4 * CELL, 0);
    expect(signs["+"].y).toBeGreaterThan(body.y); // + on the positive plate's side
    expect(signs["−"].y).toBeLessThan(body.y); // − on the negative plate's side
    expect(signs["+"].distanceTo(body)).toBeLessThan(CELL / 2); // next to the plates, not the pins
    expect(Math.sign(signs["+"].x - body.x)).toBe(Math.sign(signs["−"].x - body.x)); // same side
    const id = world(node.getObjectByName("labels").getObjectByName("id"));
    for (const sign of Object.values(signs)) expect(sign.distanceTo(id)).toBeGreaterThan(12);
  });
});

describe("inventory region (same scene as the board)", () => {
  const board = {
    grid: { columns: 12, rows: 8 }, components: [], wires: [], targets: {},
    inventory: [{ id: "R2", type: "resistor", value: 20 }, { id: "R3", type: "resistor", value: 4700 },
                { id: "AM2", type: "ammeter" }],
  };

  test("slots sit right of the grid in two columns: parts, then the five wire pieces", () => {
    const layout = layoutInventory(board);
    const grid = boardBounds(board);
    expect(layout.slots.map((s) => s.key)).toEqual([
      "part:R2", "part:R3", "part:AM2", "wire:straight-h", "wire:straight-v", "wire:corner", "wire:T", "wire:plus"]);
    expect(layout.slots.every((s) => s.x - s.w / 2 > grid.right)).toBe(true);
    expect(new Set(layout.slots.map((s) => s.x)).size).toBe(2); // two columns
    expect(layout.slots.find((s) => s.key === "part:R3").label).toBe("4.7 kΩ");
  });

  test("the camera bounds cover the grid and the inventory", () => {
    const layout = layoutInventory(board);
    const b = sceneBounds(board, layout);
    expect(b.left).toBe(boardBounds(board).left);
    expect(b.right).toBeGreaterThan(layout.bounds.right);
  });

  test("picking hits an inventory item by its drawn shape, not its slot's box", () => {
    const layout = layoutInventory(board);
    const inventory = inventoryNode(layout);
    const r3 = layout.slots.find((s) => s.key === "part:R3");
    const body = slotAnchor(r3);
    expect(pickAt([inventory], body.x, body.y)).toEqual({ kind: "inventory", key: "part:R3" });
    // Inside the slot's box but beside the symbol: nothing.
    expect(pickAt([inventory], body.x, body.y + STYLE.resistor.height)).toBeNull();
    // Grown by a tolerance, the edge of the body counts.
    const edge = body.y + STYLE.resistor.height / 2 + 1.5;
    expect(pickAt([inventory], body.x, edge)).toBeNull();
    expect(pickAt([inventory], body.x, edge, 2)).toEqual({ kind: "inventory", key: "part:R3" });
  });


  test("inventory parts are drawn with the board's own builder, so they're the same size", () => {
    const node = inventoryNode(layoutInventory(board));
    const slot = node.getObjectByName("part:R2");
    const part = slot.getObjectByName("R2");
    expect(part.getObjectByName("symbol")).toBeDefined();
    const bodies = [];
    part.traverse((o) => o.isMesh && o.geometry.parameters?.width === STYLE.resistor.length && bodies.push(o));
    expect(bodies).toHaveLength(1); // the same resistor body as on the board
  });
});

describe("dragging from the inventory", () => {
  const board = { grid: { columns: 12, rows: 8 }, components: [], wires: [], targets: {},
                  inventory: [{ id: "R2", type: "resistor", value: 20 }] };

  test("a lifted part leaves its slot empty", () => {
    const node = inventoryNode(layoutInventory(board), "part:R2");
    expect(node.getObjectByName("part:R2").getObjectByName("R2")).toBeUndefined();
  });

  test("the floating ghost sits under the pointer, without labels", () => {
    const ghost = floatingNode({ kind: "part", id: "R2", type: "resistor", value: 20 }, "E", 600, -100);
    expect([ghost.position.x, ghost.position.y]).toEqual([600, -100]);
    const labels = [];
    ghost.traverse((o) => o.isCSS2DObject && labels.push(o));
    expect(labels).toHaveLength(0);
  });

  test("grid and inventory share a vertical midline", () => {
    const tall = { ...board, inventory: Array.from({ length: 8 }, (_, i) => ({ id: `R${i + 2}`, type: "resistor", value: 20 })) };
    const layout = layoutInventory(tall);
    const g = boardBounds(tall);
    expect((layout.bounds.top + layout.bounds.bottom) / 2).toBeCloseTo((g.top + g.bottom) / 2);
    const b = sceneBounds(tall, layout);
    expect(b.top).toBe(layout.bounds.top); // the taller column sets the height
  });
});

describe("stable scale while placing parts", () => {
  test("reserved rows keep the scene bounds the same after a part leaves the inventory", () => {
    const start = { grid: { columns: 12, rows: 8 }, components: [], wires: [], targets: {},
                    inventory: [1, 2, 3].map((i) => ({ id: `R${i}`, type: "resistor", value: 20 })) };
    const placed = { ...start, inventory: start.inventory.slice(1) }; // R1 dragged onto the board
    const before = sceneBounds(start, layoutInventory(start, 3));
    const after = sceneBounds(placed, layoutInventory(placed, 3));
    expect(after).toEqual(before);
    // Without the reservation the column would shrink and the scale would jump.
    expect(sceneBounds(placed, layoutInventory(placed))).not.toEqual(before);
  });
});
