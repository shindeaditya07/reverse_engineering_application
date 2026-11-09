"""Coverage and accuracy reports: REV-3.1 to REV-3.5."""

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from services.claims import verify_and_store
from services.db.models import AuditLog, Snapshot
from services.evals.corpus import APP, lines, stored
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot
from services.review import (
    ReviewError,
    accuracy,
    coverage,
    decide,
    draw_sample,
    load_sample,
    report_markdown,
)
from services.review.__main__ import build_parser
from services.verifier import ClaimInput

pytestmark = pytest.mark.requires_db

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
DAY = dt.date(2026, 11, 9)


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


async def put(
    session: AsyncSession,
    world: Any,
    key: str,
    *,
    status: str = "inferred",
    kind: str = "route",
    evidence: bool = True,
    span: tuple[str, int, int] = ("app.js", 24, 28),
) -> uuid.UUID:
    snapshot, reader, run_id = world
    claim = ClaimInput(
        claim_id=key,
        text=f"Claim {key}.",
        status=status,
        producer_kind="deterministic" if status == "confirmed" else "model",
        evidence=(stored(reader, lines(*span)),) if evidence else (),
    )
    done = await verify_and_store(
        session,
        snapshot_id=snapshot.id,
        run_id=run_id,
        kind=kind,
        claim=claim,
        producer="t@1",
        reader=reader,
    )
    return done.version_id


async def many(session: AsyncSession, world: Any, n: int, **kw: Any) -> list[uuid.UUID]:
    return [await put(session, world, f"k{i}", **kw) for i in range(n)]


async def mark(session: AsyncSession, world: Any, vid: uuid.UUID, decision: str) -> None:
    await decide(
        session,
        version_id=vid,
        decision=decision,
        reviewer="dana",
        reason=None if decision == "accept" else "r",
        reader=world[1],
        new_text="Reworded." if decision == "edit" else None,
    )


# ---- the sample ------------------------------------------------------------------------


async def test_the_sample_is_random_recorded_and_repeatable_by_seed(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 70)
    sample = await draw_sample(session, world[2], drawn_by="dana", seed=7)
    assert len(sample.version_ids) == 60 and sample.eligible == 70 and sample.seed == 7
    assert not sample.below_minimum
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "accuracy.sample_drawn"))
    ).scalar_one()
    assert audit.actor == "dana" and audit.detail is not None and audit.detail["seed"] == 7
    assert "Claim k" not in str(audit.detail)  # IDs only
    assert await load_sample(session, world[2]) == sample


async def test_a_second_draw_for_the_same_run_is_refused(session: AsyncSession, world: Any) -> None:
    await many(session, world, 80)
    first = await draw_sample(session, world[2], drawn_by="dana", seed=1)
    with pytest.raises(ReviewError, match="already has"):
        await draw_sample(session, world[2], drawn_by="dana", seed=2)
    assert len(set(first.version_ids)) == 60


async def test_only_undecided_assertions_are_eligible(session: AsyncSession, world: Any) -> None:
    ids = await many(session, world, 66)
    await put(session, world, "unk", evidence=False)  # stored Unknown: not an assertion
    await mark(session, world, ids[0], "accept")  # already seen
    await mark(session, world, ids[1], "reject")
    sample = await draw_sample(session, world[2], drawn_by="dana", seed=3)
    assert sample.eligible == 64
    assert ids[0] not in sample.version_ids and ids[1] not in sample.version_ids


async def test_below_the_minimum_is_refused_unless_asked_and_then_flagged(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 10)
    with pytest.raises(ReviewError, match="minimum"):
        await draw_sample(session, world[2], drawn_by="dana")
    with pytest.raises(ReviewError, match="minimum"):
        await draw_sample(session, world[2], drawn_by="dana", size=5)
    assert await load_sample(session, world[2]) is None
    sample = await draw_sample(session, world[2], drawn_by="dana", below_minimum=True)
    assert len(sample.version_ids) == 10 and sample.below_minimum


async def test_a_sample_larger_than_the_minimum_can_be_asked_for(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 70)
    with pytest.raises(ReviewError, match="70 are eligible"):
        await draw_sample(session, world[2], drawn_by="dana", size=100)
    sample = await draw_sample(session, world[2], drawn_by="dana", size=65)
    assert len(sample.version_ids) == 65 and not sample.below_minimum


