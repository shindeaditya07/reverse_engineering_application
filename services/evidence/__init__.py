"""Evidence: turn a reference into the exact bytes it points at (EVD-1.1 to EVD-1.5)."""

from services.evidence.reader import SnapshotReader, Unresolved
from services.evidence.refs import (
    BuildStep,
    ConfigKey,
    EvidenceRef,
    FileRange,
    LogLine,
    SchemaObject,
    Ticket,
    parse_ref,
)
from services.evidence.resolve import Resolution, check_hash, resolve, split_range
from services.evidence.rows import evidence_row_fields, ref_from_row

__all__ = [
    "BuildStep",
    "ConfigKey",
    "EvidenceRef",
    "FileRange",
    "LogLine",
    "Resolution",
    "SchemaObject",
    "SnapshotReader",
    "Ticket",
    "Unresolved",
    "check_hash",
    "evidence_row_fields",
    "parse_ref",
    "ref_from_row",
    "resolve",
    "split_range",
]
