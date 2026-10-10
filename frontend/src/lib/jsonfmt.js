// Human-readable JSON, same rules as backend/app/jsonfmt.py:
// short arrays and objects on one line, arrays longer than 6 elements wrapped 6 per line.

const INDENT = 2;
const WIDTH = 100;
const PER_LINE = 6;

// One-line form with ", " and ": " separators (like Python's json.dumps separators).
function flat(value) {
  if (Array.isArray(value)) return "[" + value.map(flat).join(", ") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.entries(value).map(([k, v]) => `${JSON.stringify(k)}: ${flat(v)}`).join(", ") + "}";
  }
  return JSON.stringify(value);
}

function format(value, level) {
  const pad = " ".repeat(INDENT * (level + 1));
  const end = " ".repeat(INDENT * level);
  const room = WIDTH - INDENT * level;

  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const one = flat(value);
    if (value.length <= PER_LINE && one.length <= room) return one;
    const parts = value.map((v) => format(v, level + 1));
    if (parts.every((p) => !p.includes("\n"))) {
      const rows = [];
      for (let i = 0; i < parts.length; i += PER_LINE) rows.push(parts.slice(i, i + PER_LINE).join(", "));
      if (rows.every((r) => r.length <= WIDTH - pad.length)) {
        return "[\n" + rows.map((r) => pad + r).join(",\n") + "\n" + end + "]";
      }
    }
    return "[\n" + parts.map((p) => pad + p).join(",\n") + "\n" + end + "]";
  }

  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) return "{}";
    const longArrays = entries.some(([, v]) => Array.isArray(v) && v.length > PER_LINE);
    const one = flat(value);
    if (!longArrays && one.length <= room) return one;
    const items = entries.map(([k, v]) => `${pad}${JSON.stringify(k)}: ${format(v, level + 1)}`);
    return "{\n" + items.join(",\n") + "\n" + end + "}";
  }

  return JSON.stringify(value);
}

export function readableJson(value) {
  return format(value, 0);
}
