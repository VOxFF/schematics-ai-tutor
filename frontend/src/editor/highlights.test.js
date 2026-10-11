import { expect, test } from "vitest";
import { liveHighlights } from "./highlights.js";

const board = {
  components: [{ id: "R1", type: "resistor", pins: { a: [2, 2], b: [4, 2] } }],
  wires: [{ id: "W1", segments: [[[4, 2], [4, 4]]] }],
};
const highlights = [
  { target: { component: "R1" }, style: "attention" },
  { target: { wire: "W1" }, style: "error" },
  { target: { point: [6, 6] }, style: "success" },
];

test("highlights stay while their elements are unchanged", () => {
  expect(liveHighlights(highlights, board, structuredClone(board))).toEqual(highlights);
});

test("a highlight drops when its element is moved or removed; points stay", () => {
  const moved = { components: [{ ...board.components[0], pins: { a: [2, 3], b: [4, 3] } }], wires: [] };
  expect(liveHighlights(highlights, board, moved)).toEqual([highlights[2]]);
});

test("no highlights", () => {
  expect(liveHighlights(undefined, board, board)).toEqual([]);
});
