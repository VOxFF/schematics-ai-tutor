// Names and captions for inventory parts.

// Nominal value with a unit: 20 Ω, 4.7 kΩ, 1 MΩ, 9 V.
export function formatValue(item) {
  if (item.value == null) return null;
  if (item.type !== "resistor") return `${item.value} V`;
  const ohms = item.value;
  if (ohms >= 1e6) return `${+(ohms / 1e6).toPrecision(2)} MΩ`;
  if (ohms >= 1e3) return `${+(ohms / 1e3).toPrecision(2)} kΩ`;
  return `${ohms} Ω`;
}

// Caption under a part in the inventory: its nominal value, or its ID for a meter.
export const partCaption = (item) => formatValue(item) ?? item.id;
// Full name, e.g. "R2 resistor 20 Ω" (accessible name of an inventory item).
export const partName = (item) => [item.id, item.type.replace("_", " "), formatValue(item)].filter(Boolean).join(" ");
