"""Deterministic candidate finder for the Business Rule agent (FR-5).

A candidate is a span of at most 40 lines (EVD-1.4) that looks like it enforces domain
behaviour: a comparison against a number or string literal, a multiplication or division by a
number, a table of numbers, a `throw`, or an HTTP 4xx answer. The model never chooses where to
look; it only explains a span this module found, so every rule it states can be tied to cited
lines.

Functions longer than the limit are not sent whole: their direct `if` statements that carry a
signal are. Test files are skipped. The signals were chosen after the fixture was read, so the
fixture score is optimistic.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node

from services.codeanalysis.analyze import _FUNCTIONS, _is_test, _parse, _span, _text, _walk
from services.evidence import SnapshotReader
from services.evidence.refs import max_excerpt_lines

_FUNCTION_TYPES = (*_FUNCTIONS, "method_definition")
_COMPARE = frozenset({"<", ">", "<=", ">=", "===", "==", "!==", "!="})
_SCALE = frozenset({"*", "/", "%"})
_LITERAL = frozenset({"number", "string"})


@dataclass(frozen=True)
class Candidate:
    path: str
    start: int
    end: int
    kind: str  # "validation" if it rejects input, else "rule"
    code: str  # the cited lines, as numbered text

    @property
    def key(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"


def _own_nodes(node: Node) -> Iterator[Node]:
    """Nodes of this function, not of functions nested inside it."""
    stack = list(reversed(node.children))
    while stack:
        current = stack.pop()
        yield current
        if current.type not in _FUNCTION_TYPES:
            stack.extend(reversed(current.children))


def _is_number(node: Node | None) -> bool:
    return node is not None and node.type == "number"


def _signal(node: Node) -> str | None:
    """'validation', 'rule', or None if this node alone says nothing about domain behaviour."""
    if node.type == "throw_statement":
        return "validation"
    if node.type == "binary_expression":
        op = node.child_by_field_name("operator")
        symbol = op.type if op is not None else ""
        sides = (node.child_by_field_name("left"), node.child_by_field_name("right"))
        if symbol in _COMPARE and any(s is not None and s.type in _LITERAL for s in sides):
            return "rule"
        if symbol in _SCALE and any(_is_number(s) for s in sides):
            return "rule"
    if node.type == "object":
        numbers = [
            c
            for c in node.named_children
            if c.type == "pair" and _is_number(c.child_by_field_name("value"))
        ]
        if len(numbers) >= 2:
            return "rule"
    if node.type == "call_expression":
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if fn is not None and fn.type == "member_expression" and args is not None:
            prop = fn.child_by_field_name("property")
            first = args.named_children[0] if args.named_children else None
            if (
                prop is not None
                and _text(prop) == "status"
                and first is not None
                and _is_number(first)
            ):
                code = _text(first)
                if code.startswith("4"):
                    return "validation"
    return None


def _classify(node: Node) -> str | None:
    kinds = {k for n in _own_nodes(node) if (k := _signal(n))}
    if not kinds:
        return None
    return "validation" if "validation" in kinds else "rule"


def _candidate(path: str, node: Node, lines: list[str], kind: str) -> Candidate:
    start, end = _span(node)
    width = len(str(end))
    code = "\n".join(f"{n:>{width}}  {lines[n - 1]}" for n in range(start, end + 1))
    return Candidate(path, start, end, kind, code)


def _from_function(path: str, fn: Node, lines: list[str], limit: int) -> list[Candidate]:
    start, end = _span(fn)
    if end - start + 1 <= limit:
        kind = _classify(fn)
        if kind:
            return [_candidate(path, fn, lines, kind)]
        return []
    found = []
    for child in _walk(fn):
        if child.type != "if_statement" or child is fn:
            continue
        s, e = _span(child)
        if e - s + 1 <= limit and _enclosing(child) is fn:
            kind = _classify(child)
            if kind:
                found.append(_candidate(path, child, lines, kind))
    return found


def _enclosing(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None and parent.type not in _FUNCTION_TYPES:
        parent = parent.parent
    return parent


def find_candidates(
    reader: SnapshotReader, paths: list[str]
) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """Candidates over the given first-party source paths, plus files that could not be read."""
    limit = max_excerpt_lines()
    out: dict[tuple[str, int, int], Candidate] = {}
    unread: list[tuple[str, str]] = []
    for path in sorted(paths):
        if not path.endswith((".js", ".cjs")) or _is_test(path):
            continue
        parsed = _parse(reader, path)
        if isinstance(parsed, str):
            unread.append((path, parsed))
            continue
        lines = reader.lines(path)
        for node in _walk(parsed):
            if node.type in _FUNCTION_TYPES:
                for cand in _from_function(path, node, lines, limit):
                    out.setdefault((cand.path, cand.start, cand.end), cand)
    return sorted(out.values(), key=lambda c: (c.path, c.start, c.end)), unread
