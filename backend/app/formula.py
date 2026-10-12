"""Math check for formulas in tutor replies (docs/design.md §4, Formulas and paragraphs).

Claude writes `chat.formula` as lines of LaTeX; this module decides whether they are shown. It
parses a small LaTeX subset (symbols with subscripts, numbers with units, + - \\cdot \\times
\\frac, parentheses, powers, = and \\approx) and checks that every number comes from the board or
an earlier result, that the arithmetic holds, that each hint rung keeps to its limits, and that
the answer, the value of a part the learner still has to place, shows only on rung 4.
"""

import math
import re

# Unit → (dimension, factor to SI).
UNITS = {
    "Ω": ("ohm", 1.0), "kΩ": ("ohm", 1e3), "MΩ": ("ohm", 1e6),
    "V": ("volt", 1.0), "mV": ("volt", 1e-3), "kV": ("volt", 1e3),
    "A": ("amp", 1.0), "mA": ("amp", 1e-3), "µA": ("amp", 1e-6),
    "W": ("watt", 1.0), "mW": ("watt", 1e-3),
}
# What a part's value or a meter's reading measures.
DIMENSIONS = {"voltage_source": "volt", "resistor": "ohm", "voltmeter": "volt", "ammeter": "amp"}
EXACT = 0.01      # `=`: both sides agree within 1%
ROUNDED = 0.05    # `\approx`: within 5%
COEFFICIENTS = 10  # whole numbers up to this may appear without a source: algebra (3 R_2, 1/R)

