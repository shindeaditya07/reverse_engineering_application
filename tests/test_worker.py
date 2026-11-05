"""The worker: Discovery as a job, kill and resume, a changed snapshot. Needs Postgres.

The queue rows and the snapshot are committed (they can be deleted afterwards); claims are
written through the rolled-back test connection, because committed claim versions can never be
deleted (CLM-1.5). The snapshot's ingest audit rows stay behind, which is harmless: audit_log is
append-only by design.
"""

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

import services.worker.__main__ as cli
from services.db.models import Claim, ClaimVersion, Job, ReviewItem, Snapshot
from services.db.session import session_scope
from services.discovery import discover
from services.discovery.store import store_discovery
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot
from services.jobs import (
    Claimed,
    claim_next,
    lease_seconds,
    max_retries,
    run_until_idle,
    sweep,
)
from services.worker import (
    DISCOVERY,
    JobInputMissing,
    discovery_handler,
    enqueue_discovery,
    load_reader,
)

pytestmark = pytest.mark.requires_db

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
APP_FILES = {
    "package.json": b'{\n  "main": "a.js",\n  "dependencies": {\n    "express": "^4"\n  }\n}\n',
    "a.js": b"const _ = require('lodash');\nsetInterval(tick, 1000);\n",
    "b.js": b"https.request(options, done);\n",
}


class World:
    def __init__(self, snapshot_id: uuid.UUID, revision: str, store: Path) -> None:
        self.snapshot_id, self.revision, self.store = snapshot_id, revision, store

    @property
    def copy(self) -> Path:
        return self.store / self.revision


@pytest_asyncio.fixture
async def world(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[World]:
    """A small app, pinned and stored for real. Its content is unique per run so the snapshot
    is always new, and it is deleted afterwards along with any job that named it."""
    source = tmp_path / "source"
    for rel, data in {**APP_FILES, "unique.txt": uuid.uuid4().hex.encode()}.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data)
    store = tmp_path / "store"
    pinned = pin_local(source, store, LIMITS)
    async with session_scope(engine) as session:
        snapshot, created = await store_snapshot(session, pinned)
    assert created
    yield World(snapshot.id, snapshot.revision, store)
    async with session_scope(engine) as session:
        for table in ("jobs", "snapshot_files"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE snapshot_id = :s"),  # noqa: S608
                {"s": snapshot.id},
            )
        await session.execute(text("DELETE FROM snapshots WHERE id = :s"), {"s": snapshot.id})


@pytest_asyncio.fixture
async def session(connection: AsyncConnection, world: World) -> AsyncIterator[AsyncSession]:
    """Depends on `world` so the test connection rolls back, and releases its locks on the
    snapshot, before the snapshot is deleted: fixtures tear down in reverse order."""
    async with AsyncSession(connection, join_transaction_mode="create_savepoint") as session:
        yield session


