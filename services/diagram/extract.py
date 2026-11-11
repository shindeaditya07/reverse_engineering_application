"""Read structure out of stored claims. Only fixed templates the analyzers write are parsed.

A claim whose text does not match (for example one a reviewer edited) is not drawn and is
listed as omitted with the reason, never guessed at. tests/test_diagram.py runs every analyzer
over the fixture and fails if a template changes without this module following.
"""

import re
from dataclasses import dataclass

from services.diagram.model import DiagramClaim

_TABLE = re.compile(
    r"^(?P<file>\S+) defines table (?P<name>\w+) with columns (?P<cols>[\w, ]+?)"
    r"(?: \(primary key (?P<pk>[\w, ]+)\)| \(no primary key\))?\.$"
)
_GUESSED = re.compile(
    r"^(?P<t>\w+)\.(?P<c>\w+) looks like a reference to (?P<rt>\w+)\.(?P<rc>\w+) by its name"
)
_DECLARED = re.compile(r"^(?P<file>\S+) declares a foreign key (?P<pair>.+)\.$")
_PAIR = re.compile(r"(?P<t>\w+)\((?P<c>[\w, ]+)\)\s*(?:->|references|to)\s*(?P<rt>\w+)")
_SQL = re.compile(r"^(?P<file>\S+) line (?P<line>\d+) (?P<body>.+)$")
_ROUTES = re.compile(r"^(?P<file>\S+) line (?P<line>\d+) registers (?P<list>.+?)(?: \(|\.$)")
_ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|ALL|USE) (\S+)")
_STEPS = re.compile(
    r"(?:in source order|in order|error-first callbacks): (?P<steps>.+?)\.(?: Each step .*)?$"
)
_FLOW_HEAD = re.compile(r"^(?P<fn>.+?) in (?P<file>\S+) line (?P<line>\d+)")


@dataclass(frozen=True)
class Table:
    key: str
    status: str
    name: str
    columns: tuple[str, ...]
    primary: tuple[str, ...]


@dataclass(frozen=True)
class Relation:
    key: str
    status: str
    table: str
    column: str
    ref_table: str
    declared: bool


@dataclass(frozen=True)
class Access:
    key: str
    status: str
    file: str
    line: int
    verb: str  # "reads" or "writes"
    tables: tuple[str, ...]


@dataclass(frozen=True)
class Route:
    key: str
    status: str
    file: str
    routes: tuple[str, ...]  # "GET /api/x"


@dataclass(frozen=True)
class Outbound:
    key: str
    status: str
    file: str
    line: int
    what: str  # "HTTP call" or "network connection" or "timer"


@dataclass(frozen=True)
class Flow:
    key: str
    status: str
    name: str
    file: str
    line: int
    kind: str  # "async" or "callbacks" or "promises"
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Extracted:
    tables: tuple[Table, ...]
    relations: tuple[Relation, ...]
    access: tuple[Access, ...]
    routes: tuple[Route, ...]
    outbound: tuple[Outbound, ...]
    flows: tuple[Flow, ...]
    omitted: tuple[tuple[str, str], ...]


def _names(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in value.split(",") if p.strip())


def _access(c: DiagramClaim, m: re.Match[str]) -> Access | None:
    body = m["body"]
    file, line = m["file"], int(m["line"])
    if body.startswith("reads "):
        found = re.search(r" from (?P<t>[\w, ]+?)(?:\.|$)", body.split(". ")[0] + ".")
        return Access(c.key, c.status, file, line, "reads", _names(found["t"])) if found else None
    if body.startswith("inserts into "):
        found = re.match(r"inserts into (?P<t>[\w, ]+?)(?: setting|\.|$)", body)
        return Access(c.key, c.status, file, line, "writes", _names(found["t"])) if found else None
    if body.startswith(("updates ", "deletes from ")):
        qualified = re.findall(r"\b(\w+)\.\w+", body.split(";")[0])
        tables = tuple(dict.fromkeys(qualified[:1]))
        return Access(c.key, c.status, file, line, "writes", tables) if tables else None
    return None


def extract(claims: list[DiagramClaim]) -> Extracted:
    tables: list[Table] = []
    relations: list[Relation] = []
    access: list[Access] = []
    routes: list[Route] = []
    outbound: list[Outbound] = []
    flows: list[Flow] = []
    omitted: list[tuple[str, str]] = []

    for c in sorted(claims, key=lambda x: x.key):
        if c.status not in ("confirmed", "inferred"):
            continue  # Unknown is never drawn
        key = c.key
        if key.startswith("data:table:"):
            m = _TABLE.match(c.text)
            if m:
                pk = _names(m["pk"] or "")
                tables.append(Table(key, c.status, m["name"], _names(m["cols"]), pk))
            else:
                omitted.append((key, "table claim text is not in the expected form"))
        elif key.startswith("data:relation:"):
            g = _GUESSED.match(c.text)
            d = _DECLARED.match(c.text)
            if g:
                relations.append(Relation(key, c.status, g["t"], g["c"], g["rt"], False))
            elif d and (p := _PAIR.search(d["pair"])):
                relations.append(Relation(key, c.status, p["t"], p["c"], p["rt"], True))
            else:
                omitted.append((key, "relation claim text is not in the expected form"))
        elif key.startswith("data:sql:"):
            m = _SQL.match(c.text)
            found = _access(c, m) if m else None
            if found is not None:
                access.append(found)
            else:
                omitted.append((key, "SQL claim names no table to draw"))
        elif key.startswith("ca:route:"):
            m = _ROUTES.match(c.text)
            listed = (
                tuple(f"{v} {p.rstrip(',')}" for v, p in _ROUTE.findall(m["list"])) if m else ()
            )
            if m and listed:
                routes.append(Route(key, c.status, m["file"], listed))
            else:
                omitted.append((key, "route claim names no route to draw"))
        elif key.startswith(("disc:http:", "disc:socket:", "disc:timer:")):
            m = re.match(r"^(?P<file>\S+) line (?P<line>\d+) ", c.text)
            what = {"http": "HTTP call", "socket": "network connection", "timer": "timer"}[
                key.split(":")[1]
            ]
            if m:
                outbound.append(Outbound(key, c.status, m["file"], int(m["line"]), what))
            else:
                omitted.append((key, "claim text is not in the expected form"))
        elif key.startswith(("ca:async-flow:", "ca:callback-chain:", "ca:promise-chain:")):
            h, s = _FLOW_HEAD.match(c.text), _STEPS.search(c.text)
            if h and s:
                kind = {"async-flow": "async", "callback-chain": "callbacks"}.get(
                    key.split(":")[1], "promises"
                )
                steps = tuple(p.strip() for p in s["steps"].split(", ") if p.strip())
                flows.append(Flow(key, c.status, h["fn"], h["file"], int(h["line"]), kind, steps))
            else:
                omitted.append((key, "flow claim text is not in the expected form"))
    return Extracted(
        tuple(tables),
        tuple(relations),
        tuple(access),
        tuple(routes),
        tuple(outbound),
        tuple(flows),
        tuple(omitted),
    )
