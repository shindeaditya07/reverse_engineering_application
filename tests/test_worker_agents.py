"""Code Analysis and the Data agent as worker jobs: one job per agent, each stores what its agent
finds, a crash stores nothing and the retry stores once, one agent failing leaves the others.
Needs Postgres. Same rules as test_worker.py: claims go through the rolled-back test connection."""

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

import services.worker.__main__ as cli
from services.codeanalysis import analyze as analyze_code
from services.data import analyze as analyze_data
from services.db.models import Claim, Snapshot
from services.db.session import session_scope
from services.discovery import discover
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot
from services.jobs import Claimed, lease_seconds, max_retries, run_until_idle
from services.worker import (
    AGENT_JOBS,
    CODE_ANALYSIS,
    DATA,
    DISCOVERY,
    code_analysis_handler,
    data_handler,
    discovery_handler,
    enqueue_agents,
    load_reader,
)
from tests.test_worker import World, job_row, n, sessions_in

pytestmark = pytest.mark.requires_db

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
APP_FILES = {
    "package.json": b'{\n  "main": "app.js",\n  "dependencies": {\n    "express": "^4"\n  }\n}\n',
    "app.js": (
        b"const express = require('express');\nconst _ = require('lodash');\n"
        b"const db = require('./lib/db');\nconst app = express();\n"
        b"app.get('/things', (req, res) => db.query('SELECT id FROM things', [], cb));\n"
    ),
    "lib/db.js": b"function query(sql, p, cb) {}\nmodule.exports = { query };\n",
    "db/schema.sql": b"CREATE TABLE things (\n  id INT PRIMARY KEY,\n  spare INT\n);\n",
}
HANDLERS = {
    DISCOVERY: discovery_handler,
    CODE_ANALYSIS: code_analysis_handler,
    DATA: data_handler,
}
ANALYZERS: dict[str, Callable[[SnapshotReader, list[str]], Any]] = {
    DISCOVERY: discover,
    CODE_ANALYSIS: analyze_code,
    DATA: analyze_data,
}
PREFIX = {DISCOVERY: "disc:", CODE_ANALYSIS: "ca:", DATA: "data:"}


