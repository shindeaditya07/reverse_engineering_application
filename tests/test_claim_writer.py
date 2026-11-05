"""The claim writer: idempotent, fail-closed, no secrets stored. Needs Postgres."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from services.claims import WITHHELD_TEXT, ClaimRejected, verify_and_store
from services.db.models import (
    AuditLog,
    Claim,
    ClaimVersion,
    Evidence,
    ReviewItem,
    Snapshot,
    VerificationResult,
)
from services.discovery import discover
from services.discovery.store import PRODUCER, store_discovery
from services.evals.corpus import APP, bad_claims, good_claims, lines, stored
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot
from services.verifier import ClaimInput, EvidenceInput
from services.verifier.models import PRODUCER_KINDS, STATUSES
from tests.test_db_schema import expect_error

pytestmark = pytest.mark.requires_db

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
SECRET = "AKIA" + "IOSFODNN7EXAMPLE"


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(connection, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest_asyncio.fixture
async def world(
    session: AsyncSession, tmp_path: Path
) -> tuple[Snapshot, SnapshotReader, uuid.UUID]:
    pinned = pin_local(APP, tmp_path / "store", LIMITS)
    snapshot, _ = await store_snapshot(session, pinned)
    return snapshot, SnapshotReader.from_pinned(pinned), uuid.uuid4()


async def count(session: AsyncSession, model: type, *where: ColumnElement[bool]) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


def make(reader: SnapshotReader, key: str = "c1", **changes: Any) -> ClaimInput:
    base: dict[str, Any] = {
        "claim_id": key,
        "text": "The three report routes are registered in a loop.",
        "status": "confirmed",
        "producer_kind": "deterministic",
        "evidence": (stored(reader, lines("app.js", 24, 28)),),
    }
    return ClaimInput(**{**base, **changes})


async def put(session: AsyncSession, world: Any, claim: ClaimInput, kind: str = "route") -> Any:
    snapshot, reader, run = world
    return await verify_and_store(
        session,
        snapshot_id=snapshot.id,
        run_id=run,
        kind=kind,
        claim=claim,
        producer="test@1",
        reader=reader,
    )


async def test_a_passing_confirmed_claim_is_stored_whole(session: AsyncSession, world: Any) -> None:
    snapshot, reader, run = world
    result = await put(session, world, make(reader))
    assert result.created and result.status == "confirmed" and result.queued_reason is None
    version = (await session.execute(select(ClaimVersion))).scalars().one()
    assert (version.version, version.status, version.producer) == (1, "confirmed", "test@1")
    evidence = (await session.execute(select(Evidence))).scalars().one()
    assert (evidence.path, evidence.start_line, evidence.end_line) == ("app.js", 24, 28)
    assert evidence.snapshot_id == snapshot.id and len(evidence.content_hash) == 64
    assert await count(session, VerificationResult) == 9  # V-1 to V-7, V-9, V-10
    assert await count(session, ReviewItem) == 0
    claim = (await session.execute(select(Claim))).scalars().one()
    assert (claim.run_id, claim.key, claim.kind) == (run, "c1", "route")


async def test_an_inferred_claim_goes_to_the_review_queue(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    result = await put(
        session,
        world,
        make(
            reader,
            status="inferred",
            producer_kind="model",
            explanation="reports forEach over daily weekly monthly registers each route",
        ),
    )
    assert result.status == "inferred" and result.queued_reason == "inferred"
    item = (await session.execute(select(ReviewItem))).scalars().one()
    assert (item.reason, item.status) == ("inferred", "open")


async def test_an_unknown_claim_with_no_evidence_is_stored_and_queued(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    result = await put(session, world, make(reader, status="unknown", evidence=()))
    assert result.status == "unknown" and result.queued_reason == "unknown"
    assert await count(session, Evidence) == 0


async def test_writing_the_same_key_twice_in_a_run_adds_nothing(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    first = await put(session, world, make(reader))
    again = await put(session, world, make(reader))
    assert (first.created, again.created) == (True, False)
    assert (first.claim_id, first.version_id) == (again.claim_id, again.version_id)
    for model in (Claim, ClaimVersion, Evidence, VerificationResult):
        assert await count(session, model) == (9 if model is VerificationResult else 1), model
    assert await count(session, AuditLog, AuditLog.action == "claim.written") == 1


async def test_a_repeat_returns_the_stored_status_and_queue_reason(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    bad = make(reader, evidence=(EvidenceInput(lines("nope.js", 1, 2), "0" * 64),))
    first = await put(session, world, bad)
    again = await put(session, world, bad)
    assert (again.created, again.status, again.queued_reason) == (
        False,
        first.status,
        "verifier_failure",
    )


async def test_the_same_key_in_another_run_is_a_new_claim(
    session: AsyncSession, world: Any
) -> None:
    snapshot, reader, run = world
    await put(session, world, make(reader))
    other = await verify_and_store(
        session,
        snapshot_id=snapshot.id,
        run_id=uuid.uuid4(),
        kind="route",
        claim=make(reader),
        producer="test@1",
        reader=reader,
    )
    assert other.created and await count(session, Claim) == 2


async def test_the_database_refuses_a_duplicate_key_in_a_run(
    connection: AsyncConnection, session: AsyncSession, world: Any
) -> None:
    snapshot, reader, run = world
    await put(session, world, make(reader))
    await session.flush()
    message = await expect_error(
        connection,
        "INSERT INTO claims (snapshot_id, run_id, key, kind) VALUES (:s, :r, 'c1', 'route')",
        {"s": snapshot.id, "r": run},
    )
    assert "uq_claim_run_key" in message


async def test_a_claim_that_fails_a_check_is_stored_unknown_and_queued(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    good = stored(reader, lines("app.js", 24, 28))
    bad = make(reader, evidence=(good, EvidenceInput(lines("no/such.js", 1, 2), "0" * 64)))
    result = await put(session, world, bad)
    assert (result.status, result.queued_reason) == ("unknown", "verifier_failure")
    assert await count(session, Evidence) == 1  # only the reference that resolved
    audit = (
        await session.execute(select(AuditLog.detail).where(AuditLog.action == "claim.written"))
    ).scalar_one()
    assert audit["requested_status"] == "confirmed" and audit["stored_status"] == "unknown"
    assert "V-2" in audit["failed_checks"] and audit["evidence_rows"] == 1


async def test_a_claim_that_fails_without_being_demoted_still_cannot_stand(
    session: AsyncSession, world: Any
) -> None:
    """V-4 blocks without demoting. The writer stores it Unknown anyway: no evidence row can
    hold a 41-line range, and a claim that failed verification must not keep its status."""
    _, reader, _ = world
    over = make(reader, evidence=(EvidenceInput(lines("app.js", 1, 41), "0" * 64),))
    result = await put(session, world, over)
    assert (result.status, result.queued_reason) == ("unknown", "verifier_failure")
    assert await count(session, Evidence) == 0


async def test_a_claim_holding_a_secret_is_stored_without_its_text(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    claim = make(reader, text=f"The mailer signs requests with {SECRET}.")
    result = await put(session, world, claim)
    assert (result.status, result.queued_reason) == ("unknown", "verifier_failure")
    version = (await session.execute(select(ClaimVersion))).scalars().one()
    assert version.text == WITHHELD_TEXT
    everywhere = [
        str(r)
        for table in ("claim_versions", "verification_results", "audit_log", "claims", "evidence")
        for r in (await session.execute(text(f"SELECT * FROM {table}"))).all()  # noqa: S608
    ]
    assert SECRET not in json.dumps(everywhere)


async def test_a_claim_with_an_unknown_status_or_producer_is_rejected_unwritten(
    session: AsyncSession, world: Any
) -> None:
    _, reader, _ = world
    for changes in ({"status": "maybe"}, {"producer_kind": "oracle"}):
        with pytest.raises(ClaimRejected):
            await put(session, world, make(reader, **changes))
    assert await count(session, Claim) == 0
    assert await count(session, AuditLog, AuditLog.action == "claim.written") == 0


async def test_a_reference_object_is_accepted_as_well_as_a_mapping(
    session: AsyncSession, world: Any
) -> None:
    from services.evidence import parse_ref

    _, reader, _ = world
    ref = parse_ref(lines("app.js", 24, 28))
    entry = EvidenceInput(ref, stored(reader, lines("app.js", 24, 28)).content_hash)
    result = await put(session, world, make(reader, evidence=(entry,)))
    assert result.status == "confirmed" and await count(session, Evidence) == 1


async def test_no_claim_from_either_corpus_can_leave_a_confirmed_or_inferred_status_unbacked(
    connection: AsyncConnection, session: AsyncSession, world: Any
) -> None:
    """All 100 corpus claims through the writer, with the deferred evidence trigger run after each
    as COMMIT would: no claim keeps a status that needs evidence it does not have."""
    snapshot, reader, _ = world

    async def commit_point() -> None:
        """Run the deferred evidence trigger now, as COMMIT would, then defer it again."""
        await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    rejected = 0
    for claim, _check in bad_claims(reader):
        try:
            result = await verify_and_store(
                session,
                snapshot_id=snapshot.id,
                run_id=uuid.uuid4(),
                kind="x",
                claim=claim,
                producer="corpus@1",
                reader=reader,
            )
        except ClaimRejected:
            rejected += 1
            continue
        await commit_point()
        assert result.status == "unknown", claim.text
        assert result.queued_reason is not None
    malformed = [
        c
        for c, _ in bad_claims(reader)
        if c.status not in STATUSES or c.producer_kind not in PRODUCER_KINDS
    ]
    assert rejected == len(malformed) == 4  # the V-5 cases the schema has no value for
    for claim in good_claims(reader):
        await verify_and_store(
            session,
            snapshot_id=snapshot.id,
            run_id=uuid.uuid4(),
            kind="x",
            claim=claim,
            producer="corpus@1",
            reader=reader,
        )
        await commit_point()
    unbacked = await count(
        session,
        ClaimVersion,
        ClaimVersion.status.in_(["confirmed", "inferred"]),
        ~select(Evidence.id).where(Evidence.claim_version_id == ClaimVersion.id).exists(),
    )
    assert unbacked == 0


async def test_discovery_findings_are_stored_verified_and_idempotent(
    session: AsyncSession, world: Any
) -> None:
    snapshot, reader, run = world
    found = discover(reader, reader.paths())
    first = await store_discovery(session, snapshot.id, run, found, reader)
    assert len(first) == len(found.findings) and all(r.created for r in first)
    assert await count(session, Claim, Claim.run_id == run) == len(found.findings)
    confirmed = [r for r in first if r.status == "confirmed"]
    assert len(confirmed) == 2  # the two byte-level findings; every line pattern is Inferred
    assert await count(session, ReviewItem) == len(found.findings) - len(confirmed)
    audit = await count(session, AuditLog, AuditLog.actor == PRODUCER)
    assert audit == len(found.findings)

    again = await store_discovery(session, snapshot.id, run, found, reader)
    assert not any(r.created for r in again)
    assert [r.version_id for r in again] == [r.version_id for r in first]
    assert await count(session, Claim, Claim.run_id == run) == len(found.findings)
    assert await count(session, AuditLog, AuditLog.actor == PRODUCER) == audit
