"""Review decisions: REV-1.1 to REV-2.1, audit, edit re-verification, export (OUT-1.2)."""

import datetime as dt
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from services.claims import WITHHELD_TEXT, add_version, verify_and_store
from services.db.models import (
    AuditLog,
    ClaimVersion,
    Evidence,
    ReviewDecision,
    ReviewItem,
    Snapshot,
)
from services.evals.corpus import APP, lines, stored
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.ingest.store import store_snapshot
from services.review import (
    ReviewError,
    decide,
    export_markdown,
    history,
    list_claims,
    resolve_version_id,
    show,
)
from services.review.__main__ import build_parser
from services.verifier import ClaimInput

pytestmark = pytest.mark.requires_db

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
SECRET = "AKIA" + "IOSFODNN7EXAMPLE"
T0 = dt.datetime(2026, 11, 6, 9, 0, tzinfo=dt.UTC)


def at(minutes: int) -> dt.datetime:
    return T0 + dt.timedelta(minutes=minutes)


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
    world: tuple[Snapshot, SnapshotReader, uuid.UUID],
    key: str,
    *,
    status: str = "confirmed",
    producer_kind: str = "deterministic",
    text: str = "The three report routes are registered in a loop.",
    evidence: bool = True,
    kind: str = "route",
) -> uuid.UUID:
    snapshot, reader, run_id = world
    claim = ClaimInput(
        claim_id=key,
        text=text,
        status=status,
        producer_kind=producer_kind,
        evidence=(stored(reader, lines("app.js", 24, 28)),) if evidence else (),
    )
    done = await verify_and_store(
        session,
        snapshot_id=snapshot.id,
        run_id=run_id,
        kind=kind,
        claim=claim,
        producer="test@1",
        reader=reader,
    )
    return done.version_id


async def count(session: AsyncSession, model: type, *where: Any) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


async def accept(session: AsyncSession, world: Any, vid: uuid.UUID, **kw: Any) -> Any:
    return await decide(
        session,
        version_id=vid,
        decision=kw.pop("decision", "accept"),
        reviewer=kw.pop("reviewer", "dana"),
        reason=kw.pop("reason", None),
        reader=world[1],
        **kw,
    )


async def test_queue_holds_unknown_and_inferred_and_undecided_adds_confirmed(
    session: AsyncSession, world: Any
) -> None:
    await put(session, world, "conf")
    await put(session, world, "inf", status="inferred", producer_kind="model")
    await put(session, world, "unk", evidence=False, status="inferred", producer_kind="model")
    run = world[2]
    queue = {r.key: r for r in await list_claims(session, run_id=run)}
    assert set(queue) == {"inf", "unk"}  # REV-2.1; Confirmed is not queued
    assert queue["unk"].status == "unknown" and queue["unk"].queue_reason == "verifier_failure"
    undecided = {r.key for r in await list_claims(session, run_id=run, view="undecided")}
    assert undecided == {"conf", "inf", "unk"}


async def test_accept_records_decision_audit_and_resolves_the_item(
    session: AsyncSession, world: Any
) -> None:
    vid = await put(session, world, "inf", status="inferred", producer_kind="model")
    done = await accept(session, world, vid, reason="matches the code", now=at(1))
    assert done.decision == "accept" and done.new_version_id is None
    d = (await session.execute(select(ReviewDecision))).scalar_one()
    assert (d.reviewer, d.decision, d.reason, d.decided_at) == (
        "dana", "accept", "matches the code", at(1)
    )  # fmt: skip
    item = (await session.execute(select(ReviewItem))).scalar_one()
    assert item.status == "resolved"
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "review.accept"))
    ).scalar_one()
    assert audit.actor == "dana" and audit.subject_id == str(vid)
    assert "matches the code" not in str(audit.detail)  # IDs and flags only
    assert [r.decision for r in await list_claims(session, view="queue")] == []
    assert [r.decision for r in await list_claims(session, view="decided")] == ["accept"]


