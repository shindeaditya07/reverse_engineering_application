"""Job handlers. A handler reads its input from the store, never from the job row alone, and
writes only through the claim writer, so running it twice stores nothing twice."""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import Snapshot, SnapshotFile
from services.discovery import discover
from services.discovery.store import store_discovery
from services.evidence import SnapshotReader
from services.jobs import Claimed, enqueue
from services.jobs.runner import Handler

DISCOVERY = "discovery"
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class JobInputMissing(Exception):
    """The job names no snapshot, or one that is not in the store. A retry cannot fix it, but
    the retry budget (OPS-1.1) bounds it, and the error class is what the failed job shows."""


async def load_reader(
    session: AsyncSession, snapshot_id: uuid.UUID | None, store: Path
) -> tuple[Snapshot, SnapshotReader]:
    """The pinned copy as the evidence reader sees it. Each file is re-hashed on read, so a copy
    changed since it was pinned fails the job instead of producing claims about other bytes."""
    if snapshot_id is None:
        raise JobInputMissing("the job has no snapshot")
    snapshot = (
        await session.execute(select(Snapshot).where(Snapshot.id == snapshot_id))
    ).scalar_one_or_none()
    if snapshot is None:
        raise JobInputMissing("the snapshot is not in the store")
    files = (
        await session.execute(
            select(SnapshotFile.path, SnapshotFile.sha256).where(
                SnapshotFile.snapshot_id == snapshot_id
            )
        )
    ).all()
    return snapshot, SnapshotReader(store / snapshot.revision, {p: h for p, h in files})


async def enqueue_discovery(
    session: AsyncSession, snapshot: Snapshot, run_id: uuid.UUID
) -> tuple[uuid.UUID, bool]:
    """One discovery job per (run, snapshot). The revision is the input hash."""
    return await enqueue(session, run_id, DISCOVERY, snapshot.revision, snapshot.id)


def discovery_handler(sessions: SessionFactory, store: Path) -> Handler:
    """Run Discovery on the job's snapshot and store its findings in one transaction: a crash
    stores nothing, and a repeat finds every claim key already stored."""

    async def handle(job: Claimed) -> None:
        async with sessions() as session:
            snapshot, reader = await load_reader(session, job.snapshot_id, store)
            found = discover(reader, reader.paths())
            await store_discovery(session, snapshot.id, job.run_id, found, reader)

    return handle
