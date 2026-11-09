"""A diagram that can only contain elements that name the claims they come from (OUT-1.1).

`Builder.node` and `Builder.edge` refuse an element with no claim key, so a diagram built through
them cannot hold an unmapped node or edge. The mapping is returned next to the Mermaid text.
"""

import re
from dataclasses import dataclass, field

_UNSAFE = re.compile(r"[^A-Za-z0-9 _./:,()+\-*=?$@#]")
_IDENT = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True)
class DiagramClaim:
    key: str
    kind: str
    status: str  # "confirmed" or "inferred"; Unknown claims are never drawn
    text: str


@dataclass(frozen=True)
class Diagram:
    name: str
    title: str
    mermaid: str
    mapping: dict[str, tuple[str, ...]]  # node id or "a->b#n" edge id -> claim keys
    omitted: tuple[tuple[str, str], ...] = ()  # (claim key, why it was not drawn)


def label(value: str, limit: int = 60) -> str:
    """Text that is safe inside a quoted Mermaid label. Legacy names can hold anything."""
    cleaned = " ".join(_UNSAFE.sub("_", value).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."


def ident(value: str) -> str:
    return _IDENT.sub("_", value) or "_"


@dataclass
class Builder:
    lines: list[str] = field(default_factory=list)
    mapping: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _edges: int = 0

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def _need(self, keys: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        if not keys:
            raise ValueError("a diagram element must map to at least one claim (OUT-1.1)")
        return tuple(sorted(set(keys)))

    def node(self, node_id: str, line: str, keys: list[str] | tuple[str, ...]) -> None:
        self.mapping[node_id] = self._need(keys)
        self.lines.append(line)

    def edge(self, a: str, b: str, line: str, keys: list[str] | tuple[str, ...]) -> None:
        self._edges += 1
        self.mapping[f"{a}->{b}#{self._edges}"] = self._need(keys)
        self.lines.append(line)