_SPACING = re.compile(r"\\[,;:! ]|~|\\q?quad\b|\\left\b|\\right\b|\s+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_BARE_UNIT = re.compile(r"(?:kΩ|MΩ|Ω|mV|kV|mA|µA|mW|V|A|W)(?![A-Za-z_{])")
_LETTER = re.compile(r"[A-Za-z]'?")
_TEXT_COMMANDS = ("\\mathrm", "\\text", "\\textrm", "\\operatorname")
_FRACTIONS = ("\\frac", "\\dfrac", "\\tfrac")
_OPERATORS = {"\\cdot": "*", "\\times": "*", "*": "*", "/": "/", "\\div": "/", "+": "+", "-": "-",
              "−": "-", "=": "=", "\\approx": "≈", "^": "^", "(": "(", ")": ")", "[": "(", "]": ")",
              "{": "{", "}": "}"}


class FormulaError(ValueError):
    pass


def _unit_name(raw: str) -> str | None:
    name = raw.replace("\\Omega", "Ω").replace("\\mu", "µ").replace("μ", "µ").replace("\\", "")
    name = re.sub(r"[\s{},;:!~]", "", name)
    return name if name in UNITS else None


def _group(line: str, at: int) -> tuple[str, int]:
    """The contents of the braced group at `at` and the index after it."""
    if at >= len(line) or line[at] != "{":
        raise FormulaError(f"expected '{{' at {at}")
    depth = 0
    for i in range(at, len(line)):
        depth += {"{": 1, "}": -1}.get(line[i], 0)
        if depth == 0:
            return line[at + 1:i], i + 1
    raise FormulaError("unbalanced braces")


def _skip(line: str, at: int) -> int:
    while m := _SPACING.match(line, at):
        at = m.end()
    return at


def _unit(line: str, at: int) -> tuple[str | None, int]:
    """A unit right after a number, if there is one."""
    at = _skip(line, at)
    for command in _TEXT_COMMANDS:
        if line.startswith(command + "{", at):
            body, end = _group(line, at + len(command))
            if name := _unit_name(body):
                return name, end
            return None, at
    if line.startswith("\\Omega", at):
        return "Ω", at + len("\\Omega")
    if line.startswith(("k\\Omega", "M\\Omega"), at):
        return line[at] + "Ω", at + len("k\\Omega")
    if m := _BARE_UNIT.match(line, at):
        return m.group(0), m.end()
    return None, at


def tokenize(line: str) -> list[tuple]:
    """Tokens: ("num", si_value, dimension | None), ("sym", name), ("frac",), or (operator,)."""
    tokens, at = [], 0
    while at < len(line):
        if m := _SPACING.match(line, at):
            at = m.end()
            continue
        if m := _NUMBER.match(line, at):
            value = float(m.group(0))
            unit, at = _unit(line, m.end())
            dimension, factor = UNITS[unit] if unit else (None, 1.0)
            tokens.append(("num", value * factor, dimension))
            continue
        command = next((c for c in _FRACTIONS if line.startswith(c, at)), None)
        if command:
            tokens.append(("frac",))
            at += len(command)
            continue
        command = next((c for c in _TEXT_COMMANDS if line.startswith(c + "{", at)), None)
        if command:
            body, at = _group(line, at + len(command))
            tokens.append(("sym", body))
            continue
        operator = next((o for o in sorted(_OPERATORS, key=len, reverse=True) if line.startswith(o, at)), None)
        if operator and not (operator == "\\cdot" and line.startswith("\\cdots", at)):
            tokens.append((_OPERATORS[operator],))
            at += len(operator)
            continue
        if m := _LETTER.match(line, at):
            name, at = m.group(0), m.end()
            if line.startswith("_", at):
                at = _skip(line, at + 1)
                if line.startswith("{", at):
                    sub, at = _group(line, at)
                elif command := next((c for c in _TEXT_COMMANDS if line.startswith(c + "{", at)), None):
                    sub, at = _group(line, at + len(command))
                elif at < len(line):
                    sub, at = line[at], at + 1
                else:
                    raise FormulaError("empty subscript")
                name += "_" + sub
            tokens.append(("sym", name))
            continue
        raise FormulaError(f"unsupported: {line[at:at + 12]!r}")
    return tokens


class _Parser:
    """Recursive descent over one side of an equation. A side's value is a float, or None when it
    has a symbol; every number literal is collected, apart from exponents."""

    def __init__(self, tokens: list[tuple]):
        self.tokens, self.at, self.literals = tokens, 0, []

    def peek(self) -> tuple | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self, kind: str) -> tuple:
        token = self.peek()
        if token is None or token[0] != kind:
            raise FormulaError(f"expected {kind!r}")
        self.at += 1
        return token

    def side(self):
        value = self.expr()
        if self.peek() is not None:
            raise FormulaError(f"unexpected {self.peek()[0]!r}")
        return value

    def expr(self):
        value = self.term()
        while (token := self.peek()) and token[0] in "+-":
            self.at += 1
            right = self.term()
            value = None if value is None or right is None else value + right if token[0] == "+" else value - right
        return value

    def term(self):
        value = self.unary()
        while (token := self.peek()) and (token[0] in ("*", "/") or token[0] in ("num", "sym", "frac", "(", "{")):
            divide = token[0] == "/"
            if token[0] in ("*", "/"):
                self.at += 1
            right = self.unary()
            if value is None or right is None:
                value = None
            elif divide:
                if right == 0:
                    raise FormulaError("division by zero")
                value = value / right
            else:
                value = value * right
        return value

    def unary(self):
        if (token := self.peek()) and token[0] == "-":
            self.at += 1
            value = self.unary()
            return None if value is None else -value
        return self.power()

    def power(self):
        value = self.atom()
        if (token := self.peek()) and token[0] == "^":
            self.at += 1
            found = len(self.literals)
            exponent = self.atom()
            del self.literals[found:]  # an exponent is algebra, not a value from the board
            if exponent is None:
                raise FormulaError("symbolic exponent")
            value = None if value is None else value ** exponent
        return value

    def atom(self):
        token = self.peek()
        if token is None:
            raise FormulaError("unexpected end")
        self.at += 1
        if token[0] == "num":
            self.literals.append((token[1], token[2]))
            return token[1]
        if token[0] == "sym":
            return None
        if token[0] in ("(", "{"):
            value = self.expr()
            self.take(")" if token[0] == "(" else "}")
            return value
        if token[0] == "frac":
            self.take("{")
            top = self.expr()
            self.take("}")
            self.take("{")
            bottom = self.expr()
            self.take("}")
            if top is None or bottom is None:
                return None
            if bottom == 0:
                raise FormulaError("division by zero")
            return top / bottom
        raise FormulaError(f"unexpected {token[0]!r}")


def parse_line(line: str) -> tuple[list[dict], bool]:
    """A line's sides, each {value, literals, single}, and whether it uses \\approx."""
    tokens = tokenize(line)
    sides, current, approx, depth = [], [], False, 0
    for token in tokens:
        depth += {"(": 1, "{": 1, ")": -1, "}": -1}.get(token[0], 0)
        if token[0] in ("=", "≈") and depth == 0:
            approx = approx or token[0] == "≈"
            sides.append(current)
            current = []
        else:
            current.append(token)
    sides.append(current)
    if any(not side for side in sides):
        raise FormulaError("empty side")
    parsed = []
    for side in sides:
        parser = _Parser(side)
        value = parser.side()
        parsed.append({"value": value, "literals": parser.literals,
                       "single": len(side) == 1 and side[0][0] == "num"})
    return parsed, approx


def _close(a: float, b: float, tolerance: float) -> bool:
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=1e-9)


def _matches(value: float, dimension: str | None, quantities: list[tuple]) -> bool:
    """Whether a number is one of `quantities` [(si_value, dimension)]: same value and, when the
    number has a unit, the same dimension."""
    return any(_close(value, v, EXACT) and (dimension is None or dimension == d) for v, d in quantities)