async def test_nothing_is_accepted_without_a_call(session: AsyncSession, world: Any) -> None:
    await put(session, world, "conf")
    await put(session, world, "inf", status="inferred", producer_kind="model")
    assert await count(session, ReviewDecision) == 0  # REV-1.1: writing a claim decides nothing


async def test_unknown_and_withheld_cannot_be_accepted(session: AsyncSession, world: Any) -> None:
    unk = await put(session, world, "unk", evidence=False, status="inferred", producer_kind="model")
    with pytest.raises(ReviewError, match="Unknown"):
        await accept(session, world, unk)
    secret = await put(session, world, "sec", status="inferred", producer_kind="model", text=SECRET)
    version = (
        await session.execute(select(ClaimVersion).where(ClaimVersion.id == secret))
    ).scalar_one()
    assert version.text == WITHHELD_TEXT
    with pytest.raises(ReviewError, match="Unknown|withheld"):
        await accept(session, world, secret)
    assert await count(session, ReviewDecision) == 0
    assert await count(session, AuditLog, AuditLog.action == "review.accept") == 0


async def test_accept_fails_closed_when_the_snapshot_no_longer_matches(
    session: AsyncSession, world: Any, tmp_path: Path
) -> None:
    vid = await put(session, world, "conf")
    changed = tmp_path / "changed"
    shutil.copytree(APP, changed)
    target = changed / "app.js"
    target.write_text(target.read_text().replace("report", "REPORT"), encoding="utf-8")
    other = SnapshotReader.from_pinned(pin_local(changed, tmp_path / "store2", LIMITS))
    with pytest.raises(ReviewError, match="re-verification"):
        await decide(
            session, version_id=vid, decision="accept", reviewer="dana", reason=None, reader=other
        )
    assert await count(session, ReviewDecision) == 0


@pytest.mark.parametrize(
    ("decision", "reviewer", "reason", "message"),
    [
        ("reject", "dana", None, "needs a reason"),
        ("reject", "dana", "  ", "needs a reason"),
        ("accept", "  ", None, "reviewer name"),
        ("reject", "dana", "token " + SECRET, "personal-data|secret|AKIA|aws|key"),
        ("approve", "dana", None, "decision must be"),
        ("accept", "x" * 65, None, "longer than"),
    ],
)
async def test_refusals_store_nothing(
    session: AsyncSession,
    world: Any,
    decision: str,
    reviewer: str,
    reason: str | None,
    message: str,
) -> None:
    vid = await put(session, world, "inf", status="inferred", producer_kind="model")
    with pytest.raises(ReviewError, match=message):
        await accept(session, world, vid, decision=decision, reviewer=reviewer, reason=reason)
    assert await count(session, ReviewDecision) == 0
    assert await count(session, AuditLog, AuditLog.action.like("review.%")) == 0
    assert (await session.execute(select(ReviewItem))).scalar_one().status == "open"


async def test_reject_is_recorded_and_excluded_from_export(
    session: AsyncSession, world: Any
) -> None:
    keep = await put(session, world, "keep", status="inferred", producer_kind="model")
    drop = await put(session, world, "drop", status="inferred", producer_kind="model")
    await accept(session, world, keep, now=at(1))
    await accept(session, world, drop, decision="reject", reason="wrong", now=at(2))
    doc = await export_markdown(session, world[2], today=dt.date(2026, 11, 6))
    assert "`keep`" in doc and "`drop`" not in doc
    assert "Accepted: 1 of 2 claims" in doc and "1 rejected" in doc


