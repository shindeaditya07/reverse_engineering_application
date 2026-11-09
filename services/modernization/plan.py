"""Build the proposal set from accepted claims (OUT-1.3, OUT-1.5). Deterministic, no model.

Reads accepted Confirmed and Inferred claims only. A claim that is not accepted (Unknown,
undecided, rejected, replaced by an edit) is never used as a basis: only its key and kind appear,
under "Unknown dependencies". Every proposal carries the claims it rests on, and cannot be built
without one. The action sentences are fixed wording; names from the legacy code appear only as
quoted claims or as validated identifiers. Phase and boundary rules are mine: they order and group
the work, they do not measure risk.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from services.diagram.extract import extract
from services.diagram.model import DiagramClaim
from services.documentation import DocClaim

USABLE = ("confirmed", "inferred")
PHASES = {
    1: "Record behaviour and settle the basics",
    2: "Small local clean-ups",
    3: "Data ownership and boundaries",
    4: "Structural changes",
}
_NAME = re.compile(r"^\w{1,40}$")
_API = re.compile(r"^/api/(\w{1,40})")


@dataclass(frozen=True)
class Cite:
    key: str
    status: str
    text: str


@dataclass(frozen=True)
class Item:
    id: str
    phase: int
    action: str
    cites: tuple[Cite, ...]

    def __post_init__(self) -> None:
        if not self.cites:  # OUT-1.3: every risk cites a claim
            raise ValueError(f"proposal {self.id} cites no claim")


@dataclass(frozen=True)
class Boundary:
    name: str
    routes: tuple[Cite, ...]
    tables: tuple[Cite, ...]
    files: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    boundaries: tuple[Boundary, ...]
    shared_tables: tuple[Cite, ...]
    items: tuple[Item, ...]
    unknown: dict[str, tuple[str, ...]]  # kind -> keys of claims that are not accepted
    accepted: int
    total: int
    used: frozenset[str] = field(default_factory=frozenset)


def _cite(c: DocClaim) -> Cite:
    return Cite(c.key, c.status, " ".join(c.text.split()))


def _stem(path: str) -> str:
    base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return base.split("_")[0].rstrip("s")


# (kind, key prefix or None) -> (phase, fixed action sentence)
RULES: list[tuple[str, str | None, int, str]] = [
    ("rule", None, 1, "Keep this behaviour. Write a characterization test for it before changing the code around it."),  # noqa: E501
    ("validation", None, 1, "Keep this validation. Write a characterization test for it before changing the code around it."),  # noqa: E501
    ("pii", None, 1, "Decide how this personal data is classified and masked in any copy used for migration work."),  # noqa: E501
    ("encoding", None, 1, "Normalise the file encoding or line endings before tools that assume otherwise are introduced."),  # noqa: E501
    ("dependency", "disc:undeclared:", 1, "Declare this dependency and commit a lockfile, so the build can be reproduced."),  # noqa: E501
    ("error_handling", None, 2, "Handle or record the error here. As it stands a failure in this block leaves no trace."),  # noqa: E501
    ("dead_code", None, 2, "Candidate for removal. First rule out use through reflection or a computed require."),  # noqa: E501
    ("column", "data:unused:", 2, "Candidate for removal from the schema. First check reports and readers outside the snapshot."),  # noqa: E501
    ("relation", "data:relation:", 3, "Decide whether to declare this foreign key. The code behaves as if it exists."),  # noqa: E501
    ("sql_write", "data:lineage:", 3, "Choose a single owner for writes to this column before the data layer is split."),  # noqa: E501
    ("integration", None, 3, "Put this outbound call behind an interface so it can be replaced or stubbed."),  # noqa: E501
    ("job", None, 3, "Move this scheduled work to an explicit scheduler that can be monitored."),
    ("flow", "ca:callback-chain:", 4, "Candidate to convert from nested callbacks to a flatter form, once behaviour is recorded."),  # noqa: E501
    ("flow", "ca:promise-chain:", 4, "Candidate to convert from a promise chain to async functions, once behaviour is recorded."),  # noqa: E501
    ("provenance", None, 4, "Decide whether to replace this generated or vendored code with a maintained dependency or a build step."),  # noqa: E501
]  # fmt: skip
CROSS = "This code writes to a table that another candidate boundary owns. Route the write through that boundary's interface."  # noqa: E501


def _boundaries(usable: list[DocClaim]) -> tuple[list[Boundary], list[Item], list[Cite]]:
    by_key = {c.key: c for c in usable}
    found = extract([DiagramClaim(c.key, c.kind, c.status, c.text) for c in usable])
    names: dict[str, set[str]] = defaultdict(set)  # boundary -> route claim keys
    route_files: dict[str, set[str]] = defaultdict(set)
    for r in found.routes:
        for route in r.routes:
            m = _API.match(route.split(" ", 1)[1]) if " " in route else None
            if m and _NAME.match(m[1]):
                names[m[1]].add(r.key)
                route_files[m[1]].add(r.file)
    table_of = {t.name: t for t in found.tables if _NAME.match(t.name)}
    owner: dict[str, str] = {}
    for b in names:
        for t in table_of:
            if t.rstrip("s") == b.rstrip("s"):
                owner[t] = b
    files_of: dict[str, set[str]] = {b: set(route_files[b]) for b in names}
    for a in found.access:
        for b in names:
            if _stem(a.file) == b.rstrip("s"):
                files_of[b].add(a.file)
    boundaries = [
        Boundary(
            b,
            tuple(_cite(by_key[k]) for k in sorted(names[b])),
            tuple(_cite(by_key[table_of[t].key]) for t, o in sorted(owner.items()) if o == b),
            tuple(sorted(files_of[b])),
        )
        for b in sorted(names)
    ]
    shared = [_cite(by_key[t.key]) for n, t in sorted(table_of.items()) if n not in owner]
    cross: list[Item] = []
    for a in sorted(found.access, key=lambda x: x.key):
        if a.verb != "writes":
            continue
        mine = {b for b, files in files_of.items() if a.file in files}
        for t in a.tables:
            other = owner.get(t)
            if other and mine and other not in mine and t in table_of:
                cites = (_cite(by_key[a.key]), _cite(by_key[table_of[t].key]))
                cross.append(Item("", 3, CROSS, cites))
    return boundaries, cross, shared


def build_plan(claims: list[DocClaim]) -> Plan:
    usable = [c for c in claims if c.accepted and c.status in USABLE]
    raw: list[tuple[int, str, str, tuple[Cite, ...]]] = []
    used: set[str] = set()
    for c in usable:
        for kind, prefix, phase, action in RULES:
            if c.kind == kind and (prefix is None or c.key.startswith(prefix)):
                raw.append((phase, c.key, action, (_cite(c),)))
                used.add(c.key)
                break
    boundaries, cross, shared = _boundaries(usable)
    for item in cross:
        raw.append((item.phase, item.cites[0].key, item.action, item.cites))
        used.update(c.key for c in item.cites)
    for b in boundaries:
        used.update(c.key for c in (*b.routes, *b.tables))
    used.update(c.key for c in shared)
    raw.sort(key=lambda r: (r[0], r[1], r[2]))
    items = tuple(Item(f"P-{n:02d}", p, a, cites) for n, (p, _, a, cites) in enumerate(raw, 1))
    unknown: dict[str, list[str]] = defaultdict(list)
    for c in claims:
        if c.key not in {u.key for u in usable}:
            unknown[c.kind].append(c.key)
    return Plan(
        tuple(boundaries),
        tuple(shared),
        items,
        {k: tuple(sorted(v)) for k, v in sorted(unknown.items())},
        len(usable),
        len(claims),
        frozenset(used),
    )
