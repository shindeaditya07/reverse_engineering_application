"""Job handlers. A handler reads its input from the store, never from the job row alone, and
writes only through the claim writer, so running it twice stores nothing twice."""

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.businessrule.agent import analyze as analyze_rules
from services.businessrule.candidates import find_candidates
from services.businessrule.store import store_rules
from services.codeanalysis import analyze as analyze_code
from services.codeanalysis.store import store_analysis
from services.data import analyze as analyze_data
from services.data.store import store_data
from services.db.models import Snapshot, SnapshotFile
from services.discovery import discover
from services.discovery.inventory import build_inventory
from services.discovery.store import store_discovery
from services.evidence import SnapshotReader
from services.jobs import Claimed, enqueue
from services.jobs.runner import Handler
from services.models import LoggedClient, ModelClient

DISCOVERY = "discovery"
CODE_ANALYSIS = "code_analysis"
DATA = "data"
BUSINESS_RULE = "business_rule"  # needs a model client; not one of AGENT_JOBS
# The three agents that read one pinned snapshot and need nothing from each other. The spec
# draws Discovery first, then Code Analysis and Data in parallel; nothing here enforces that
# order, because none of the three reads another's claims.
AGENT_JOBS = (DISCOVERY, CODE_ANALYSIS, DATA)
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


async def enqueue_agents(
    session: AsyncSession, snapshot: Snapshot, run_id: uuid.UUID
) -> dict[str, tuple[uuid.UUID, bool]]:
    """One job per agent for (run, snapshot). Queueing the same run again adds nothing."""
    return {
        job_type: await enqueue(session, run_id, job_type, snapshot.revision, snapshot.id)
        for job_type in AGENT_JOBS
    }


def _agent_handler(
    sessions: SessionFactory,
    store: Path,
    run_agent: Callable[[SnapshotReader, list[str]], Any],
    save: Callable[..., Awaitable[Any]],
) -> Handler:
    """Run one agent on the job's snapshot and store its findings in one transaction: a crash
    stores nothing, and a repeat finds every claim key already stored."""

    async def handle(job: Claimed) -> None:
        async with sessions() as session:
            snapshot, reader = await load_reader(session, job.snapshot_id, store)
            found = run_agent(reader, reader.paths())
            await save(session, snapshot.id, job.run_id, found, reader)

    return handle


def discovery_handler(sessions: SessionFactory, store: Path) -> Handler:
    return _agent_handler(sessions, store, discover, store_discovery)


def code_analysis_handler(sessions: SessionFactory, store: Path) -> Handler:
    return _agent_handler(sessions, store, analyze_code, store_analysis)


def data_handler(sessions: SessionFactory, store: Path) -> Handler:
    return _agent_handler(sessions, store, analyze_data, store_data)


def rule_job_hash(path: str) -> str:
    """The identity of one Business Rule job: one per file, so no job holds many model calls
    for long (OPS-1.2 stops a job at 600 seconds; the work already stored is kept)."""
    return hashlib.sha256(f"{BUSINESS_RULE}:{path}".encode()).hexdigest()


async def enqueue_business_rule(
    session: AsyncSession, snapshot: Snapshot, run_id: uuid.UUID, store: Path
) -> dict[str, tuple[uuid.UUID, bool]]:
    """One job per file that has a candidate span or could not be read. A repeat adds none."""
    _, reader = await load_reader(session, snapshot.id, store)
    inventory = build_inventory(reader, reader.paths())
    candidates, unread = find_candidates(reader, list(inventory.first_party_sources))
    files = sorted({c.path for c in candidates} | {p for p, _ in unread})
    return {
        path: await enqueue(session, run_id, BUSINESS_RULE, rule_job_hash(path), snapshot.id)
        for path in files
    }


def business_rule_handler(sessions: SessionFactory, store: Path, client: ModelClient) -> Handler:
    """Explain one file's candidates and store the claims in one transaction. Every model call
    is logged (NFR-6). A crash stores nothing; the retry finds stored claim keys unchanged."""

    async def handle(job: Claimed) -> None:
        async with sessions() as session:
            snapshot, reader = await load_reader(session, job.snapshot_id, store)
            wanted = {p for p in reader.paths() if rule_job_hash(p) == job.input_hash}
            found = await analyze_rules(
                LoggedClient(client, session, job.run_id),
                reader,
                reader.paths(),
                only=wanted.__contains__,
            )
            await store_rules(session, snapshot.id, job.run_id, found, reader)

    return handle