async def test_a_decision_can_be_revised_and_the_latest_wins(
    session: AsyncSession, world: Any
) -> None:
    vid = await put(session, world, "inf", status="inferred", producer_kind="model")
    await accept(session, world, vid, now=at(1))
    await accept(session, world, vid, decision="reject", reason="second look", now=at(2))
    assert await count(session, ReviewDecision) == 2  # append-only: both are kept
    rows = await list_claims(session, view="all")
    assert rows[0].decision == "reject"
    log = await history(session)
    assert [h["decision"] for h in log] == ["reject", "accept"]
    assert "`inf`" not in await export_markdown(session, world[2], today=dt.date(2026, 11, 6))


async def test_edit_stores_a_new_inferred_human_version_and_needs_its_own_accept(
    session: AsyncSession, world: Any
) -> None:
    v1 = await put(session, world, "conf")
    done = await accept(
        session, world, v1, decision="edit", reason="clearer", new_text="Report routes loop.",
        now=at(1),
    )  # fmt: skip
    assert done.new_version_id is not None and done.new_status == "inferred"
    v2 = (
        await session.execute(select(ClaimVersion).where(ClaimVersion.id == done.new_version_id))
    ).scalar_one()
    assert (v2.version, v2.status, v2.producer_kind, v2.producer) == (
        2, "inferred", "human", "review:dana"
    )  # fmt: skip
    assert await count(session, Evidence, Evidence.claim_version_id == v2.id) == 1  # carried over
    items = {
        i.claim_version_id: i for i in (await session.execute(select(ReviewItem))).scalars().all()
    }
    assert v1 not in items  # a Confirmed claim had no item; the edit adds one for v2
    assert items[v2.id].status == "open" and items[v2.id].reason == "inferred"
    with pytest.raises(ReviewError, match="not the latest"):
        await accept(session, world, v1)
    # Not accepted by the edit: it still needs a decision of its own (REV-1.3).
    assert "Report routes loop." not in await export_markdown(
        session, world[2], today=dt.date(2026, 11, 6)
    )
    await accept(session, world, v2.id, now=at(2))
    doc = await export_markdown(session, world[2], today=dt.date(2026, 11, 6))
    assert "Report routes loop." in doc
    assert "registered in a loop" not in doc  # the replaced wording is not exported


async def test_edit_is_verified_again_and_a_failure_is_stored_unknown(
    session: AsyncSession, world: Any
) -> None:
    v1 = await put(session, world, "conf")
    done = await accept(
        session, world, v1, decision="edit", reason="needs support", new_text="Changed.",
        cites=["app.js:24-28"], now=at(1),
    )  # fmt: skip
    assert done.new_status == "inferred"
    with pytest.raises(ReviewError, match="does not resolve|bad citation"):
        await accept(
            session, world, done.new_version_id, decision="edit", reason="x", new_text="Other",
            cites=["app.js:900-901"],
        )  # fmt: skip
    with pytest.raises(ReviewError, match="bad citation"):
        await accept(
            session, world, done.new_version_id, decision="edit", reason="x", new_text="Other",
            cites=["nonsense"],
        )  # fmt: skip
    assert await count(session, ClaimVersion) == 2  # the refused edits stored nothing


async def test_edit_of_an_unknown_claim_with_a_citation_gives_it_evidence(
    session: AsyncSession, world: Any
) -> None:
    unk = await put(session, world, "unk", evidence=False, status="inferred", producer_kind="model")
    done = await accept(
        session, world, unk, decision="edit", reason="found the code", new_text="Routes loop.",
        cites=["app.js:24-28"], now=at(1),
    )  # fmt: skip
    assert done.new_status == "inferred"


async def test_edit_without_evidence_stays_unknown(session: AsyncSession, world: Any) -> None:
    unk = await put(session, world, "unk", evidence=False, status="inferred", producer_kind="model")
    done = await accept(
        session, world, unk, decision="edit", reason="reworded", new_text="Reworded.", now=at(1)
    )
    assert done.new_status == "unknown"  # fail closed: no evidence, no standing
    with pytest.raises(ReviewError, match="Unknown"):
        await accept(session, world, done.new_version_id)