def sessions_in(session: AsyncSession) -> Any:
    """A session factory over the rolled-back test session. Like session_scope it is one
    transaction: an error inside rolls back everything the handler wrote (a savepoint here)."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with session.begin_nested():
            yield session

    return factory


async def n(session: AsyncSession, model: type, *where: Any) -> int:
    query = select(func.count()).select_from(model).where(*where)
    return (await session.execute(query)).scalar_one()


async def queue(engine: AsyncEngine, world: World) -> tuple[uuid.UUID, uuid.UUID]:
    run = uuid.uuid4()
    async with session_scope(engine) as s:
        snapshot = (
            await s.execute(select(Snapshot).where(Snapshot.id == world.snapshot_id))
        ).scalar_one()
        job_id, _ = await enqueue_discovery(s, snapshot, run)
    return run, job_id


async def job_row(engine: AsyncEngine, job_id: uuid.UUID) -> dict[str, Any]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT status, attempts, last_error FROM jobs WHERE id = :i"), {"i": job_id}
        )
        return dict(result.one()._mapping)


# ---- loading the job's input -------------------------------------------------------------------


async def test_a_job_without_a_snapshot_cannot_load_a_reader(
    session: AsyncSession, tmp_path: Path
) -> None:
    with pytest.raises(JobInputMissing, match="no snapshot"):
        await load_reader(session, None, tmp_path)


async def test_a_job_naming_an_unknown_snapshot_cannot_load_a_reader(
    session: AsyncSession, tmp_path: Path
) -> None:
    with pytest.raises(JobInputMissing, match="not in the store"):
        await load_reader(session, uuid.uuid4(), tmp_path)


async def test_the_reader_serves_the_pinned_files(session: AsyncSession, world: World) -> None:
    snapshot, reader = await load_reader(session, world.snapshot_id, world.store)
    assert snapshot.revision == world.revision
    assert set(reader.paths()) == {*APP_FILES, "unique.txt"}
    assert reader.lines("b.js") == ["https.request(options, done);"]


# ---- the handler -------------------------------------------------------------------------------


async def test_the_handler_stores_what_discovery_finds(session: AsyncSession, world: World) -> None:
    job = Claimed(uuid.uuid4(), uuid.uuid4(), DISCOVERY, world.revision, 1, "w", world.snapshot_id)
    await discovery_handler(sessions_in(session), world.store)(job)
    stored = await n(session, Claim, Claim.run_id == job.run_id)
    _, reader = await load_reader(session, world.snapshot_id, world.store)
    assert stored == len(discover(reader, reader.paths()).findings) == 3  # lodash, timer, call
    assert await n(session, ReviewItem) >= 3
    await discovery_handler(sessions_in(session), world.store)(job)  # a repeat adds nothing
    assert await n(session, Claim, Claim.run_id == job.run_id) == stored


async def test_the_handler_fails_when_the_pinned_copy_changed(
    session: AsyncSession, world: World
) -> None:
    (world.copy / "a.js").parent.chmod(0o755)
    (world.copy / "a.js").chmod(0o644)
    (world.copy / "a.js").write_bytes(b"changed();\n")
    job = Claimed(uuid.uuid4(), uuid.uuid4(), DISCOVERY, world.revision, 1, "w", world.snapshot_id)
    with pytest.raises(Exception, match="differs from its pinned hash"):
        await discovery_handler(sessions_in(session), world.store)(job)
    assert await n(session, Claim, Claim.run_id == job.run_id) == 0


# ---- through the queue -------------------------------------------------------------------------


async def test_a_queued_discovery_job_runs_to_success(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    run, job_id = await queue(engine, world)
    handler = {DISCOVERY: discovery_handler(sessions_in(session), world.store)}
    assert await run_until_idle(engine, handler, lease_seconds()) == 1
    assert (await job_row(engine, job_id))["status"] == "succeeded"
    assert await n(session, Claim, Claim.run_id == run) == 3


async def test_a_crash_after_writing_stores_nothing_and_the_retry_stores_everything(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    run, job_id = await queue(engine, world)
    real = discovery_handler(sessions_in(session), world.store)
    crashes = [True]

    async def crash_once(job: Claimed) -> None:
        await real(job)
        if crashes:
            crashes.pop()
            raise RuntimeError("killed after writing")

    # The crash happens inside the handler's transaction in production, so the savepoint stands
    # in for it: wrap the real handler's writes and the crash in one transaction.
    async def one_transaction(job: Claimed) -> None:
        async with session.begin_nested():
            await crash_once(job)

    await run_until_idle(engine, {DISCOVERY: one_transaction}, lease_seconds())
    final = await job_row(engine, job_id)
    assert (final["status"], final["attempts"], final["last_error"]) == ("succeeded", 2, None)
    assert await n(session, Claim, Claim.run_id == run) == 3  # once, not twice


async def test_a_killed_worker_is_swept_and_the_job_finishes_without_duplicates(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    """The kill and resume test (build plan, job runner): a worker claims the job and dies."""
    run, job_id = await queue(engine, world)
    async with session_scope(engine) as s:
        assert await claim_next(s, "killed-halfway", [DISCOVERY]) is not None
    handler = {DISCOVERY: discovery_handler(sessions_in(session), world.store)}
    assert await run_until_idle(engine, handler, lease_seconds()) == 0  # still leased

    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=lease_seconds() + 30)
    async with session_scope(engine) as s:
        assert (await sweep(s, lease_seconds(), later))["requeued"] >= 1
    assert await run_until_idle(engine, handler, lease_seconds()) == 1
    assert await n(session, Claim, Claim.run_id == run) == 3

    async with session_scope(engine) as s:
        snapshot = (
            await s.execute(select(Snapshot).where(Snapshot.id == world.snapshot_id))
        ).scalar_one()
        again, created = await enqueue_discovery(s, snapshot, run)
    assert (again, created) == (job_id, False)
    assert await run_until_idle(engine, handler, lease_seconds()) == 0
    assert await n(session, Claim, Claim.run_id == run) == 3
    assert (
        await n(
            session,
            ClaimVersion,
            ClaimVersion.claim_id.in_(select(Claim.id).where(Claim.run_id == run)),
        )
        == 3
    )


async def test_a_changed_snapshot_fails_the_job_visibly_after_the_retries(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    (world.copy / "a.js").parent.chmod(0o755)
    (world.copy / "a.js").chmod(0o644)
    (world.copy / "a.js").write_bytes(b"changed();\n")
    run, job_id = await queue(engine, world)
    handler = {DISCOVERY: discovery_handler(sessions_in(session), world.store)}
    assert await run_until_idle(engine, handler, lease_seconds()) == 1 + max_retries()
    final = await job_row(engine, job_id)
    assert (final["status"], final["last_error"]) == ("failed", "Unresolved")
    assert await n(session, Claim, Claim.run_id == run) == 0


# ---- the command line --------------------------------------------------------------------------


async def test_work_sweeps_a_stale_job_then_runs_it(
    engine: AsyncEngine, session: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, job_id = await queue(engine, world)
    async with session_scope(engine) as s:
        await claim_next(s, "gone", [DISCOVERY])
        await s.execute(
            text("UPDATE jobs SET locked_at = now() - make_interval(secs => :t) WHERE id = :i"),
            {"t": lease_seconds() + 30, "i": job_id},
        )
    monkeypatch.setattr(
        cli,
        "handlers",
        lambda e, store: {DISCOVERY: discovery_handler(sessions_in(session), store)},
    )
    result = await cli.work(engine, world.store)
    assert result["swept_requeued"] >= 1 and result["ran"] >= 1
    assert (await job_row(engine, job_id))["status"] == "succeeded"


async def test_the_summary_counts_by_status_and_review_reason(
    session: AsyncSession, world: World
) -> None:
    run = uuid.uuid4()
    snapshot, reader = await load_reader(session, world.snapshot_id, world.store)
    await store_discovery(session, snapshot.id, run, discover(reader, reader.paths()), reader)
    result = await cli.summary(session, run)
    assert result["jobs"] == {} and result["run_id"] == str(run)
    assert result["claims_by_status"] == {"inferred": 3}
    assert result["review_queue_by_reason"] == {"inferred": 3}


def test_analyze_rejects_a_ref_on_a_local_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["analyze", os.getcwd(), "--ref", "main"]) == 1
    assert "--ref only applies to GitHub URLs" in capsys.readouterr().err


def test_a_job_row_knows_its_snapshot() -> None:
    assert Job.snapshot_id.property.columns[0].nullable is True