@pytest.mark.parametrize(("name", "size"), [("", None), ("dana", 0)])
async def test_draw_refusals(
    session: AsyncSession, world: Any, name: str, size: int | None
) -> None:
    await many(session, world, 3)
    with pytest.raises(ReviewError):
        await draw_sample(session, world[2], drawn_by=name, size=size, below_minimum=True)
    assert await load_sample(session, world[2]) is None


async def test_drawing_for_a_run_without_claims_or_eligible_claims_fails(
    session: AsyncSession, world: Any
) -> None:
    with pytest.raises(LookupError):
        await draw_sample(session, uuid.uuid4(), drawn_by="dana")
    await put(session, world, "unk", evidence=False)
    with pytest.raises(ReviewError, match="no claim is eligible"):
        await draw_sample(session, world[2], drawn_by="dana", below_minimum=True)


# ---- accuracy and the verdict ----------------------------------------------------------


async def decide_sample(session: AsyncSession, world: Any, wrong: int, *, leave: int = 0) -> None:
    sample = await load_sample(session, world[2])
    assert sample is not None
    ids = list(sample.version_ids)
    for index, vid in enumerate(ids[: len(ids) - leave]):
        await mark(session, world, vid, "reject" if index < wrong else "accept")


async def test_a_clean_sample_demonstrates_the_target(session: AsyncSession, world: Any) -> None:
    await many(session, world, 120)
    await draw_sample(session, world[2], drawn_by="dana", size=120, seed=1)
    await decide_sample(session, world, wrong=0)
    acc = await accuracy(session, world[2])
    assert (acc.size, acc.decided, acc.correct) == (120, 120, 120)
    assert acc.verdict.startswith("DEMONSTRATED")


async def test_a_passing_point_estimate_with_a_low_lower_bound_is_not_demonstrated(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 60)
    await draw_sample(session, world[2], drawn_by="dana", seed=1)
    await decide_sample(session, world, wrong=5)  # 55/60 = 92%, interval lower bound ~82%
    acc = await accuracy(session, world[2])
    assert acc.rate.value is not None and acc.rate.value > 0.9 and acc.rate.interval[0] < 0.9
    assert acc.verdict.startswith("NOT DEMONSTRATED") and "point estimate passes" in acc.verdict


async def test_a_failing_estimate_is_not_demonstrated(session: AsyncSession, world: Any) -> None:
    await many(session, world, 60)
    await draw_sample(session, world[2], drawn_by="dana", seed=1)
    await decide_sample(session, world, wrong=20)
    acc = await accuracy(session, world[2])
    assert acc.verdict.startswith("NOT DEMONSTRATED") and "point estimate" not in acc.verdict


async def test_undecided_claims_mean_no_verdict(session: AsyncSession, world: Any) -> None:
    await many(session, world, 60)
    await draw_sample(session, world[2], drawn_by="dana", seed=1)
    await decide_sample(session, world, wrong=0, leave=4)
    acc = await accuracy(session, world[2])
    assert acc.decided == 56 and len(acc.undecided) == 4
    assert acc.verdict.startswith("INCOMPLETE")


async def test_a_small_sample_never_demonstrates_the_target(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 12)
    await draw_sample(session, world[2], drawn_by="dana", below_minimum=True)
    await decide_sample(session, world, wrong=0)
    acc = await accuracy(session, world[2])
    assert acc.verdict.startswith("NOT DEMONSTRATED") and "below the minimum" in acc.verdict


async def test_edit_counts_as_not_correct_and_status_is_broken_out(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 6, status="confirmed")
    await many(session, world, 6, status="inferred")  # same keys: idempotent, stays 6 confirmed
    await put(session, world, "inf", status="inferred")
    await draw_sample(session, world[2], drawn_by="dana", below_minimum=True, seed=2)
    sample = await load_sample(session, world[2])
    assert sample is not None
    ids = list(sample.version_ids)
    await mark(session, world, ids[0], "edit")
    for vid in ids[1:]:
        await mark(session, world, vid, "accept")
    acc = await accuracy(session, world[2])
    assert (acc.decided, acc.correct) == (7, 6)
    assert sum(t for _, t in acc.by_status.values()) == 7


