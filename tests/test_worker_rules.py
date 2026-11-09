"""The Business Rule agent as worker jobs: one job per file, claims stored through the writer
(a claim the verifier blocks is stored Unknown and queued), every model call logged without text,
a repeat adds nothing, and without a client no model job runs. Needs Postgres."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

import services.worker.__main__ as cli
from services.db.models import Claim, ClaimVersion, ModelCall, ReviewItem, Snapshot
from services.db.session import session_scope
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot
from services.jobs import Claimed, lease_seconds, run_until_idle
from services.models import Completion, Request
from services.worker import (
    AGENT_JOBS,
    BUSINESS_RULE,
    business_rule_handler,
    enqueue_business_rule,
    load_reader,
    rule_job_hash,
)
from tests.test_worker import World, job_row, n, sessions_in

pytestmark = pytest.mark.requires_db

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
FILES = {
    "package.json": b'{\n  "main": "lib/price.js"\n}\n',
    "lib/price.js": (
        b"'use strict';\n\n"
        b"function discount(total) {\n"
        b"  if (total > 100) {\n"
        b"    return Math.floor(total * 0.9);\n"
        b"  }\n"
        b"  return total;\n"
        b"}\n\nmodule.exports = { discount };\n"
    ),
    "lib/limits.js": (
        b"'use strict';\n\n"
        b"function check(n) {\n"
        b"  if (n > 50) {\n"
        b"    throw new Error('too many');\n"
        b"  }\n"
        b"}\n\nmodule.exports = { check };\n"
    ),
    "lib/plain.js": b"'use strict';\n\nmodule.exports = { name: 'plain' };\n",
}
# Written with the code's own words on purpose: V-10 demotes a natural paraphrase such as
# "Orders over 100 get 10% off", which is the over-demotion the operator has not yet decided on.
GOOD_PRICE = json.dumps(
    {
        "rules": [
            {
                "text": "When total is over 100, discount returns floor of total times 0.9.",
                "line": 4,
            }
        ]
    }
)
# Shares no content word with the code it cites, so V-10 demotes it.
UNRELATED = json.dumps({"rules": [{"text": "Zebras migrate seasonally.", "line": 4}]})


class ByFile:
    """A stand-in model that answers by the file named in the prompt."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls = 0

    async def complete(self, request: Request) -> Completion:
        self.calls += 1
        code = request.untrusted["code"]
        for path, reply in self.answers.items():
            if f"file: {path}" in code:
                return Completion(reply, "stand-in", "a" * 64, 11, 7, 3)
        return Completion('{"rules":[]}', "stand-in", "a" * 64, 11, 7, 3)


@pytest_asyncio.fixture
async def world(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[World]:
    source = tmp_path / "source"
    for rel, data in {**FILES, "unique.txt": uuid.uuid4().hex.encode()}.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data)
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    async with session_scope(engine) as session:
        snapshot, _ = await store_snapshot(session, pinned)
    yield World(snapshot.id, snapshot.revision, tmp_path / "store")
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


async def snapshot_of(session: AsyncSession, world: World) -> Snapshot:
    return (
        await session.execute(select(Snapshot).where(Snapshot.id == world.snapshot_id))
    ).scalar_one()


def job_for(world: World, path: str, run: uuid.UUID | None = None) -> Claimed:
    return Claimed(
        uuid.uuid4(),
        run or uuid.uuid4(),
        BUSINESS_RULE,
        rule_job_hash(path),
        1,
        "w",
        world.snapshot_id,
    )


async def versions(session: AsyncSession, run: uuid.UUID) -> list[ClaimVersion]:
    rows = await session.execute(
        select(ClaimVersion)
        .join(Claim, Claim.id == ClaimVersion.claim_id)
        .where(Claim.run_id == run)
    )
    return list(rows.scalars())


def test_business_rule_is_not_one_of_the_always_on_agents() -> None:
    assert BUSINESS_RULE not in AGENT_JOBS


