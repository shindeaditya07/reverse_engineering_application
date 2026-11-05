"""A plain grep and regex finder for routes, SQL and validation (spec section 19, item 2).

It is deliberately naive: one line at a time, no parsing, no call graph, no idea what a loop,
a condition or a variable is. Agents must beat it, so it must not be good. The patterns come
from common Express and MySQL idioms, were written before the first score and are never tuned
to the fixture (build-plan step 10). `patterns_sha256` fingerprints them; a changed pattern
changes the hash and the committed baseline result must then be re-run in the open.

Every finding is Inferred, never Confirmed: a regex hit is a heuristic, not a parse (CLM-1.2,
CLM-1.3). It does not skip generated, vendored or test files; a grep would not.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from services.evals.key import Span
from services.evals.score import Produced
from services.evidence import SnapshotReader

FILE_SUFFIXES = (".js", ".cjs", ".mjs", ".ts")


@dataclass(frozen=True)
class Pattern:
    kind: str
    regex: re.Pattern[str]


PATTERNS: tuple[Pattern, ...] = (
    # Express: app.get('/x', ...), router.post("/y", ...)
    Pattern(
        "route",
        re.compile(
            r"""\b(?:app|router|server)\.(?:get|post|put|patch|delete|head|options|all)\s*\(\s*['"`]/"""
        ),
    ),
    # SQL text inside a string: SELECT ... FROM
    Pattern("sql_read", re.compile(r"\bSELECT\b.+\bFROM\b", re.IGNORECASE)),
    # SQL text inside a string: INSERT INTO / UPDATE t SET / DELETE FROM
    Pattern(
        "sql_write",
        re.compile(r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.IGNORECASE),
    ),
    # A rejected request: res.status(400), res.status(422), res.sendStatus(400)
    Pattern("validation", re.compile(r"\bres\.(?:status|sendStatus)\(\s*4(?:00|22)\s*\)")),
    # A thrown error that says it is about validation
    Pattern("validation", re.compile(r"\bthrow\s+new\s+\w*(?:Validation|Invalid)\w*\(")),
)


def patterns_sha256() -> str:
    """Fingerprint of every pattern and its kind, in order."""
    digest = hashlib.sha256()
    for p in PATTERNS:
        digest.update(f"{p.kind}\0{p.regex.pattern}\0{p.regex.flags}\n".encode())
    return digest.hexdigest()


def find_in_file(reader: SnapshotReader, path: str) -> list[Produced]:
    """One claim per matching line and kind. Raises Unresolved for an undecodable file."""
    claims = []
    for number, line in enumerate(reader.lines(path), 1):
        for pattern in PATTERNS:
            if pattern.regex.search(line):
                claims.append(
                    Produced(
                        f"grep:{path}:{number}:{pattern.kind}",
                        pattern.kind,
                        "inferred",
                        (Span(path, number, number),),
                    )
                )
    return claims


def source_files(paths: Sequence[str]) -> list[str]:
    return sorted(p for p in paths if p.endswith(FILE_SUFFIXES))