def check(lines, *, allowed: list[tuple], answers: list[tuple], rung: int, max_lines: int = 8) -> list[str]:
    """The problems with a formula, for the regeneration request; empty if it may be shown.

    `allowed` are the board's quantities [(si_value, dimension)]: part values, readings and
    targets. `answers` are the values of the parts the learner still has to place. `rung` is the
    hint rung, 0 for a reply that isn't a hint."""
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        return ["formula must be a list of LaTeX lines"]
    problems, results = [], []
    if len(lines) > max_lines:
        problems.append(f"formula has {len(lines)} lines; at most {max_lines}")
    for number, line in enumerate(lines, 1):
        try:
            sides, approx = parse_line(line)
        except FormulaError as error:
            problems.append(f"line {number} uses LaTeX outside the subset ({error})")
            continue
        numeric = [s["value"] for s in sides if s["value"] is not None]
        if any(not _close(v, numeric[0], ROUNDED if approx else EXACT) for v in numeric[1:]):
            problems.append(f"line {number}: the arithmetic doesn't hold")
            continue
        # A number standing alone as a side that equals another side is a result.
        line_results = numeric if len(numeric) > 1 else []
        for side in sides:
            if side["single"] and line_results:
                continue
            for value, dimension in side["literals"]:
                if dimension is None and value.is_integer() and 0 <= value <= COEFFICIENTS:
                    continue  # algebra, like 1/R or 2 R_2: allowed on every rung
                if rung == 2:
                    problems.append(f"line {number}: hint rung 2 shows the formula without the board's numbers")
                    break
                if (_matches(value, dimension, allowed) or _matches(value, None, results + [(r, None) for r in line_results])
                        or (rung == 4 and _matches(value, dimension, answers))):
                    continue
                problems.append(f"line {number}: {value:g} is not a value on the board or an earlier result")
        if rung != 4:
            shown = [lit for s in sides for lit in s["literals"]] + [(v, None) for v in numeric]
            if any(_matches(value, dimension, answers) for value, dimension in shown):
                problems.append(f"line {number} gives the answer; only hint rung 4 may")
        results += [(v, None) for v in numeric]
    return sorted(set(problems), key=problems.index)


_TEXT_QUANTITY = re.compile(r"(\d+(?:\.\d+)?)\s*(kΩ|MΩ|Ω|k?ohms?|kilo-?ohms?|mV|kV|V|volts?|mA|µA|A|amps?|mW|W|watts?)\b",
                            re.IGNORECASE)
_TEXT_UNITS = {"ohm": "Ω", "kohm": "kΩ", "kiloohm": "kΩ", "kilo-ohm": "kΩ", "volt": "V", "amp": "A", "watt": "W"}


def answer_in_text(text: str, answers: list[tuple]) -> list[str]:
    """The quantities in `text` (a number with a unit) that give the answer away."""
    found = []
    for m in _TEXT_QUANTITY.finditer(text):
        word = m.group(2).lower().removesuffix("s")
        unit = m.group(2) if m.group(2) in UNITS else _TEXT_UNITS.get(word)
        if unit is None:
            continue
        dimension, factor = UNITS[unit]
        if _matches(float(m.group(1)) * factor, dimension, answers):
            found.append(m.group(0))
    return found


def board_quantities(board: dict, evaluation: dict) -> tuple[list[tuple], list[tuple]]:
    """(placed, inventory): the quantities on the learner's board [(si_value, dimension)]. Placed
    are the values of placed parts, the meters' readings and the targets."""
    types = {c["id"]: c["type"] for c in board.get("components", []) + board.get("inventory", [])}

    def values(parts):
        return [(float(p["value"]), DIMENSIONS[p["type"]]) for p in parts
                if isinstance(p.get("value"), (int, float)) and p.get("type") in DIMENSIONS]

    placed = values(board.get("components", []))
    for meter, reading in (evaluation.get("readings") or {}).items():
        if isinstance(reading, (int, float)) and types.get(meter) in DIMENSIONS:
            placed.append((float(reading), DIMENSIONS[types[meter]]))
    for meter, target in (board.get("targets") or {}).items():
        value = target.get("value") if isinstance(target, dict) else None
        if isinstance(value, (int, float)) and types.get(meter) in DIMENSIONS:
            placed.append((float(value), DIMENSIONS[types[meter]]))
    return placed, values(board.get("inventory", []))


def answer_values(reference: dict | None, placed: list[tuple]) -> list[tuple]:
    """The values of the reference's parts that aren't on the board yet: what the learner still
    has to work out. A value that is also on the board (a fixed part, a target) isn't one."""
    if not reference:
        return []
    answers = []
    for part in reference.get("components", []):
        if part.get("type") in DIMENSIONS and isinstance(part.get("value"), (int, float)):
            quantity = (float(part["value"]), DIMENSIONS[part["type"]])
            if not _matches(*quantity, placed) and quantity not in answers:
                answers.append(quantity)
    return answers
