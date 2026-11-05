"""OPS-1.1 and AGENTS.md section 4: SKIP LOCKED claim, sweeper, bounded retries, resume."""

import asyncio
import datetime as dt
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from services.db.session import session_scope
from services.jobs import (
    Claimed,
    claim_next,
    complete,
    enqueue,
    fail,
    max_retries,
    run_one,
    run_until_idle,
    sweep,
    sweep_on_startup,
)
from services.rules_constants import rule_constants
from tests.test_db_schema import expect_error

pytestmark = pytest.mark.requires_db

RUN = uuid.UUID("11111111-1111-1111-1111-111111111111")
LEASE = 600  # a test value: the real lease is not fixed by any rule yet


@pytest_asyncio.fixture
async def jtype(engine: AsyncEngine) -> AsyncIterator[str]:
    """A job type no other test uses, so committed rows here never leak into another test."""
    name = f"t{uuid.uuid4().hex[:12]}"
    yield name
    async with session_scope(engine) as session:
        await session.execute(text("DELETE FROM jobs WHERE job_type = :t"), {"t": name})


async def put(engine: AsyncEngine, jtype: str, key: str = "a") -> uuid.UUID:
    async with session_scope(engine) as session:
        return (await enqueue(session, RUN, jtype, key))[0]


async def row(engine: AsyncEngine, job_id: uuid.UUID) -> dict[str, object]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT status, attempts, last_error, locked_by, locked_at FROM jobs WHERE id=:i"),
            {"i": job_id},
        )
        return dict(result.one()._mapping)


async def always_ok(job: Claimed) -> None:
    return None


def test_the_retry_limit_comes_from_the_constants_file() -> None:
    assert max_retries() == rule_constants("OPS-1.1")["max_job_retries"]


async def test_enqueue_is_idempotent_per_run_type_and_input(
    engine: AsyncEngine, jtype: str
) -> None:
    async with session_scope(engine) as session:
        first, created = await enqueue(session, RUN, jtype, "a")
        again, created_again = await enqueue(session, RUN, jtype, "a")
        other, created_other = await enqueue(session, RUN, jtype, "b")
    assert (created, created_again, created_other) == (True, False, True)
    assert first == again != other


async def test_a_succeeded_job_is_not_run_again(engine: AsyncEngine, jtype: str) -> None:
    job_id = await put(engine, jtype)
    assert await run_until_idle(engine, {jtype: always_ok}, LEASE) == 1
    async with session_scope(engine) as session:
        same, created = await enqueue(session, RUN, jtype, "a")
    assert (same, created) == (job_id, False)
    assert await run_until_idle(engine, {jtype: always_ok}, LEASE) == 0
    assert (await row(engine, job_id))["status"] == "succeeded"


async def test_skip_locked_never_hands_one_job_to_two_workers(
    engine: AsyncEngine, jtype: str
) -> None:
    await put(engine, jtype, "a")
    await put(engine, jtype, "b")
    async with session_scope(engine) as one, session_scope(engine) as two:
        first = await claim_next(one, "w1", [jtype])  # row lock held: not committed yet
        second = await claim_next(two, "w2", [jtype])
        third = await claim_next(two, "w2", [jtype])
    assert first is not None and second is not None
    assert first.id != second.id
    assert third is None  # both rows are taken: SKIP LOCKED returns nothing instead of waiting


async def test_concurrent_workers_run_each_job_exactly_once(
    engine: AsyncEngine, jtype: str
) -> None:
    for n in range(12):
        await put(engine, jtype, f"k{n}")
    seen: list[uuid.UUID] = []

    async def handler(job: Claimed) -> None:
        await asyncio.sleep(0.01)
        seen.append(job.id)

    counts = await asyncio.gather(
        *(run_until_idle(engine, {jtype: handler}, LEASE, f"w{n}") for n in range(4))
    )
    assert sum(counts) == 12
    assert len(seen) == len(set(seen)) == 12


async def test_only_types_the_worker_handles_are_claimed(engine: AsyncEngine, jtype: str) -> None:
    job_id = await put(engine, jtype)
    assert await run_one(engine, {f"{jtype}x": always_ok}, LEASE) is False
    assert (await row(engine, job_id))["status"] == "queued"


async def test_a_failing_job_retries_then_enters_the_visible_failed_state(
    engine: AsyncEngine, jtype: str
) -> None:
    job_id = await put(engine, jtype)

    async def boom(job: Claimed) -> None:
        raise ValueError("secret value that must not be stored")

    ran = await run_until_idle(engine, {jtype: boom}, LEASE)
    final = await row(engine, job_id)
    assert ran == 1 + max_retries()  # OPS-1.1: at most 3 retries after the first run
    assert final["status"] == "failed"
    assert final["attempts"] == 1 + max_retries()
    assert final["last_error"] == "ValueError"  # the class name, never the message
    assert await run_one(engine, {jtype: boom}, LEASE) is False  # failed jobs are not claimed again


async def test_a_job_that_succeeds_on_a_retry_clears_its_error(
    engine: AsyncEngine, jtype: str
) -> None:
    job_id = await put(engine, jtype)
    calls = 0

    async def flaky(job: Claimed) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError

    await run_until_idle(engine, {jtype: flaky}, LEASE)
    final = await row(engine, job_id)
    assert (final["status"], final["attempts"], final["last_error"]) == ("succeeded", 2, None)
    assert final["locked_by"] is None and final["locked_at"] is None


