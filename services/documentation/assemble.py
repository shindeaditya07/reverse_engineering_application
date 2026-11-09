"""Assemble documents from claims (CLM-1.6, OUT-1.2).

Every sentence about the application in a document is a stored claim's text, copied verbatim and
followed by its claim key. The only other text is fixed wording that says how to read the page and
makes no statement about the application. Nothing is paraphrased, so nothing can be added: a
model-written connecting sentence is deliberately not built (see docs/documentation.md).
`check` re-reads a rendered document and fails if any bullet is not a stored claim, verbatim.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

STATUS = {"confirmed": "Confirmed", "inferred": "Inferred", "unknown": "Unknown"}

# kind -> (document, section). Lineage and unused-column claims are told apart by key prefix.
PLACE: dict[str, tuple[str, str]] = {
    "route": ("api-reference", "Routes"),
    "table": ("data-reference", "Tables"),
    "relation": ("data-reference", "Relations"),
    "sql_read": ("data-reference", "Reads"),
    "sql_write": ("data-reference", "Writes"),
    "column": ("data-reference", "Columns"),
    "pii": ("data-reference", "Personal data"),
    "rule": ("business-rules", "Rules"),
    "validation": ("business-rules", "Validation"),
    "integration": ("runbook", "Outbound calls"),
    "job": ("runbook", "Scheduled work"),
    "dependency": ("runbook", "Dependencies"),
    "error_handling": ("runbook", "Error handling"),
    "flow": ("runbook", "Step order"),
    "dead_code": ("runbook", "Unused code"),
    "provenance": ("runbook", "Generated and vendored code"),
    "encoding": ("runbook", "File encoding"),
}
TITLES = {
    "api-reference": "API and interface reference",
    "data-reference": "Data reference",
    "business-rules": "Business rules",
    "runbook": "Runbook facts",
    "glossary": "Glossary",
    "open-questions": "Open questions",
}
INTRO = {
    "api-reference": "Routes found by static analysis. Nothing here was run.",
    "data-reference": "Tables, columns, statements and personal-data findings found in the code.",
    "business-rules": "Rules and validation found in the code. Model-drafted rules are Inferred "
    "and need a human check.",
    "runbook": "Facts that matter when running the system. These are observations from the "
    "code, not instructions.",
    "glossary": "Table names used in this application, each with the claim that defines it.",
    "open-questions": "Things the analysis could not settle, and claims waiting for a reviewer.",
}
ORDER = tuple(TITLES)
LINE = re.compile(r"^- \*\*(Confirmed|Inferred|Unknown)\*\* (.+) \(claim `([^`]+)`\)$")


@dataclass(frozen=True)
class DocClaim:
    key: str
    kind: str
    status: str
    text: str
    accepted: bool = False
    reason: str | None = None  # why it is in the review queue, if it is


@dataclass(frozen=True)
class Doc:
    name: str
    title: str
    markdown: str
    keys: tuple[str, ...]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _bullet(c: DocClaim) -> str:
    return f"- **{STATUS[c.status]}** {_one_line(c.text)} (claim `{c.key}`)"


def _place(c: DocClaim) -> tuple[str, str] | None:
    if c.kind == "sql_write" and c.key.startswith("data:lineage:"):
        return ("data-reference", "Column write sources")
    return PLACE.get(c.kind)


def _render(name: str, sections: dict[str, list[DocClaim]], stamp: str) -> Doc:
    out = [f"# {TITLES[name]}", "", stamp, "", INTRO[name]]
    keys: list[str] = []
    for heading, claims in sections.items():
        out += ["", f"## {heading}", ""]
        for c in sorted(claims, key=lambda c: c.key):
            out.append(_bullet(c))
            keys.append(c.key)
    return Doc(name, TITLES[name], "\n".join(out) + "\n", tuple(keys))


def assemble(
    claims: list[DocClaim], *, stamp: str, accepted_only: bool
) -> tuple[list[Doc], dict[str, int]]:
    """(documents, claims of a kind with no place, by kind). A document with nothing in it is
    not written. Unknown claims and queued claims go to open-questions only."""
    placed: dict[str, dict[str, list[DocClaim]]] = defaultdict(lambda: defaultdict(list))
    unplaced: dict[str, int] = defaultdict(int)
    for c in claims:
        if c.status == "unknown" or c.reason:
            placed["open-questions"]["Needs a decision"].append(c)
        if c.status == "unknown":
            continue
        if accepted_only and not c.accepted:
            continue
        where = _place(c)
        if where is None:
            unplaced[c.kind] += 1
            continue
        placed[where[0]][where[1]].append(c)
        if c.kind == "table":
            placed["glossary"]["Tables"].append(c)
    docs = [_render(n, placed[n], stamp) for n in ORDER if placed.get(n)]
    return docs, dict(sorted(unplaced.items()))


def check(markdown: str, claims: list[DocClaim]) -> list[str]:
    """CLM-1.6: every bullet must be a stored claim, verbatim, with its status. Returns the
    problems; empty means every statement in the document is backed by a claim."""
    by_key = {c.key: c for c in claims}
    problems = []
    for line in markdown.splitlines():
        if not line.startswith("- "):
            continue
        m = LINE.match(line)
        if m is None:
            problems.append(f"not a claim line: {line[:80]}")
            continue
        status, text, key = m.groups()
        c = by_key.get(key)
        if c is None:
            problems.append(f"unknown claim {key}")
        elif STATUS[c.status] != status or _one_line(c.text) != text:
            problems.append(f"{key}: text or status differs from the stored claim")
    return problems
