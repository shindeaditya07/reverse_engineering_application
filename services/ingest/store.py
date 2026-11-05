"""Record a pinned source in the claim store (spec section 10)."""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import AuditLog, Snapshot, SnapshotFile
from services.ingest.pin import PinnedSource

ACTOR = "ingest"


async def store_snapshot(session: AsyncSession, pinned: PinnedSource) -> tuple[Snapshot, bool]:
    """Insert the snapshot, its files and its findings. Returns (snapshot, created).

    Ingesting the same revision again returns the existing snapshot and writes nothing. Audit
    detail holds paths, line numbers and kinds only, never a matched value (SEC-1.3).
    """
    existing = (
        await session.execute(
            select(Snapshot).where(
                Snapshot.source_kind == pinned.kind,
                Snapshot.source_ref == pinned.origin,
                Snapshot.revision == pinned.revision,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    snapshot = Snapshot(source_kind=pinned.kind, source_ref=pinned.origin, revision=pinned.revision)
    session.add(snapshot)
    await session.flush()
    subject = str(snapshot.id)

    session.add_all(
        SnapshotFile(snapshot_id=snapshot.id, path=f.path, sha256=f.sha256, size_bytes=f.size)
        for f in pinned.tree.files
    )
    session.add_all(
        AuditLog(
            actor=ACTOR,
            action="ingest.finding",
            subject_type="snapshot",
            subject_id=subject,
            detail={"path": finding.path, "line": finding.line, "kind": finding.kind},
        )
        for finding in pinned.report.findings
    )
    session.add(
        AuditLog(
            actor=ACTOR,
            action="ingest.snapshot",
            subject_type="snapshot",
            subject_id=subject,
            detail={
                "files": len(pinned.tree.files),
                "bytes": pinned.tree.total_bytes,
                "skipped": len(pinned.tree.skipped),
                "excluded": list(pinned.tree.excluded),
                "unscanned": [{"path": p, "reason": r} for p, r in pinned.report.unscanned],
                "findings": dict(Counter(f.kind for f in pinned.report.findings)),
            },
        )
    )
    await session.flush()
    return snapshot, True
