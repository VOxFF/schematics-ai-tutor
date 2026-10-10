import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, test } from "vitest";
import { readableJson } from "./jsonfmt.js";

// Tests run from frontend/ (npm test).
const EXAMPLES = resolve(process.cwd(), "../backend/data/examples");

test("matches the backend formatter byte for byte", () => {
  for (const name of readdirSync(EXAMPLES)) {
    const text = readFileSync(join(EXAMPLES, name), "utf8");
    expect(readableJson(JSON.parse(text)) + "\n").toBe(text);
  }
});

test("wraps long arrays six per line", () => {
  expect(readableJson([...Array(8).keys()])).toBe("[\n  0, 1, 2, 3, 4, 5,\n  6, 7\n]");
});
