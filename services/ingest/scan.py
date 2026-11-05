"""Secret and personal-data scan with redaction (SEC-1.3, SEC-1.5).

Regex based, so it only finds structured values: keys, tokens, credentials in assignments,
e-mail addresses, phone and card numbers, and fields whose name says they hold personal data.
Names and free-text addresses without such a field name are NOT found; a human review catches
those. A finding never holds the matched value, only where it was and what kind it was.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from services.ingest.tree import FileEntry, open_regular

# Implementation bound, not a rule: bigger files are listed as unscanned, never skipped silently.
# Proposed constant; it moves into rules_constants.yaml if the rules adopt a number.
SCAN_MAX_BYTES = 10 * 1024 * 1024
_BINARY_PROBE = 8000
_KEYED = r"""(?i)["']?[A-Za-z0-9_]*{names}[A-Za-z0-9_]*["']?\s*[:=]\s*(["'])({value}{{{n},}})\1"""

# (kind, pattern, group holding the value to mask; 0 = whole match). ASCII digits only on purpose.
_RULES: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("secret:private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), 0),
    ("secret:aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("secret:github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), 0),
    ("secret:slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), 0),
    (
        "secret:jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        0,
    ),
    (
        "secret:url_credentials",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:([^/\s@]{3,})@"),
        1,
    ),
    (
        "secret:credential",
        re.compile(
            _KEYED.format(
                names=r"(?:password|passwd|pwd|secret|token|api[_-]?key|auth[_-]?key)",
                value=r"[^\"'\s]",
                n=8,
            )
        ),
        2,
    ),
    ("pii:email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0),
    ("pii:ssn", re.compile(r"(?<![0-9A-Za-z])[0-9]{3}-[0-9]{2}-[0-9]{4}(?![0-9A-Za-z])"), 0),
    (
        "pii:phone",
        re.compile(
            r"(?<![0-9A-Za-z])(?:\+?[0-9]{1,3}[ .-])?\(?[0-9]{3}\)?[ .-][0-9]{3}[ .-][0-9]{4}"
            r"(?![0-9A-Za-z])"
        ),
        0,
    ),
    (
        "pii:field",
        re.compile(
            _KEYED.format(
                names=r"(?:phone|mobile|telephone|address|street|ssn|dob|birth(?:date|day)?)",
                value=r"[^\"'\n]",
                n=3,
            )
        ),
        2,
    ),
)
_CARD = re.compile(r"(?<![0-9A-Za-z])(?:[0-9][ -]?){12,18}[0-9](?![0-9A-Za-z])")


@dataclass(frozen=True)
class Finding:
    """Where a secret or personal value is and what kind it is. Never the value itself."""

    path: str
    line: int | None
    kind: str


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[Finding, ...]
    unscanned: tuple[tuple[str, str], ...]


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _spans(text: str) -> list[tuple[int, int, str]]:
    """Every (start, end, kind) to mask, with overlaps removed.

    The earliest match wins. At the same start a secret beats personal data, then the longer
    match wins.
    """
    found: list[tuple[int, int, str]] = []
    for kind, pattern, group in _RULES:
        for match in pattern.finditer(text):
            found.append((*match.span(group), kind))
    for match in _CARD.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append((*match.span(), "pii:card"))
    found.sort(key=lambda s: (s[0], s[2].startswith("pii"), -(s[1] - s[0])))
    kept: list[tuple[int, int, str]] = []
    for span in found:
        if not kept or span[0] >= kept[-1][1]:
            kept.append(span)
    return kept


def normalise(text: str) -> str:
    """CRLF and lone CR become LF, so line numbers match EVD-1.5."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def scan_text(path: str, text: str, *, numbered: bool = True) -> list[Finding]:
    text = normalise(text)
    return [
        Finding(path, text.count("\n", 0, start) + 1 if numbered else None, kind)
        for start, _, kind in _spans(text)
    ]


def redact(text: str) -> str:
    """Replace every found value with [REDACTED:<kind>]. Safe to run twice."""
    text = normalise(text)
    pieces: list[str] = []
    cursor = 0
    for start, end, kind in _spans(text):
        pieces.append(text[cursor:start])
        pieces.append(f"[REDACTED:{kind}]")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def scan_files(root: Path, files: Iterable[FileEntry]) -> ScanReport:
    findings: list[Finding] = []
    unscanned: list[tuple[str, str]] = []
    for entry in files:
        if entry.size > SCAN_MAX_BYTES:
            unscanned.append((entry.path, "too_large_to_scan"))
            continue
        with os.fdopen(open_regular(str(root / entry.path), entry.path), "rb") as handle:
            raw = handle.read(SCAN_MAX_BYTES + 1)
        if b"\0" in raw[:_BINARY_PROBE]:
            unscanned.append((entry.path, "binary"))
            continue
        try:
            findings.extend(scan_text(entry.path, raw.decode("utf-8")))
        except UnicodeDecodeError:
            # Line numbers mean nothing for an undecodable file; it is cited by byte range.
            findings.extend(scan_text(entry.path, raw.decode("utf-8", "replace"), numbered=False))
    return ScanReport(tuple(findings), tuple(unscanned))
