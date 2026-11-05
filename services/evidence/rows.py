"""Convert between references and `evidence` table rows. Pure: no database access here."""

import uuid
from typing import Any

from services.db.models import Evidence
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
from services.evidence.resolve import Resolution

_LOCATED = {
    "schema_object": SchemaObject,
    "config_key": ConfigKey,
    "build_step": BuildStep,
    "ticket": Ticket,
}


def evidence_row_fields(
    ref: EvidenceRef, resolution: Resolution, claim_version_id: uuid.UUID, snapshot_id: uuid.UUID
) -> dict[str, Any]:
    """Column values for a new Evidence row. Only a resolved reference may be stored (EVD-1.2)."""
    if resolution.status != "resolved" or resolution.content_hash is None:
        raise ValueError(f"cannot store evidence that is {resolution.status}: {resolution.reason}")
    fields: dict[str, Any] = {
        "claim_version_id": claim_version_id,
        "snapshot_id": snapshot_id,
        "kind": ref.kind,
        "path": ref.path,
        "content_hash": resolution.content_hash,
    }
    if isinstance(ref, FileRange):
        fields.update(
            start_line=ref.start_line,
            end_line=ref.end_line,
            start_byte=ref.start_byte,
            end_byte=ref.end_byte,
        )
    elif isinstance(ref, LogLine):
        fields.update(start_line=ref.line, end_line=ref.line)
    else:
        fields.update(object_name=ref.object_name, start_line=ref.line, end_line=ref.line)
    return fields


def ref_from_row(row: Evidence) -> EvidenceRef:
    """Rebuild the reference stored in a row. Raises ValueError if the row is not a valid one."""
    if row.path is None:
        raise ValueError("evidence row has no path")
    if row.kind == "file_range":
        return FileRange(
            path=row.path,
            start_line=row.start_line,
            end_line=row.end_line,
            start_byte=row.start_byte,
            end_byte=row.end_byte,
        )
    if row.kind == "log_line":
        return LogLine(path=row.path, line=row.start_line or 0)
    if row.kind in _LOCATED and row.object_name:
        return parse_ref(
            {
                "kind": row.kind,
                "path": row.path,
                "object_name": row.object_name,
                "line": row.start_line,
            }
        )
    raise ValueError(f"evidence row of kind {row.kind!r} cannot be rebuilt")
