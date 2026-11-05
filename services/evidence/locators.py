"""Find an object in a file and return its 1-based inclusive line span.

Schema objects use a small DDL scanner (CREATE TABLE, CREATE INDEX, ALTER TABLE ... ADD
CONSTRAINT); config keys, build steps and tickets are matched line by line. It is a locator,
not a parser: it finds where a name is declared, and a name it cannot find is "unresolved",
never guessed.
"""

import re

from services.evidence.errors import Unresolved

Span = tuple[int, int]
_IDENT = r"""(?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_$]*)"""
_QNAME = rf"(?:{_IDENT}\s*\.\s*)?({_IDENT})"
_CREATE_TABLE = re.compile(
    rf"\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_QNAME}\s*\(", re.I
)
_CREATE_INDEX = re.compile(
    rf"\bCREATE\s+(?:UNIQUE\s+|FULLTEXT\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?{_QNAME}\s+ON\b", re.I
)
_ALTER_CONSTRAINT = re.compile(
    rf"\bALTER\s+TABLE\s+(?:ONLY\s+)?{_QNAME}\s+ADD\s+CONSTRAINT\s+{_QNAME}", re.I
)
_ITEM_CONSTRAINT = re.compile(rf"^CONSTRAINT\s+{_IDENT}", re.I)
_ITEM_INDEX = re.compile(rf"^(?:UNIQUE\s+|FULLTEXT\s+)?(?:KEY|INDEX)\s+({_IDENT})", re.I)
_TABLE_LEVEL = re.compile(r"^(?:PRIMARY|FOREIGN|UNIQUE|KEY|INDEX|CHECK|FULLTEXT|EXCLUDE)\b", re.I)


def _unquote(name: str) -> str:
    return (name[1:-1] if name[:1] in '`"[' else name).lower()


def _blank_comments(text: str) -> str:
    """Replace comments with spaces, keeping every newline so line numbers stay true."""
    out: list[str] = []
    i, n, quote = 0, len(text), ""
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
            out.append(ch)
        elif text.startswith("--", i) or ch == "#":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.extend("\n" if c == "\n" else " " for c in text[i:end])
            i = end
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _body(text: str, open_at: int) -> tuple[int, list[tuple[int, int]]]:
    """From the '(' at open_at: the index of its ')' and the (start, end) of each top-level item."""
    depth, quote, start, items = 0, "", open_at + 1, []
    for i in range(open_at, len(text)):
        ch = text[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                items.append((start, i))
                return i, items
        elif ch == "," and depth == 1:
            items.append((start, i))
            start = i + 1
    raise Unresolved("not_found", "unbalanced parentheses in the DDL")


def _span(text: str, start: int, end: int) -> Span:
    """Line span of text[start:end] with surrounding whitespace trimmed away."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return text.count("\n", 0, start) + 1, text.count("\n", 0, max(end - 1, start)) + 1


def _statement_end(text: str, start: int) -> int:
    end = text.find(";", start)
    return len(text) if end == -1 else end + 1


def _pick(spans: list[Span], what: str) -> Span:
    if not spans:
        raise Unresolved("not_found", f"{what} is not declared in this file")
    if len(set(spans)) > 1:
        raise Unresolved("ambiguous", f"{what} is declared {len(spans)} times")
    return spans[0]


def locate_schema(lines: list[str], object_name: str) -> Span:
    kind, _, name = object_name.partition(":")
    name = name.strip().lower()
    if kind not in ("table", "column", "index", "constraint") or not name:
        raise Unresolved(
            "bad_object_name", "use table:<t>, column:<t>.<c>, index:<i>, constraint:<t>.<c>"
        )
    text = _blank_comments("\n".join(lines))
    table, _, member = name.partition(".")
    if kind in ("column", "constraint") and not member:
        raise Unresolved("bad_object_name", f"{kind}: needs <table>.<name>")
    found: list[Span] = []
    if kind == "index":
        for match in _CREATE_INDEX.finditer(text):
            if _unquote(match.group(1)) == name:
                found.append(_span(text, match.start(), _statement_end(text, match.start())))
    if kind == "constraint":
        for match in _ALTER_CONSTRAINT.finditer(text):
            if _unquote(match.group(1)) == table and _unquote(match.group(2)) == member:
                found.append(_span(text, match.start(), _statement_end(text, match.start())))
    for match in _CREATE_TABLE.finditer(text):
        close, items = _body(text, match.end() - 1)
        is_table = _unquote(match.group(1)) == (table if kind != "table" else name)
        if kind == "table" and is_table:
            found.append(_span(text, match.start(), close + 1))
        elif kind in ("column", "constraint", "index") and (is_table or kind == "index"):
            for start, end in items:
                item = text[start:end].strip()
                declared = _declared_name(kind, item)
                wanted = member if kind != "index" else name
                if declared is not None and declared == wanted:
                    found.append(_span(text, start, end))
    return _pick(found, object_name)


def _declared_name(kind: str, item: str) -> str | None:
    if kind == "constraint":
        if _ITEM_CONSTRAINT.match(item):
            return _unquote(item.split(None, 2)[1])
        return None
    if kind == "index":
        match = _ITEM_INDEX.match(item)
        return _unquote(match.group(1)) if match else None
    if not item or _TABLE_LEVEL.match(item) or _ITEM_CONSTRAINT.match(item):
        return None
    first = re.match(_IDENT, item)
    return _unquote(first.group(0)) if first else None


def _choose(lines: list[str], hits: list[int], hint: int | None, what: str) -> Span:
    """hits are 1-based line numbers. A hint must be one of them; without one, one hit is needed."""
    if hint is not None:
        if hint in hits:
            return hint, hint
        raise Unresolved("not_found", f"{what} does not occur on line {hint}")
    if not hits:
        raise Unresolved("not_found", f"{what} does not occur in this file")
    if len(hits) > 1:
        raise Unresolved("ambiguous", f"{what} occurs on lines {hits}; give `line`")
    return hits[0], hits[0]


def _matching(lines: list[str], pattern: re.Pattern[str]) -> list[int]:
    return [number for number, line in enumerate(lines, 1) if pattern.search(line)]


def locate_config_key(lines: list[str], name: str, hint: int | None) -> Span:
    key = re.escape(name.split(".")[-1].strip())
    pattern = re.compile(rf"""(?:^|[^A-Za-z0-9_$])["']?{key}["']?\s*[:=]""")
    return _choose(lines, _matching(lines, pattern), hint, f"config key {name!r}")


def locate_build_step(lines: list[str], name: str, hint: int | None) -> Span:
    kind, _, value = name.partition(":")
    value = value.strip()
    if not value:
        raise Unresolved(
            "bad_object_name",
            "use npm:<script>, make:<target>, docker:<INSTRUCTION> or step:<text>",
        )
    if kind == "npm":
        pattern = re.compile(rf"""^\s*["']{re.escape(value)}["']\s*:""")
    elif kind == "make":
        pattern = re.compile(rf"^{re.escape(value)}\s*:(?!=)")
    elif kind == "docker":
        pattern = re.compile(rf"^\s*{re.escape(value)}\s", re.I)
    elif kind == "step":
        pattern = re.compile(re.escape(value))
    else:
        raise Unresolved("bad_object_name", f"unknown build step kind {kind!r}")
    return _choose(lines, _matching(lines, pattern), hint, f"build step {name!r}")


def locate_ticket(lines: list[str], name: str, hint: int | None) -> Span:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name.strip())}(?![A-Za-z0-9])")
    return _choose(lines, _matching(lines, pattern), hint, f"ticket {name!r}")