async def test_a_hung_handler_is_stopped_at_the_lease(engine: AsyncEngine, jtype: str) -> None:
    job_id = await put(engine, jtype)

    async def hang(job: Claimed) -> None:
        await asyncio.sleep(30)

    await run_one(engine, {jtype: hang}, 0.05)
    final = await row(engine, job_id)
    assert (final["status"], final["last_error"]) == ("queued", "TimeoutError")


async def test_the_sweeper_requeues_only_jobs_past_their_lease(
    engine: AsyncEngine, jtype: str
) -> None:
    stale = await put(engine, jtype, "stale")
    async with session_scope(engine) as session:
        claimed = await claim_next(session, "dead-worker", [jtype])
    assert claimed is not None and claimed.id == stale
    fresh = await put(engine, jtype, "fresh")
    async with session_scope(engine) as session:
        await claim_next(session, "live-worker", [jtype])
    assert (await row(engine, fresh))["status"] == "running"

    just_before = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=LEASE - 30)
    async with session_scope(engine) as session:
        assert await sweep(session, LEASE, just_before) == {"requeued": 0, "failed": 0}

    after = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=LEASE + 30)
    async with session_scope(engine) as session:
        swept = await sweep(session, LEASE, after)
    assert swept["requeued"] >= 2  # both leases are past by then
    state = await row(engine, stale)
    assert (state["status"], state["last_error"], state["locked_by"]) == (
        "queued",
        "LeaseExpired",
        None,
    )


async def test_a_job_that_keeps_dying_ends_failed_not_looping(
    engine: AsyncEngine, jtype: str
) -> None:
    job_id = await put(engine, jtype)
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=LEASE + 30)
    for _ in range(1 + max_retries()):
        async with session_scope(engine) as session:
            assert await claim_next(session, "doomed", [jtype]) is not None
        async with session_scope(engine) as session:
            await sweep(session, LEASE, later)
    final = await row(engine, job_id)
    assert (final["status"], final["last_error"]) == ("failed", "LeaseExpired")
    assert final["attempts"] == 1 + max_retries()


async def test_a_swept_worker_cannot_overwrite_the_new_holder(
    engine: AsyncEngine, jtype: str
) -> None:
    job_id = await put(engine, jtype)
    async with session_scope(engine) as session:
        old = await claim_next(session, "old", [jtype])
    assert old is not None
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=LEASE + 30)
    async with session_scope(engine) as session:
        await sweep(session, LEASE, later)
    async with session_scope(engine) as session:
        new = await claim_next(session, "new", [jtype])
    assert new is not None
    async with session_scope(engine) as session:
        assert await complete(session, job_id, "old") is False
        assert await fail(session, job_id, "old", "Late") is None
    state = await row(engine, job_id)
    assert (state["status"], state["locked_by"]) == ("running", "new")


async def test_resume_idempotent(engine: AsyncEngine, jtype: str) -> None:
    """A worker killed halfway: the sweeper requeues the job, a second worker finishes it, and
    the work lands once. Re-enqueueing the same input afterwards adds nothing."""
    job_id = await put(engine, jtype)
    produced: dict[str, int] = {}  # stands in for claims written by an idempotent upsert

    async def handler(job: Claimed) -> None:
        produced[f"claim:{job.input_hash}"] = job.attempts  # upsert: same key every time

    async with session_scope(engine) as session:
        killed = await claim_next(session, "killed-halfway", [jtype])  # never completes
    assert killed is not None
    assert await run_one(engine, {jtype: handler}, LEASE) is False  # still leased: nothing to take

    async with session_scope(engine) as session:
        await sweep(session, LEASE, dt.datetime.now(dt.UTC) + dt.timedelta(seconds=LEASE + 30))
    assert await run_until_idle(engine, {jtype: handler}, LEASE) == 1

    async with session_scope(engine) as session:
        again, created = await enqueue(session, RUN, jtype, "a")
    assert (again, created) == (job_id, False)
    assert await run_until_idle(engine, {jtype: handler}, LEASE) == 0
    assert produced == {"claim:a": 2}
    assert (await row(engine, job_id))["status"] == "succeeded"


async def test_sweep_on_startup_recovers_a_job_left_running(
    engine: AsyncEngine, jtype: str
) -> None:
    job_id = await put(engine, jtype)
    async with session_scope(engine) as session:
        await claim_next(session, "gone", [jtype])
        await session.execute(
            text("UPDATE jobs SET locked_at = now() - make_interval(secs => :s) WHERE id = :i"),
            {"s": LEASE + 30, "i": job_id},
        )
    await sweep_on_startup(engine, LEASE)
    assert (await row(engine, job_id))["status"] == "queued"


async def test_a_running_job_must_hold_a_lease(connection: AsyncConnection) -> None:
    """CHECK running_has_lease: every branch, because a NULL-valued CHECK passes."""
    run = uuid.uuid4()
    base = "INSERT INTO jobs (run_id, job_type, input_hash, status, locked_at, locked_by) "
    no_time = base + "VALUES (:r, 'c', 'h1', 'running', NULL, 'w')"
    no_owner = base + "VALUES (:r, 'c', 'h2', 'running', now(), NULL)"
    neither = base + "VALUES (:r, 'c', 'h3', 'running', NULL, NULL)"
    for sql in (no_time, no_owner, neither):
        assert "running_has_lease" in await expect_error(connection, sql, {"r": run})
    for status, locked in (("running", "now(), 'w'"), ("queued", "NULL, NULL")):
        await connection.execute(
            text(base + f"VALUES (:r, 'c', 'ok-{status}', '{status}', {locked})"), {"r": run}
        )
