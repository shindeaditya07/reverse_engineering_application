"""Recording a pinned source in the claim store. Needs Postgres (see tests/conftest.py)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from services.db.models import AuditLog, Snapshot, SnapshotFile
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local
from services.ingest.store import store_snapshot

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parent.parent
LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
SECRET = "fxlive_0f1e2d3c4b5a69788796"


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(connection, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def fixture_pin(tmp_path: Path) -> PinnedSource:
    return pin_local(ROOT / "fixtures/legacy-app", tmp_path / "store", LIMITS)


async def count(session: AsyncSession, model: type, *where: ColumnElement[bool]) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


async def test_stores_snapshot_files_and_findings(
    session: AsyncSession, fixture_pin: PinnedSource
) -> None:
    snapshot, created = await store_snapshot(session, fixture_pin)
    assert created is True
    assert (snapshot.source_kind, snapshot.revision) == ("local_path", fixture_pin.revision)
    assert await count(session, SnapshotFile, SnapshotFile.snapshot_id == snapshot.id) == len(
        fixture_pin.tree.files
    )
    subject = AuditLog.subject_id == str(snapshot.id)
    assert await count(session, AuditLog, subject, AuditLog.action == "ingest.finding") == len(
        fixture_pin.report.findings
    )
    assert await count(session, AuditLog, subject, AuditLog.action == "ingest.snapshot") == 1


async def test_audit_rows_hold_no_matched_values(
    session: AsyncSession, fixture_pin: PinnedSource
) -> None:
    snapshot, _ = await store_snapshot(session, fixture_pin)
    rows = (
        await session.execute(
            select(AuditLog.detail).where(AuditLog.subject_id == str(snapshot.id))
        )
    ).scalars()
    text = " ".join(str(detail) for detail in rows)
    assert SECRET not in text
    assert "jane.example@example.com" not in text
    assert "secret:credential" in text


async def test_summary_row_counts_findings_by_kind(
    session: AsyncSession, fixture_pin: PinnedSource
) -> None:
    snapshot, _ = await store_snapshot(session, fixture_pin)
    detail = (
        await session.execute(
            select(AuditLog.detail).where(
                AuditLog.subject_id == str(snapshot.id), AuditLog.action == "ingest.snapshot"
            )
        )
    ).scalar_one()
    assert detail["files"] == len(fixture_pin.tree.files)
    assert detail["findings"] == {"pii:email": 2, "pii:field": 4, "secret:credential": 1}


async def test_ingesting_the_same_revision_again_writes_nothing(
    session: AsyncSession, fixture_pin: PinnedSource
) -> None:
    first, created_first = await store_snapshot(session, fixture_pin)
    audit_before = await count(session, AuditLog)
    second, created_second = await store_snapshot(session, fixture_pin)
    assert (created_first, created_second) == (True, False)
    assert second.id == first.id
    assert await count(session, Snapshot, Snapshot.id == first.id) == 1
    assert await count(session, AuditLog) == audit_before


async def test_a_changed_source_is_a_new_snapshot(session: AsyncSession, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.js").write_text("one")
    first, _ = await store_snapshot(session, pin_local(source, tmp_path / "store", LIMITS))
    (source / "a.js").write_text("two")
    second, created = await store_snapshot(session, pin_local(source, tmp_path / "store", LIMITS))
    assert created is True
    assert first.id != second.id
