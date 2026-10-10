"""Human-readable JSON: indented, short arrays and objects on one line, long arrays wrapped.

Rules
- Objects and arrays stay on one line when they fit within `width` characters.
- An array with more than `per_line` (6) elements is wrapped, `per_line` elements per line.
- Everything else is indented by `indent` spaces per level.
"""

import json

INDENT, WIDTH, PER_LINE = 2, 100, 6


def _flat(value) -> str:
    return json.dumps(value, separators=(", ", ": "), ensure_ascii=False)


def _format(value, level: int) -> str:
    pad = " " * INDENT * (level + 1)
    end = " " * INDENT * level
    room = WIDTH - INDENT * level

    if isinstance(value, dict):
        if not value:
            return "{}"
        long_arrays = any(isinstance(v, list) and len(v) > PER_LINE for v in value.values())
        flat = _flat(value)
        if not long_arrays and len(flat) <= room:
            return flat
        items = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {_format(v, level + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"

    if isinstance(value, list):
        if not value:
            return "[]"
        flat = _flat(value)
        if len(value) <= PER_LINE and len(flat) <= room:
            return flat
        parts = [_format(v, level + 1) for v in value]
        if all("\n" not in p for p in parts):
            rows = [", ".join(parts[i:i + PER_LINE]) for i in range(0, len(parts), PER_LINE)]
            if all(len(r) <= WIDTH - len(pad) for r in rows):
                return "[\n" + ",\n".join(pad + r for r in rows) + "\n" + end + "]"
        return "[\n" + ",\n".join(pad + p for p in parts) + "\n" + end + "]"

    return json.dumps(value, ensure_ascii=False)


def dumps(value) -> str:
    """Readable JSON text, ending with a newline."""
    return _format(value, 0) + "\n"
