"""Evidence rows in Postgres: a stored reference rebuilds to the same reference and bytes."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from services.db.models import Claim, ClaimVersion, Evidence
from services.evidence import (
    BuildStep,
    ConfigKey,
    EvidenceRef,
    FileRange,
    LogLine,
    SchemaObject,
    SnapshotReader,
    Ticket,
    check_hash,
    evidence_row_fields,
    ref_from_row,
    resolve,
)
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot

pytestmark = pytest.mark.requires_db
ROOT = Path(__file__).resolve().parent.parent
LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)

REFS: list[EvidenceRef] = [
    FileRange(path="lib/totals.js", start_line=3, end_line=5),
    FileRange(path="lib/legacy_labels.js", start_byte=73, end_byte=74),
    LogLine(path="app.js", line=1),
    SchemaObject(path="db/schema.sql", object_name="column:orders.status"),
    ConfigKey(path="config.js", object_name="taxRate"),
    BuildStep(path="package.json", object_name="npm:start"),
    Ticket(path="package.json", object_name="corner-shop-orders", line=2),
]


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as s:
        yield s


@pytest.mark.parametrize("ref", REFS, ids=lambda r: r.kind)
async def test_round_trip(session: AsyncSession, tmp_path: Path, ref: EvidenceRef) -> None:
    pinned = pin_local(ROOT / "fixtures/legacy-app", tmp_path / "store", LIMITS)
    reader = SnapshotReader.from_pinned(pinned)
    snapshot, _ = await store_snapshot(session, pinned)
    claim = Claim(snapshot_id=snapshot.id, run_id=uuid.uuid4(), kind="behavior")
    session.add(claim)
    await session.flush()
    version = ClaimVersion(
        claim_id=claim.id,
        version=1,
        text="t",
        status="unknown",
        producer="t",
        producer_kind="model",
    )
    session.add(version)
    await session.flush()

    found = resolve(ref, reader)
    row = Evidence(**evidence_row_fields(ref, found, version.id, snapshot.id))
    session.add(row)
    await session.flush()

    stored = (await session.execute(select(Evidence).where(Evidence.id == row.id))).scalar_one()
    rebuilt = ref_from_row(stored)
    assert rebuilt == ref
    again = check_hash(rebuilt, stored.content_hash, reader)
    assert again.status == "resolved"
    assert again.content_hash == found.content_hash


async def test_verifier_result_rows_fit_the_table(session: AsyncSession, tmp_path: Path) -> None:
    from services.db.models import VerificationResult
    from services.verifier import ClaimInput, result_rows, verify_claim
    from tests.verifier_corpus import lines, stored

    pinned = pin_local(ROOT / "fixtures/legacy-app", tmp_path / "store", LIMITS)
    reader = SnapshotReader.from_pinned(pinned)
    snapshot, _ = await store_snapshot(session, pinned)
    claim = Claim(snapshot_id=snapshot.id, run_id=uuid.uuid4(), kind="behavior")
    session.add(claim)
    await session.flush()
    version = ClaimVersion(
        claim_id=claim.id,
        version=1,
        text="t",
        status="unknown",
        producer="t",
        producer_kind="model",
    )
    session.add(version)
    await session.flush()

    verdict = verify_claim(
        ClaimInput("C", "t", "maybe", "model", (stored(reader, lines("app.js", 1, 1)),)), reader
    )
    session.add_all(VerificationResult(**row) for row in result_rows(verdict, version.id))
    await session.flush()
    stored_rows = (await session.execute(select(VerificationResult))).scalars().all()
    assert {r.check_id for r in stored_rows if not r.passed} == {"V-5"}
    assert len(stored_rows) == 9