def test_the_worker_has_no_model_handler_unless_a_client_is_given(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    assert BUSINESS_RULE not in cli.handlers(engine, tmp_path)
    assert BUSINESS_RULE in cli.handlers(engine, tmp_path, ByFile({}))


async def test_one_job_per_file_with_a_candidate_and_a_repeat_adds_none(
    engine: AsyncEngine, world: World
) -> None:
    run = uuid.uuid4()
    async with session_scope(engine) as s:
        snap = await snapshot_of(s, world)
        first = await enqueue_business_rule(s, snap, run, world.store)
        again = await enqueue_business_rule(s, snap, run, world.store)
    assert sorted(first) == ["lib/limits.js", "lib/price.js"]  # not plain.js: no candidate
    assert all(created for _, created in first.values())
    assert {p: (j, False) for p, (j, _) in first.items()} == again


async def test_a_job_stores_only_its_files_claims_and_a_repeat_adds_nothing(
    session: AsyncSession, world: World
) -> None:
    model = ByFile({"lib/price.js": GOOD_PRICE})
    job = job_for(world, "lib/price.js")
    handler = business_rule_handler(sessions_in(session), world.store, model)
    await handler(job)
    keys = {
        c.key
        for c in (await session.execute(select(Claim).where(Claim.run_id == job.run_id))).scalars()
    }
    assert keys == {"br:lib/price.js:4:1"}  # nothing about lib/limits.js
    assert model.calls == 1
    await handler(job)
    assert await n(session, Claim, Claim.run_id == job.run_id) == 1


async def test_a_stored_rule_is_inferred_from_a_model_and_never_confirmed(
    session: AsyncSession, world: World
) -> None:
    job = job_for(world, "lib/price.js")
    await business_rule_handler(
        sessions_in(session), world.store, ByFile({"lib/price.js": GOOD_PRICE})
    )(job)
    (v,) = await versions(session, job.run_id)
    assert (v.status, v.producer_kind, v.producer) == ("inferred", "model", "businessrule@1")


async def test_a_sentence_the_verifier_blocks_is_stored_unknown_and_queued(
    session: AsyncSession, world: World
) -> None:
    job = job_for(world, "lib/price.js")
    await business_rule_handler(
        sessions_in(session), world.store, ByFile({"lib/price.js": UNRELATED})
    )(job)
    (v,) = await versions(session, job.run_id)
    assert v.status == "unknown"
    queued = (
        (await session.execute(select(ReviewItem).where(ReviewItem.claim_version_id == v.id)))
        .scalars()
        .all()
    )
    assert queued


async def test_every_model_call_is_logged_with_counts_and_no_text(
    session: AsyncSession, world: World
) -> None:
    job = job_for(world, "lib/price.js")
    await business_rule_handler(
        sessions_in(session), world.store, ByFile({"lib/price.js": GOOD_PRICE})
    )(job)
    rows = (
        (await session.execute(select(ModelCall).where(ModelCall.run_id == job.run_id)))
        .scalars()
        .all()
    )
    assert [(r.model, r.tokens_in, r.tokens_out, r.latency_ms) for r in rows] == [
        ("stand-in", 11, 7, 3)
    ]
    assert len(rows[0].prompt_hash) == 64
    assert "discount returns" not in repr(rows[0].__dict__)


async def test_a_failed_model_stores_unknown_claims_not_nothing(
    session: AsyncSession, world: World
) -> None:
    from services.models import FakeClient

    job = job_for(world, "lib/limits.js")
    await business_rule_handler(sessions_in(session), world.store, FakeClient([]))(job)
    (v,) = await versions(session, job.run_id)
    assert v.status == "unknown"


async def test_the_queue_runs_the_model_job_to_success(
    engine: AsyncEngine, session: AsyncSession, world: World
) -> None:
    run = uuid.uuid4()
    async with session_scope(engine) as s:
        snap = await snapshot_of(s, world)
        queued = await enqueue_business_rule(s, snap, run, world.store)
    handlers = {BUSINESS_RULE: business_rule_handler(sessions_in(session), world.store, ByFile({}))}
    assert await run_until_idle(engine, handlers, lease_seconds()) == 2
    for job_id, _ in queued.values():
        assert (await job_row(engine, job_id))["status"] == "succeeded"
    _, reader = await load_reader(session, world.snapshot_id, world.store)
    assert reader.paths()