@pytest_asyncio.fixture
async def world(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[World]:
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
    async with AsyncSession(connection, join_transaction_mode="create_savepoint") as session:
        yield session


def handlers_over(session: AsyncSession, world: World) -> dict[str, Any]:
    return {t: make(sessions_in(session), world.store) for t, make in HANDLERS.items()}


async def queue_all(engine: AsyncEngine, world: World) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    run = uuid.uuid4()
    async with session_scope(engine) as s:
        snapshot = (
            await s.execute(select(Snapshot).where(Snapshot.id == world.snapshot_id))
        ).scalar_one()
        queued = await enqueue_agents(s, snapshot, run)
    return run, {t: job_id for t, (job_id, _) in queued.items()}


async def keys(session: AsyncSession, run: uuid.UUID, prefix: str) -> list[str]:
    rows = (await session.execute(select(Claim.key).where(Claim.run_id == run))).scalars()
    return sorted(k for k in rows if k.startswith(prefix))


async def expected(session: AsyncSession, world: World, job_type: str) -> int:
    _, reader = await load_reader(session, world.snapshot_id, world.store)
    return len(ANALYZERS[job_type](reader, reader.paths()).findings)


def test_the_agent_jobs_are_the_three_agents_in_pipeline_order() -> None:
    assert AGENT_JOBS == (DISCOVERY, CODE_ANALYSIS, DATA)


def test_the_cli_runs_a_handler_for_every_agent(engine: AsyncEngine, tmp_path: Path) -> None:
    assert set(cli.handlers(engine, tmp_path)) == set(AGENT_JOBS)


async def test_queueing_a_run_makes_one_job_per_agent_and_a_repeat_adds_none(
    engine: AsyncEngine, world: World
) -> None:
    run, ids = await queue_all(engine, world)
    assert set(ids) == set(AGENT_JOBS) and len(set(ids.values())) == 3
    async with session_scope(engine) as s:
        snapshot = (
            await s.execute(select(Snapshot).where(Snapshot.id == world.snapshot_id))
        ).scalar_one()
        again = await enqueue_agents(s, snapshot, run)
    assert {t: v for t, v in again.items()} == {t: (ids[t], False) for t in AGENT_JOBS}


@pytest.mark.parametrize("job_type", [CODE_ANALYSIS, DATA])
async def test_each_new_handler_stores_what_its_agent_finds(
    session: AsyncSession, world: World, job_type: str
) -> None:
    job = Claimed(uuid.uuid4(), uuid.uuid4(), job_type, world.revision, 1, "w", world.snapshot_id)
    handler = HANDLERS[job_type](sessions_in(session), world.store)
    await handler(job)
    stored = await keys(session, job.run_id, PREFIX[job_type])
    assert len(stored) == await expected(session, world, job_type) > 0
    assert await keys(session, job.run_id, "") == stored  # nothing from another agent
    await handler(job)  # a repeat adds nothing
    assert await keys(session, job.run_id, PREFIX[job_type]) == stored


async def test_a_queued_run_stores_every_agents_claims_under_its_own_keys(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    run, ids = await queue_all(engine, world)
    assert await run_until_idle(engine, handlers_over(session, world), lease_seconds()) == 3
    for job_type in AGENT_JOBS:
        assert (await job_row(engine, ids[job_type]))["status"] == "succeeded"
        found = await keys(session, run, PREFIX[job_type])
        assert len(found) == await expected(session, world, job_type) > 0
    total = await n(session, Claim, Claim.run_id == run)
    assert total == sum([await expected(session, world, t) for t in AGENT_JOBS])


@pytest.mark.parametrize("job_type", [CODE_ANALYSIS, DATA])
async def test_a_crash_after_writing_stores_nothing_and_the_retry_stores_once(
    engine: AsyncEngine, session: AsyncSession, world: World, job_type: str
) -> None:
    run, ids = await queue_all(engine, world)
    real = HANDLERS[job_type](sessions_in(session), world.store)
    crashes = [True]

    async def crash_once(job: Claimed) -> None:
        async with session.begin_nested():  # stands in for the handler's own transaction
            await real(job)
            if crashes:
                crashes.pop()
                raise RuntimeError("killed after writing")

    await run_until_idle(engine, {job_type: crash_once}, lease_seconds())
    final = await job_row(engine, ids[job_type])
    assert (final["status"], final["attempts"], final["last_error"]) == ("succeeded", 2, None)
    assert len(await keys(session, run, PREFIX[job_type])) == await expected(
        session, world, job_type
    )


async def test_one_agent_failing_leaves_the_others_stored_and_is_named_in_the_summary(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    run, ids = await queue_all(engine, world)
    handlers = handlers_over(session, world)

    async def broken(job: Claimed) -> None:
        raise RuntimeError("the data agent crashed")

    handlers[DATA] = broken
    ran = await run_until_idle(engine, handlers, lease_seconds())
    assert ran == 1 + 1 + (1 + max_retries())
    assert (await job_row(engine, ids[DATA]))["last_error"] == "RuntimeError"
    assert (await job_row(engine, ids[DISCOVERY]))["status"] == "succeeded"
    assert (await job_row(engine, ids[CODE_ANALYSIS]))["status"] == "succeeded"
    assert await keys(session, run, PREFIX[DATA]) == []
    async with session_scope(engine) as s:
        result = await cli.summary(s, run)
    assert result["jobs"] == {"succeeded": 2, "failed": 1}
    assert result["failed_job_types"] == [DATA]


async def test_the_summary_of_a_run_with_no_failures_names_none(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    run, _ = await queue_all(engine, world)
    await run_until_idle(engine, handlers_over(session, world), lease_seconds())
    async with session_scope(engine) as s:
        assert (await cli.summary(s, run))["failed_job_types"] == []
