import { expect, test } from "vitest";
import { partCaption, partName } from "./naming.js";

test("captions and names", () => {
  expect(partCaption({ id: "R2", type: "resistor", value: 20 })).toBe("20 Ω");
  expect(partCaption({ id: "V2", type: "voltage_source", value: 9 })).toBe("9 V");
  expect(partCaption({ id: "AM2", type: "ammeter" })).toBe("AM2");
  expect(partCaption({ id: "R5", type: "resistor", value: 4700 })).toBe("4.7 kΩ");
  expect(partCaption({ id: "R6", type: "resistor", value: 1000000 })).toBe("1 MΩ");
  expect(partName({ id: "R2", type: "resistor", value: 20 })).toBe("R2 resistor 20 Ω");
});
