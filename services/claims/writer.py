"""Write a verified claim to the store: claim, version, evidence, check results, review item and
audit entry, in the caller's transaction.

Rules this module enforces, each with a test:
- Idempotent per (run, key). A second write of the same key returns the first and adds nothing,
  so a run killed halfway and resumed never duplicates a claim (AGENTS.md section 4).
- A claim that failed any check, or is stale, is stored as Unknown and queued as a verifier
  failure or stale item. It never keeps a status that would let it stand (VER-1.2, REV-2.1).
  Its verdict, including the status it asked for, goes to the audit entry.
- A claim that failed V-9 holds a secret or personal data. Its text is not stored (SEC-1.3,
  SEC-1.5); a fixed placeholder is, and the check ID is the only trace.
- Evidence rows are stored only for references that resolve, with the hash computed now. A
  Confirmed or Inferred version with no evidence is refused by the database at commit.
- Audit detail holds IDs, kinds and counts, never text or excerpts (NFR-5, SEC-1.3).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import (
    AuditLog,
    Claim,
    ClaimVersion,
    Evidence,
    ReviewItem,
    VerificationResult,
)
from services.evidence import SnapshotReader, parse_ref, resolve
from services.evidence.rows import evidence_row_fields
from services.verifier import ClaimInput, Verdict, verify_claim
from services.verifier.models import PRODUCER_KINDS, STATUSES
from services.verifier.rows import result_rows

WITHHELD_TEXT = "[text withheld: it matched a secret or personal-data pattern (V-9)]"
FIRST_VERSION = 1


class ClaimRejected(ValueError):
    """The claim is malformed (a status or producer kind the schema does not know). That is a
    bug in the analyzer, not a claim, so nothing is stored and the job fails visibly."""


@dataclass(frozen=True)
class StoredClaim:
    claim_id: uuid.UUID
    version_id: uuid.UUID
    created: bool  # False: the key already existed in this run and nothing was written
    status: str  # as stored
    queued_reason: str | None


def _stored_status(verdict: Verdict) -> str:
    return verdict.final_status if verdict.passed else "unknown"


def _text(claim: ClaimInput, verdict: Verdict) -> str:
    if any(r.check_id == "V-9" for r in verdict.failures):
        return WITHHELD_TEXT
    return claim.text


async def _existing(session: AsyncSession, run_id: uuid.UUID, key: str) -> StoredClaim | None:
    row = (
        await session.execute(
            select(Claim.id, ClaimVersion.id, ClaimVersion.status)
            .join(ClaimVersion, ClaimVersion.claim_id == Claim.id)
            .where(Claim.run_id == run_id, Claim.key == key, ClaimVersion.version == FIRST_VERSION)
        )
    ).one_or_none()
    if row is None:
        return None
    queued = (
        await session.execute(
            select(ReviewItem.reason).where(ReviewItem.claim_version_id == row[1])
        )
    ).scalar_one_or_none()
    return StoredClaim(row[0], row[1], False, row[2], queued)


async def store_claim(
    session: AsyncSession,
    *,
    snapshot_id: uuid.UUID,
    run_id: uuid.UUID,
    kind: str,
    claim: ClaimInput,
    verdict: Verdict,
    producer: str,
    reader: SnapshotReader,
) -> StoredClaim:
    """Store one claim and its verdict. `claim.claim_id` is the key and must be stable."""
    if claim.status not in STATUSES or claim.producer_kind not in PRODUCER_KINDS:
        raise ClaimRejected(f"{claim.claim_id!r}: unknown status or producer kind (V-5)")
    inserted = (
        await session.execute(
            insert(Claim)
            .values(snapshot_id=snapshot_id, run_id=run_id, key=claim.claim_id, kind=kind)
            .on_conflict_do_nothing(constraint="uq_claim_run_key")
            .returning(Claim.id)
        )
    ).scalar_one_or_none()
    if inserted is None:  # the key exists: another attempt or another worker wrote it
        found = await _existing(session, run_id, claim.claim_id)
        if found is None:  # pragma: no cover - a claim row without version means a half write
            raise RuntimeError(f"claim {claim.claim_id!r} exists in run {run_id} without a version")
        return found

    return await _write_version(
        session,
        claim_row_id=inserted,
        number=FIRST_VERSION,
        snapshot_id=snapshot_id,
        run_id=run_id,
        kind=kind,
        claim=claim,
        verdict=verdict,
        producer=producer,
        reader=reader,
        action="claim.written",
        extra={},
    )


async def _write_version(
    session: AsyncSession,
    *,
    claim_row_id: uuid.UUID,
    number: int,
    snapshot_id: uuid.UUID,
    run_id: uuid.UUID,
    kind: str,
    claim: ClaimInput,
    verdict: Verdict,
    producer: str,
    reader: SnapshotReader,
    action: str,
    extra: dict[str, Any],
) -> StoredClaim:
    status = _stored_status(verdict)
    version = ClaimVersion(
        claim_id=claim_row_id,
        version=number,
        text=_text(claim, verdict),
        status=status,
        producer=producer,
        producer_kind=claim.producer_kind,
    )
    session.add(version)
    await session.flush()

    evidence_rows: list[dict[str, Any]] = []
    for entry in claim.evidence:
        try:
            ref = parse_ref(dict(entry.ref)) if isinstance(entry.ref, Mapping) else entry.ref
            found_ref = resolve(ref, reader)
        except Exception:  # an unparseable or unresolvable reference is simply not stored
            continue
        if found_ref.status == "resolved":
            evidence_rows.append(evidence_row_fields(ref, found_ref, version.id, snapshot_id))
    session.add_all(Evidence(**fields) for fields in evidence_rows)
    session.add_all(VerificationResult(**row) for row in result_rows(verdict, version.id))

    queued = verdict.queue_reason  # failure, stale, inferred or unknown; None only if it may stand
    if queued is not None:
        session.add(ReviewItem(claim_version_id=version.id, reason=queued))
    session.add(
        AuditLog(
            actor=producer,
            action=action,
            subject_type="claim_version",
            subject_id=str(version.id),
            detail={
                **extra,
                "key": claim.claim_id,
                "kind": kind,
                "run_id": str(run_id),
                "requested_status": claim.status,
                "stored_status": status,
                "failed_checks": [r.check_id for r in verdict.failures],
                "stale": verdict.stale,
                "queued": queued,
                "evidence_rows": len(evidence_rows),
            },
        )
    )
    await session.flush()
    return StoredClaim(claim_row_id, version.id, True, status, queued)


async def add_version(
    session: AsyncSession,
    *,
    based_on: uuid.UUID,
    claim: ClaimInput,
    producer: str,
    reader: SnapshotReader,
) -> StoredClaim:
    """Store a new version of an existing claim (a reviewer's edit), verified like any other.
    `based_on` is the version being replaced and must be the claim's latest. Versions are never
    updated in place (CLM-1.5). A failed check stores the version Unknown and queued."""
    if claim.status not in STATUSES or claim.producer_kind not in PRODUCER_KINDS:
        raise ClaimRejected(f"{claim.claim_id!r}: unknown status or producer kind (V-5)")
    row = (
        await session.execute(
            select(Claim, ClaimVersion.version)
            .join(ClaimVersion, ClaimVersion.claim_id == Claim.id)
            .where(ClaimVersion.id == based_on)
        )
    ).one_or_none()
    if row is None:
        raise LookupError(f"claim version {based_on} does not exist")
    parent, number = row
    latest = (
        await session.execute(
            select(func.max(ClaimVersion.version)).where(ClaimVersion.claim_id == parent.id)
        )
    ).scalar_one()
    if latest != number:
        raise ValueError(f"version {number} is not the latest ({latest}); edit the latest")
    return await _write_version(
        session,
        claim_row_id=parent.id,
        number=number + 1,
        snapshot_id=parent.snapshot_id,
        run_id=parent.run_id,
        kind=parent.kind,
        claim=claim,
        verdict=verify_claim(claim, reader),
        producer=producer,
        reader=reader,
        action="claim.version_added",
        extra={"based_on": str(based_on), "version": number + 1},
    )


async def verify_and_store(
    session: AsyncSession,
    *,
    snapshot_id: uuid.UUID,
    run_id: uuid.UUID,
    kind: str,
    claim: ClaimInput,
    producer: str,
    reader: SnapshotReader,
) -> StoredClaim:
    """Run V-1 to V-10 on the claim, then store it. Nothing reaches the store unverified."""
    return await store_claim(
        session,
        snapshot_id=snapshot_id,
        run_id=run_id,
        kind=kind,
        claim=claim,
        verdict=verify_claim(claim, reader),
        producer=producer,
        reader=reader,
    )
