import { describe, expect, test } from "vitest";
import { componentPoints, nextOrientation, place, plan, wireSegments } from "./placement.js";

const board = () => ({
  grid: { columns: 8, rows: 6 },
  components: [{ id: "R1", type: "resistor", value: 60, fixed: true, orientation: "E", pins: { a: [4, 2], b: [2, 2] } }],
  wires: [{ id: "W3", segments: [[[5, 4], [6, 4]]] }],
  inventory: [{ id: "R2", type: "resistor", value: 20 }],
  targets: {},
});
const R2 = { kind: "part", id: "R2", type: "resistor", value: 20 };

describe("geometry", () => {
  test("component points follow the orientation", () => {
    expect(componentPoints([5, 3], "E")).toEqual([[6, 3], [5, 3], [4, 3]]);
    expect(componentPoints([5, 3], "N")).toEqual([[5, 2], [5, 3], [5, 4]]);
  });

  test("R cycles orientations clockwise", () => {
    expect(["E", "S", "W", "N"].map(nextOrientation)).toEqual(["S", "W", "N", "E"]);
  });

  test("wire pieces rotate around their anchor", () => {
    expect(wireSegments("straight", 0, [2, 2])).toEqual([[[2, 2], [3, 2]]]);
    expect(wireSegments("straight", 1, [2, 2])).toEqual([[[2, 2], [2, 3]]]);
    expect(wireSegments("corner", 0, [2, 2])).toEqual([[[2, 2], [3, 2]], [[2, 2], [2, 3]]]);
    expect(wireSegments("T", 1, [3, 3]).map((s) => s[1])).toEqual([[3, 4], [3, 2], [2, 3]]);
    expect(wireSegments("plus", 0, [3, 3])).toHaveLength(4);
  });
});

describe("plan and place", () => {
  test("a part fits on free points", () => {
    const p = plan(board(), R2, [5, 5], "E");
    expect(p.valid).toBe(true);
    expect(p.pins).toEqual([[6, 5], [4, 5]]);
  });

  test("a part can't overlap another part or sit with its body on a wire", () => {
    expect(plan(board(), R2, [3, 3], "N").valid).toBe(false); // pin on R1's body [3,2]
    expect(plan(board(), R2, [5, 4], "N").valid).toBe(false); // body on the wire point [5,4]
    expect(plan(board(), R2, [8, 5], "E").valid).toBe(false); // first pin off the grid
  });

  test("a part's pin may land on a wire end (that's how it connects)", () => {
    expect(plan(board(), R2, [4, 4], "W").valid).toBe(true); // second pin on [5,4]
  });

  test("placing moves the part from the inventory to the board", () => {
    const next = place(board(), R2, [5, 5], "E");
    expect(next.inventory).toEqual([]);
    expect(next.components.at(-1)).toEqual({
      id: "R2", type: "resistor", value: 20, fixed: false, orientation: "E", pins: { a: [6, 5], b: [4, 5] },
    });
  });

  test("a wire piece gets the next wire id and can't cross a body", () => {
    const next = place(board(), { kind: "wire", shape: "corner" }, [6, 1], 1);
    expect(next.wires.at(-1).id).toBe("W4");
    expect(plan(board(), { kind: "wire", shape: "straight" }, [3, 1], 1).valid).toBe(false); // into R1's body
    expect(place(board(), { kind: "wire", shape: "straight" }, [3, 1], 1)).toBeNull();
  });
});