async def test_a_run_without_a_sample_says_so(session: AsyncSession, world: Any) -> None:
    await put(session, world, "k")
    acc = await accuracy(session, world[2])
    assert acc.sample is None and acc.verdict.startswith("NO SAMPLE")


# ---- coverage --------------------------------------------------------------------------


async def test_coverage_counts_accepted_claims_over_everything_found(
    session: AsyncSession, world: Any
) -> None:
    snapshot, reader, run = world
    r1 = await put(session, world, "r1", kind="route", span=("app.js", 24, 28))
    await put(session, world, "r2", kind="route", span=("app.js", 1, 3))
    cov = await coverage(session, run, reader)
    assert cov.endpoints.hits == 0 and cov.endpoints.total == 2 and cov.modules.hits == 0
    assert cov.modules.total >= 1 and "app.js" in cov.uncovered_modules
    await mark(session, world, r1, "accept")
    cov = await coverage(session, run, reader)
    assert cov.modules.hits == 1 and "app.js" not in cov.uncovered_modules
    assert cov.endpoints.hits == 1 and cov.uncovered_endpoints == ("r2",)


async def test_a_claim_that_is_not_accepted_covers_nothing(
    session: AsyncSession, world: Any
) -> None:
    v = await put(session, world, "r1", kind="route")
    await mark(session, world, v, "reject")
    cov = await coverage(session, world[2], world[1])
    assert cov.modules.hits == 0 and cov.endpoints.hits == 0


async def test_unreadable_modules_stay_in_the_denominator(
    session: AsyncSession, world: Any
) -> None:
    snapshot, reader, run = world
    path = next(p for p in reader.paths() if p.endswith(".js"))
    await put(session, world, f"ca:unanalyzed:{path}", kind="unresolved", evidence=False)
    cov = await coverage(session, run, reader)
    assert path in cov.unreadable_modules and path in cov.uncovered_modules


# ---- the report ------------------------------------------------------------------------


async def test_the_report_carries_the_stamp_the_denominators_and_the_verdict(
    session: AsyncSession, world: Any
) -> None:
    snapshot, reader, run = world
    await many(session, world, 62)
    await draw_sample(session, run, drawn_by="dana", seed=5)
    await decide_sample(session, world, wrong=1)
    doc = await report_markdown(session, run, reader, today=DAY)
    assert f"`{snapshot.revision}`" in doc and f"`{run}`" in doc and "Date: 2026-11-09" in doc
    assert "Claims in this run: 62" in doc and "Within the limit." in doc
    assert "Modules with an accepted claim:" in doc and "Endpoints with an accepted claim:" in doc
    assert "seed 5" in doc and "Accuracy: 98% (59/60" in doc
    assert "**DEMONSTRATED:" in doc  # 59/60: the interval's lower bound is about 91%
    assert "Claim k" not in doc  # counts and IDs, never claim text


async def test_the_report_flags_a_run_over_the_pilot_limit_and_a_missing_sample(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 401)
    doc = await report_markdown(session, world[2], world[1], today=DAY)
    assert "EXCEEDED" in doc and "NO SAMPLE" in doc
    with pytest.raises(LookupError):
        await report_markdown(session, uuid.uuid4(), world[1])


async def test_a_below_minimum_sample_is_marked_in_the_report(
    session: AsyncSession, world: Any
) -> None:
    await many(session, world, 5)
    await draw_sample(session, world[2], drawn_by="dana", below_minimum=True)
    doc = await report_markdown(session, world[2], world[1], today=DAY)
    assert "**Below the minimum.**" in doc and "INCOMPLETE" in doc


def test_parser_reads_sample_and_report() -> None:
    parser = build_parser()
    args = parser.parse_args(["sample", "RUN", "--draw", "--size", "70", "--seed", "3"])
    assert (args.draw, args.size, args.seed, args.below_minimum) == (True, 70, 3, False)
    assert parser.parse_args(["report", "RUN", "--out", "r.md"]).out == "r.md"
