"""Resolve a reference to bytes, hash them, and detect staleness (EVD-1.2, EVD-1.3, EVD-1.4).

The excerpt that comes back is redacted (SEC-1.3). The hash is taken over the real bytes before
redaction, so it still detects a change to a value that is hidden from the reader.
"""

import hashlib
from dataclasses import dataclass, replace
from typing import Literal

from services.evidence import locators
from services.evidence.errors import Unresolved
from services.evidence.reader import SnapshotReader
from services.evidence.refs import (
    BuildStep,
    ConfigKey,
    EvidenceRef,
    FileRange,
    LogLine,
    SchemaObject,
    Ticket,
    max_excerpt_lines,
)
from services.ingest.scan import redact

Status = Literal["resolved", "stale", "unresolved"]


@dataclass(frozen=True)
class Resolution:
    status: Status
    reason: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    start_byte: int | None = None
    end_byte: int | None = None
    excerpt: str = ""
    content_hash: str | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _by_lines(reader: SnapshotReader, path: str, span: tuple[int, int]) -> Resolution:
    start, end = span
    if end - start + 1 > max_excerpt_lines():
        raise Unresolved(
            "span_too_long", f"spans {end - start + 1} lines; cite a smaller part (EVD-1.4)"
        )
    lines = reader.lines(path)
    if end > len(lines):
        raise Unresolved("out_of_range", f"file has {len(lines)} lines, range ends at {end}")
    text = "\n".join(lines[start - 1 : end])
    return Resolution(
        "resolved", None, start, end, excerpt=redact(text), content_hash=_sha(text.encode("utf-8"))
    )


def _by_bytes(reader: SnapshotReader, ref: FileRange) -> Resolution:
    data = reader.raw(ref.path)
    start, end = ref.start_byte or 0, ref.end_byte or 0
    if end > len(data):
        raise Unresolved("out_of_range", f"file has {len(data)} bytes, range ends at {end}")
    piece = data[start:end]
    shown = redact(piece.decode("utf-8", "backslashreplace"))
    return Resolution(
        "resolved", None, start_byte=start, end_byte=end, excerpt=shown, content_hash=_sha(piece)
    )


def _resolve(ref: EvidenceRef, reader: SnapshotReader) -> Resolution:
    if isinstance(ref, FileRange):
        if ref.start_byte is not None:
            return _by_bytes(reader, ref)
        return _by_lines(reader, ref.path, (ref.start_line or 0, ref.end_line or 0))
    if isinstance(ref, LogLine):
        return _by_lines(reader, ref.path, (ref.line, ref.line))
    lines = reader.lines(ref.path)
    if isinstance(ref, SchemaObject):
        span = locators.locate_schema(lines, ref.object_name)
    elif isinstance(ref, ConfigKey):
        span = locators.locate_config_key(lines, ref.object_name, ref.line)
    elif isinstance(ref, BuildStep):
        span = locators.locate_build_step(lines, ref.object_name, ref.line)
    elif isinstance(ref, Ticket):
        span = locators.locate_ticket(lines, ref.object_name, ref.line)
    else:  # pragma: no cover - the union is closed
        raise Unresolved("unknown_kind", "unsupported evidence kind")
    return _by_lines(reader, ref.path, span)


def resolve(ref: EvidenceRef, reader: SnapshotReader) -> Resolution:
    """Never raises for a bad reference: a reference that does not resolve says why."""
    try:
        return _resolve(ref, reader)
    except Unresolved as error:
        return Resolution("unresolved", f"{error.reason}: {error.detail}")


def check_hash(ref: EvidenceRef, expected_hash: str, reader: SnapshotReader) -> Resolution:
    """EVD-1.3: resolves, but to different bytes than were cited, means stale."""
    found = resolve(ref, reader)
    if found.status == "resolved" and found.content_hash != expected_hash:
        return replace(found, status="stale", reason="content_changed")
    return found


def split_range(path: str, start_line: int, end_line: int) -> list[FileRange]:
    """EVD-1.4: cut a long line span into ranges that each fit the limit."""
    if start_line < 1 or end_line < start_line:
        raise ValueError("lines count from 1 and need start_line <= end_line")
    size = max_excerpt_lines()
    return [
        FileRange(path=path, start_line=first, end_line=min(first + size - 1, end_line))
        for first in range(start_line, end_line + 1, size)
    ]
