"""Data agent findings go through the claim writer: idempotent, fail-closed. Needs Postgres."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from services.data import analyze
from services.data.store import PRODUCER, store_data
from services.db.models import AuditLog, Claim, ClaimVersion
from services.evals.corpus import APP
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot

pytestmark = pytest.mark.requires_db


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(connection, join_transaction_mode="create_savepoint") as session:
        yield session


async def test_findings_are_stored_by_status_and_idempotent(
    session: AsyncSession, tmp_path: Path
) -> None:
    pinned = pin_local(
        APP, tmp_path / "store", Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    )
    snapshot, _ = await store_snapshot(session, pinned)
    reader = SnapshotReader.from_pinned(pinned)
    run = uuid.uuid4()
    found = analyze(reader, reader.paths())

    first = await store_data(session, snapshot.id, run, found, reader)
    assert len(first) == len(found.findings) and all(r.created for r in first)
    stored = {r.status for r in first}
    assert stored == {"confirmed", "inferred"}
    count = (
        await session.execute(select(func.count()).select_from(Claim).where(Claim.run_id == run))
    ).scalar_one()
    assert count == len(found.findings)
    audit = (
        await session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.actor == PRODUCER)
        )
    ).scalar_one()
    assert audit == len(found.findings)

    again = await store_data(session, snapshot.id, run, found, reader)
    assert not any(r.created for r in again)
    assert [r.version_id for r in again] == [r.version_id for r in first]
    versions = (await session.execute(select(func.count()).select_from(ClaimVersion))).scalar_one()
    assert versions == len(found.findings)


async def test_an_unresolved_statement_is_stored_unknown_and_queued(
    session: AsyncSession, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    (source / "lib").mkdir(parents=True)
    (source / "lib/db.js").write_text(
        "function query(sql, p, cb) {}\nmodule.exports = { query };\n"
    )
    (source / "app.js").write_text("const db = require('./lib/db');\ndb.query(build(), [], cb);\n")
    pinned = pin_local(
        source, tmp_path / "store", Limits(max_bytes=MIB, max_files=100, max_depth=10)
    )
    snapshot, _ = await store_snapshot(session, pinned)
    reader = SnapshotReader.from_pinned(pinned)
    found = analyze(reader, reader.paths())
    (stored,) = await store_data(session, snapshot.id, uuid.uuid4(), found, reader)
    assert stored.status == "unknown" and stored.queued_reason is not None
