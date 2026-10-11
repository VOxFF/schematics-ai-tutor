import { afterEach, expect, test } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { PartIcon, WireIcon, partCaption, partName } from "./InventoryIcons.jsx";
import { BAND_COLORS } from "./colorCode.js";

afterEach(cleanup);

test("a resistor icon shows its color bands", () => {
  const { container } = render(<PartIcon item={{ id: "R2", type: "resistor", value: 20 }} />);
  const fills = [...container.querySelectorAll("rect")].map((r) => r.getAttribute("fill"));
  // red, black, black, gold = 20 Ω (after the body rect)
  expect(fills.slice(1)).toEqual([BAND_COLORS.red, BAND_COLORS.black, BAND_COLORS.black, BAND_COLORS.gold]);
});

test("a meter icon shows its letter", () => {
  const { container } = render(<PartIcon item={{ id: "AM2", type: "ammeter" }} />);
  expect(container.querySelector("text").textContent).toBe("A");
});

test("wire icons draw one line per arm", () => {
  const count = (shape, rotation = 0) => render(<WireIcon shape={shape} rotation={rotation} />).container.querySelectorAll("line").length;
  expect([count("straight"), count("corner"), count("T"), count("plus")]).toEqual([1, 2, 3, 4]);
});

test("captions and names", () => {
  expect(partCaption({ id: "R2", type: "resistor", value: 20 })).toBe("20 Ω");
  expect(partCaption({ id: "V2", type: "voltage_source", value: 9 })).toBe("9 V");
  expect(partCaption({ id: "AM2", type: "ammeter" })).toBe("AM2");
  expect(partName({ id: "R2", type: "resistor", value: 20 })).toBe("R2 resistor 20 Ω");
  expect(partCaption({ id: "R5", type: "resistor", value: 4700 })).toBe("4.7 kΩ");
  expect(partCaption({ id: "R6", type: "resistor", value: 1000000 })).toBe("1 MΩ");
});
