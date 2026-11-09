"""Personal data in sample and data files (SEC-1.5, key kind `pii`).

Runs the ingest scanner's personal-data patterns over data-like text files and states where
they matched, by kind and line. The values are never repeated: not in the claim, not in a log.

Two limits that shape the claim:
- The scanner is regex based. It finds e-mail addresses, phone numbers, SSN-like and card-like
  numbers and fields named like personal data. It does NOT find names or free-text addresses
  under a plain field name, so a file can hold more personal data than the claim lists. The claim
  says so.
- The matched lines are the lines V-9 would withhold a claim for. A claim cannot cite them, so
  it cites the nearest line before the first match that matches nothing, and names the matched
  lines in its text. If no such line exists the claim has no evidence and is stored Unknown.

Status is Inferred: a pattern match does not know whether a value belongs to a person (a
`support@` address is not personal data).
"""

import re

from services.discovery.agent import Finding
from services.evidence import SnapshotReader, Unresolved
from services.ingest.scan import scan_text
from services.verifier.flags import detect_flags

DATA_SUFFIXES = (".json", ".ndjson", ".csv", ".tsv", ".sql", ".txt", ".yml", ".yaml", ".xml")
LISTED_LINES = 6
_LABEL = {
    "pii:email": "e-mail addresses",
    "pii:phone": "phone numbers",
    "pii:ssn": "SSN-like numbers",
    "pii:card": "payment card numbers",
    "pii:field": "fields named like personal data (phone, address, birth date and similar)",
}
_PII = re.compile(r"^pii:")


def _lines(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:LISTED_LINES])
    return shown + (
        f" and {len(numbers) - LISTED_LINES} more" if len(numbers) > LISTED_LINES else ""
    )


def pii_findings(reader: SnapshotReader, paths: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for path in sorted(paths):
        if not path.endswith(DATA_SUFFIXES):
            continue
        flags = detect_flags(path, reader)
        if flags.generated or flags.vendored:
            continue
        try:
            lines = reader.lines(path)
        except Unresolved:
            continue
        found = [f for f in scan_text(path, "\n".join(lines)) if _PII.match(f.kind)]
        if not found:
            continue
        by_kind: dict[str, list[int]] = {}
        for f in found:
            if f.line is not None and f.line not in by_kind.setdefault(f.kind, []):
                by_kind[f.kind].append(f.line)
        matched = {n for numbers in by_kind.values() for n in numbers}
        first = min(matched)
        clean = next((n for n in range(first - 1, 0, -1) if n not in matched), None)
        parts = "; ".join(
            f"{_LABEL[k]} on {'line' if len(v) == 1 else 'lines'} {_lines(v)}"
            for k, v in sorted(by_kind.items())
        )
        out.append(
            Finding(
                f"data:pii:{path}",
                "pii",
                "inferred",
                f"{path} holds personal data by pattern: {parts}. The values are not repeated "
                f"here (SEC-1.5). Names and free-text addresses are not detected, so the file "
                f"may hold more. The cited line is the nearest one before the first match that "
                f"matches nothing.",
                ((path, clean, clean),) if clean is not None else (),
            )
        )
    return out
