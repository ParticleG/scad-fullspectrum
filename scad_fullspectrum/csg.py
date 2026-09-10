"""OpenSCAD CSG tree parsing and colour-aware splitting.

``openscad -o model.csg model.scad`` dumps the *flattened* CSG tree of a design:
modules are inlined, variables are substituted, and every ``color()`` scope
survives as a ``color([r, g, b, a]) { ... }`` wrapper.  That makes the CSG dump
the only reliable way to recover per-colour geometry from a plain SCAD source:

* OpenSCAD 2021.01 writes plain geometry to 3MF (no colours at all),
* its AMF exporter refuses objects that are not a single 2-manifold volume,
  which is exactly what a multi-colour design produces.

The splitter below turns one CSG tree into one tree per colour, with these
semantics for the boolean operations (colours are geometry attributes, not
operands):

* ``union`` / ``group`` / ``render`` / transforms / extrusions - recurse, keep
  the children that contain the requested colour.
* ``difference`` - only the base (first child) carries geometry, so the base is
  filtered and *all* cutters are kept verbatim (they remove material from every
  colour).
* ``intersection`` - every child bounds the result, so children that do not
  contain the requested colour are kept verbatim.
* ``hull`` / ``minkowski`` - reshape their children, so per-colour splitting is
  not meaningful; the whole subtree is attributed to the first colour found in
  it.

Nested ``color()`` scopes behave like OpenSCAD: the innermost scope wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterator, Sequence

__all__ = [
    "CsgError",
    "Node",
    "parse",
    "dump",
    "color_of",
    "iter_colors",
    "contains_color",
    "select_root",
    "split_for_color",
]

RGB = tuple[int, int, int]


class CsgError(Exception):
    """Raised when the input is not a parseable CSG dump."""


@dataclass
class Node:
    """One statement of a CSG tree.

    ``children is None`` marks a leaf statement (a primitive or ``import()``),
    an empty list marks a block statement with no surviving children.
    ``modifier`` holds the OpenSCAD display prefix (``%`` background, ``#``
    highlight, ``!`` root) when the source carried one.
    """

    name: str
    args: list[tuple[str | None, object]] = field(default_factory=list)
    children: list["Node"] | None = None
    modifier: str = ""

    def positional(self) -> Iterator[object]:
        for key, value in self.args:
            if key is None:
                yield value

    def named(self) -> Iterator[tuple[str, object]]:
        for key, value in self.args:
            if key is not None:
                yield key, value

    def arg(self, key: str, default: object = None) -> object:
        for name, value in self.args:
            if name == key:
                return value
        return default


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

_WHITESPACE = " \t\r\n"
_SYMBOLS = "(){}[],;=*"


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    # -- lexer helpers ----------------------------------------------------- #

    def _skip(self) -> None:
        text, n = self.text, len(self.text)
        while self.pos < n:
            ch = text[self.pos]
            if ch in _WHITESPACE:
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = n if end < 0 else end + 1
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos + 2)
                if end < 0:
                    raise CsgError("unterminated block comment")
                self.pos = end + 2
            else:
                return

    def _peek(self) -> str:
        self._skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _take(self, expected: str) -> None:
        self._skip()
        if not self.text.startswith(expected, self.pos):
            got = self.text[self.pos : self.pos + 20]
            raise CsgError(f"expected {expected!r} at offset {self.pos}, got {got!r}")
        self.pos += len(expected)

    def _identifier(self) -> str:
        self._skip()
        start = self.pos
        text, n = self.text, len(self.text)
        while self.pos < n and (text[self.pos].isalnum() or text[self.pos] in "_$."):
            self.pos += 1
        if self.pos == start:
            raise CsgError(f"expected identifier at offset {self.pos}")
        return text[start : self.pos]

    # -- grammar ----------------------------------------------------------- #

    def program(self) -> list[Node]:
        nodes: list[Node] = []
        while True:
            self._skip()
            if self.pos >= len(self.text):
                return nodes
            nodes.append(self.statement())

    def statement(self) -> Node:
        # ``%`` / ``#`` / ``!`` modifiers can appear in hand-written CSG files.
        modifier = ""
        while self._peek() in {"%", "#", "!"}:
            modifier = self._peek()
            self.pos += 1
        name = self._identifier()
        args = self.arguments() if self._peek() == "(" else []
        if self._peek() == "{":
            return Node(name, args, self.block(), modifier)
        self._take(";")
        return Node(name, args, None, modifier)

    def block(self) -> list[Node]:
        self._take("{")
        children: list[Node] = []
        while True:
            self._skip()
            if self._peek() == "}":
                self._take("}")
                return children
            if self.pos >= len(self.text):
                raise CsgError("unterminated block")
            children.append(self.statement())

    def arguments(self) -> list[tuple[str | None, object]]:
        self._take("(")
        args: list[tuple[str | None, object]] = []
        while True:
            self._skip()
            if self._peek() == ")":
                self._take(")")
                return args
            if args:
                self._take(",")
                self._skip()
                if self._peek() == ")":
                    self._take(")")
                    return args
            key: str | None = None
            mark = self.pos
            if self._peek().isalpha() or self._peek() == "$":
                word = self._identifier()
                if self._peek() == "=":
                    self._take("=")
                    key = word
                else:
                    self.pos = mark
            args.append((key, self.value()))

    def value(self) -> object:
        self._skip()
        ch = self._peek()
        if ch == "[":
            self._take("[")
            items: list[object] = []
            while True:
                self._skip()
                if self._peek() == "]":
                    self._take("]")
                    return items
                if items:
                    self._take(",")
                    self._skip()
                    if self._peek() == "]":
                        self._take("]")
                        return items
                items.append(self.value())
        if ch == "(":
            # Grouped expression: ``(a * b)`` style literals from hand edits.
            self._take("(")
            inner = self.value()
            self._take(")")
            return inner
        if ch == '"':
            return self._string()
        if ch and (ch.isdigit() or ch in "+-."):
            return self._number()
        word = self._identifier()
        if word == "true":
            return True
        if word == "false":
            return False
        if word == "undef":
            return None
        return word

    def _string(self) -> str:
        self._take('"')
        out: list[str] = []
        text = self.text
        while True:
            if self.pos >= len(text):
                raise CsgError("unterminated string")
            ch = text[self.pos]
            self.pos += 1
            if ch == '"':
                return "".join(out)
            if ch == "\\" and self.pos < len(text):
                esc = text[self.pos]
                self.pos += 1
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
            else:
                out.append(ch)

    def _number(self) -> float:
        self._skip()
        start = self.pos
        text = self.text
        while self.pos < len(text) and (text[self.pos].isdigit() or text[self.pos] in "+-.eE"):
            self.pos += 1
        try:
            return float(text[start : self.pos])
        except ValueError as exc:  # pragma: no cover - defensive
            raise CsgError(f"bad number at offset {start}") from exc


def parse(text: str) -> list[Node]:
    """Parse a CSG dump into a list of top-level statements."""

    return _Parser(text).program()


# --------------------------------------------------------------------------- #
# Serializer
# --------------------------------------------------------------------------- #

def _format_number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.9g}"


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "undef"
    if isinstance(value, (int, float)):
        return _format_number(float(value))
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    return str(value)


def _format_args(node: Node) -> str:
    rendered = [
        _format_value(value) if key is None else f"{key} = {_format_value(value)}"
        for key, value in node.args
    ]
    return "(" + ", ".join(rendered) + ")"


def dump(nodes: Sequence[Node], indent: int = 0) -> str:
    """Serialize statements back to OpenSCAD source."""

    pad = "\t" * indent
    out: list[str] = []
    for node in nodes:
        head = f"{pad}{node.name}{_format_args(node)}"
        if node.children is None:
            out.append(head + ";")
        elif not node.children:
            out.append(head + " {\n" + pad + "}")
        else:
            out.append(head + " {\n" + dump(node.children, indent + 1) + "\n" + pad + "}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Colour extraction and splitting
# --------------------------------------------------------------------------- #

def color_of(node: Node) -> RGB | None:
    """Return the RGB triple declared by a ``color()`` node, else ``None``."""

    if node.name != "color":
        return None
    values = list(node.positional())
    if not values:
        return None
    raw = values[0]
    if isinstance(raw, str):
        return _parse_hex_color(raw)
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            channels = [int(round(float(channel) * 255)) for channel in raw[:3]]
        except (TypeError, ValueError):
            return None
        return tuple(max(0, min(255, channel)) for channel in channels)  # type: ignore[return-value]
    return None


def _parse_hex_color(text: str) -> RGB | None:
    value = text.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return None


def iter_colors(nodes: Sequence[Node], inherited: RGB | None = None) -> Iterator[RGB]:
    """Yield every colour actually painted on geometry, innermost scope winning.

    A ``color()`` scope that only wraps other scopes (or nothing at all) does not
    produce material of its own, so it is not reported here.
    """

    for node in nodes:
        if node.modifier == "%":
            continue
        current = color_of(node) or inherited
        if node.children is None:
            if current is not None:
                yield current
            continue
        yield from iter_colors(node.children, current)


def contains_color(node: Node, target: RGB | None, inherited: RGB | None = None) -> bool:
    """True when any leaf of ``node`` is painted with ``target``."""

    current = color_of(node) or inherited
    if node.children is None:
        return current == target
    return any(contains_color(child, target, current) for child in node.children)


def _first_color(node: Node, inherited: RGB | None = None) -> RGB | None:
    """Effective colour of the first painted leaf inside ``node``.

    Falls back to the colour inherited from the enclosing scope when nothing
    inside declares one, so ``color("red") hull() { ... }`` is attributed to
    red rather than to no colour at all.
    """

    current = color_of(node) or inherited
    if node.children is None:
        return current
    for child in node.children:
        found = _first_color(child, current)
        if found is not None:
            return found
    return current


def select_root(nodes: Sequence[Node]) -> list[Node]:
    """Apply OpenSCAD's ``!`` root modifier: only that subtree is rendered.

    OpenSCAD already strips ``%``/``!`` scopes from its CSG dump, so this only
    matters for hand-edited CSG files.
    """

    def find(items: Sequence[Node]) -> Node | None:
        for node in items:
            if node.modifier == "!":
                return node
            if node.children:
                found = find(node.children)
                if found is not None:
                    return found
        return None

    target = find(nodes)
    if target is None:
        return list(nodes)

    def narrow(items: Sequence[Node]) -> Node | None:
        for node in items:
            if node is target:
                return replace(node, modifier="")
            if node.children:
                inner = narrow(node.children)
                if inner is not None:
                    return replace(node, children=[inner])
        return None

    selected = narrow(nodes)
    return [selected] if selected is not None else list(nodes)


def _filter_node(node: Node, target: RGB | None, inherited: RGB | None) -> Node | None:
    if node.modifier == "%":
        # Background geometry is never part of the render.
        return None

    if node.name == "color":
        current = color_of(node) or inherited
        kept = [
            filtered
            for child in node.children or []
            if (filtered := _filter_node(child, target, current)) is not None
        ]
        return replace(node, children=kept) if kept else None

    if node.children is None:
        return node if inherited == target else None

    if node.name == "difference":
        base = node.children[0] if node.children else None
        if base is None:
            return None
        kept_base = _filter_node(base, target, inherited)
        if kept_base is None:
            # The base carries no geometry of this colour: the cutters would
            # only produce a negative volume, so the whole operation drops out.
            return None
        return replace(node, children=[kept_base, *node.children[1:]])

    if node.name in {"hull", "minkowski"}:
        return node if _first_color(node, inherited) == target else None

    if node.name == "intersection":
        if not contains_color(node, target, inherited):
            return None
        children = [
            _filter_node(child, target, inherited) or child for child in node.children
        ]
        return replace(node, children=children)

    kept = [
        filtered
        for child in node.children
        if (filtered := _filter_node(child, target, inherited)) is not None
    ]
    if not kept:
        return None
    return replace(node, children=kept)


def split_for_color(nodes: Sequence[Node], target: RGB | None) -> list[Node]:
    """Return the statements that render exactly the geometry painted ``target``.

    ``target=None`` selects geometry that is not inside any ``color()`` scope.
    """

    result: list[Node] = []
    for node in nodes:
        filtered = _filter_node(node, target, None)
        if filtered is not None:
            result.append(filtered)
    return result