async def test_edit_refusals(session: AsyncSession, world: Any) -> None:
    v1 = await put(session, world, "conf", text="Same text.")
    cases: list[tuple[dict[str, Any], str]] = [
        ({"new_text": None}, "needs the new text"),
        ({"new_text": "Same text."}, "same as the current"),
        ({"new_text": "has " + SECRET}, "secret|AKIA|key|personal"),
    ]
    for kw, message in cases:
        with pytest.raises(ReviewError, match=message):
            await accept(session, world, v1, decision="edit", reason="r", **kw)
    with pytest.raises(ReviewError, match="belong to edit"):
        await accept(session, world, v1, new_text="x")
    assert await count(session, ReviewDecision) == 0 and await count(session, ClaimVersion) == 1


async def test_show_gives_evidence_excerpt_and_withholds_a_secret_excerpt(
    session: AsyncSession, world: Any
) -> None:
    vid = await put(session, world, "conf")
    view = await show(session, vid, world[1])
    assert view.row.key == "conf" and view.producer == "test@1"
    assert view.evidence[0].ref.startswith("app.js:24-28") and view.evidence[0].excerpt
    offline = await show(session, vid, None)
    assert offline.evidence[0].excerpt is None and "not available" in (
        offline.evidence[0].note or ""
    )


async def test_add_version_refuses_a_version_that_is_not_the_latest(
    session: AsyncSession, world: Any
) -> None:
    v1 = await put(session, world, "conf")
    claim = ClaimInput(
        "conf", "Second.", "inferred", "human", (stored(world[1], lines("app.js", 24, 28)),)
    )
    first = await add_version(session, based_on=v1, claim=claim, producer="p", reader=world[1])
    assert first.created
    with pytest.raises(ValueError, match="not the latest"):
        await add_version(session, based_on=v1, claim=claim, producer="p", reader=world[1])
    with pytest.raises(LookupError):
        await add_version(
            session, based_on=uuid.uuid4(), claim=claim, producer="p", reader=world[1]
        )


async def test_resolve_version_id(session: AsyncSession, world: Any) -> None:
    vid = await put(session, world, "conf")
    assert await resolve_version_id(session, str(vid)) == vid
    assert await resolve_version_id(session, str(vid)[:12]) == vid
    for bad in ("abc", "zzzzzzzz", "00000000"):
        with pytest.raises(ReviewError):
            await resolve_version_id(session, bad)


async def test_export_header_and_contents(session: AsyncSession, world: Any) -> None:
    snapshot, _, run = world
    vid = await put(session, world, "conf", kind="route")
    await put(session, world, "other", status="inferred", producer_kind="model")
    await accept(session, world, vid, now=at(1))
    doc = await export_markdown(session, run, today=dt.date(2026, 11, 6))
    assert f"`{snapshot.revision}`" in doc and f"`{run}`" in doc  # OUT-1.2
    assert "Date: 2026-11-06" in doc
    assert "Accepted: 1 of 2 claims" in doc and "1 undecided" in doc
    assert "## route" in doc and "**Confirmed**" in doc and "app.js:24-28" in doc
    assert "dana" not in doc  # reviewer names stay in the audit trail
    with pytest.raises(LookupError):
        await export_markdown(session, uuid.uuid4())


def test_parser_reads_every_command() -> None:
    parser = build_parser()
    assert parser.parse_args(["queue", "--view", "undecided"]).view == "undecided"
    assert parser.parse_args(["accept", "aaaaaaaa", "bbbbbbbb", "--reviewer", "d"]).ids == [
        "aaaaaaaa", "bbbbbbbb"
    ]  # fmt: skip
    edit = parser.parse_args(
        ["edit", "aaaaaaaa", "--text", "t", "--cite", "a.js:1-2", "--cite", "b.js:3"]
    )
    assert edit.cite == ["a.js:1-2", "b.js:3"]
    with pytest.raises(SystemExit):
        parser.parse_args(["queue", "--view", "nonsense"])
