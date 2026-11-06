"""python -m services.worker work | analyze <source> [--ref REF]

`work` recovers jobs a dead worker left running, then runs queued jobs until the queue is empty
and exits. `analyze` pins a source, stores it, queues a Discovery job for a new run and works it:
the CLI path for a first analysis (build plan: CLI before UI). Output is counts and IDs only,
never claim text or a matched value.
"""

import argparse
import asyncio
import sys
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from services.api.settings import get_settings
from services.db.models import Claim, ClaimVersion, Job, ReviewItem
from services.db.session import make_engine, session_scope
from services.ingest.errors import IngestError
from services.ingest.pin import PinnedSource, pin_github, pin_local
from services.ingest.store import store_snapshot
from services.jobs import Handler, lease_seconds, run_until_idle, sweep_on_startup
from services.worker.handlers import (
    CODE_ANALYSIS,
    DATA,
    DISCOVERY,
    code_analysis_handler,
    data_handler,
    discovery_handler,
    enqueue_agents,
)


class RunSummary(TypedDict):
    run_id: str
    jobs: dict[str, int]
    failed_job_types: list[str]
    claims_by_status: dict[str, int]
    review_queue_by_reason: dict[str, int]


def handlers(engine: AsyncEngine, store: Path) -> dict[str, Handler]:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        async with session_scope(engine) as session:
            yield session

    return {
        DISCOVERY: discovery_handler(sessions, store),
        CODE_ANALYSIS: code_analysis_handler(sessions, store),
        DATA: data_handler(sessions, store),
    }


async def work(engine: AsyncEngine, store: Path) -> dict[str, int]:
    """Sweep, then drain the queue. Returns {"swept_requeued", "swept_failed", "ran"}."""
    swept = await sweep_on_startup(engine, lease_seconds())
    ran = await run_until_idle(engine, handlers(engine, store), lease_seconds())
    return {"swept_requeued": swept["requeued"], "swept_failed": swept["failed"], "ran": ran}


async def summary(session: AsyncSession, run_id: uuid.UUID) -> RunSummary:
    rows = (
        await session.execute(select(Job.job_type, Job.status).where(Job.run_id == run_id))
    ).all()
    jobs = [status for _, status in rows]
    stored = (
        await session.execute(
            select(ClaimVersion.status, func.count())
            .join(Claim, Claim.id == ClaimVersion.claim_id)
            .where(Claim.run_id == run_id)
            .group_by(ClaimVersion.status)
        )
    ).all()
    queued = (
        await session.execute(
            select(ReviewItem.reason, func.count())
            .join(ClaimVersion, ClaimVersion.id == ReviewItem.claim_version_id)
            .join(Claim, Claim.id == ClaimVersion.claim_id)
            .where(Claim.run_id == run_id)
            .group_by(ReviewItem.reason)
        )
    ).all()
    return {
        "run_id": str(run_id),
        "jobs": dict(Counter(jobs)),
        "failed_job_types": sorted(t for t, status in rows if status == "failed"),
        "claims_by_status": {status: n for status, n in stored},
        "review_queue_by_reason": {reason: n for reason, n in queued},
    }


async def analyze(engine: AsyncEngine, pinned: PinnedSource, store: Path) -> RunSummary:
    run_id = uuid.uuid4()
    async with session_scope(engine) as session:
        snapshot, _ = await store_snapshot(session, pinned)
        await enqueue_agents(session, snapshot, run_id)
    await work(engine, store)
    async with session_scope(engine) as session:
        return await summary(session, run_id)


def _pin(source: str, ref: str | None, store: Path) -> PinnedSource:
    settings = get_settings()
    if source.startswith(("http://", "https://", "git@", "ssh://", "git://")):
        token = settings.github_token.get_secret_value() if settings.github_token else None
        return pin_github(source, store, ref=ref, token=token)
    if ref:
        raise IngestError("bad_ref", "--ref only applies to GitHub URLs")
    return pin_local(source, store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("work", help="sweep stale jobs, run queued jobs until idle, exit")
    one = sub.add_parser(
        "analyze", help="pin a source and run Discovery, Code Analysis and Data on it"
    )
    one.add_argument("source", help="GitHub repository URL or local directory")
    one.add_argument("--ref", help="branch, tag or commit SHA (GitHub URLs only)")
    args = parser.parse_args(argv)
    settings = get_settings()
    store = Path(settings.snapshot_dir).resolve()

    async def go() -> int:
        engine = make_engine()
        try:
            if args.command == "work":
                print(await work(engine, store))
                return 0
            pinned = _pin(args.source, args.ref, store)
            result = await analyze(engine, pinned, store)
            print(result)
            return 1 if result["jobs"].get("failed", 0) else 0
        finally:
            await engine.dispose()

    try:
        return asyncio.run(go())
    except IngestError as error:
        print(f"Rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
