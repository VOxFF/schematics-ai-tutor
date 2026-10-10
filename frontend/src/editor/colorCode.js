// Resistor 4-band color code (docs/gui.md §4): two digits, a multiplier, gold tolerance.

const DIGITS = ["black", "brown", "red", "orange", "yellow", "green", "blue", "violet", "grey", "white"];

export const BAND_COLORS = {
  black: "#1f1f1f",
  brown: "#7b4a2a",
  red: "#d1242f",
  orange: "#f08a24",
  yellow: "#f2cc0f",
  green: "#1f9d55",
  blue: "#1f6feb",
  violet: "#8250df",
  grey: "#8c959f",
  white: "#ffffff",
  gold: "#a5781e", // darker, metallic: distinct from the yellow digit band
  silver: "#b8bcc2",
};

// Band names for a resistance in ohms, or null when it can't be drawn with 4 bands.
export function resistorBands(ohms) {
  if (!(ohms > 0)) return null;
  let exponent = Math.floor(Math.log10(ohms)) - 1;
  let digits = Math.round(ohms / 10 ** exponent);
  if (digits >= 100) {
    digits = Math.round(digits / 10);
    exponent += 1;
  }
  const multiplier = exponent >= 0 ? DIGITS[exponent] : { "-1": "gold", "-2": "silver" }[exponent];
  if (!multiplier || exponent > 9) return null;
  return [DIGITS[Math.floor(digits / 10)], DIGITS[digits % 10], multiplier, "gold"];
}
