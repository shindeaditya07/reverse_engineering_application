"""Run claimed jobs. The claim commits before the handler runs, so a crash mid-handler leaves a
`running` row with a lease for the sweeper to find, never a lost job.

A handler must be idempotent: after a crash it runs again from the start. Write claims through
the claim store's identities (for example an upsert keyed by claim id), not blind inserts.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncEngine

from services.db.session import session_scope
from services.jobs.queue import (
    Claimed,
    claim_next,
    complete,
    fail,
    sweep,
)

Handler = Callable[[Claimed], Awaitable[None]]


async def sweep_on_startup(engine: AsyncEngine, lease_seconds: float) -> dict[str, int]:
    """Call once when a worker starts (NFR-7)."""
    async with session_scope(engine) as session:
        return await sweep(session, lease_seconds)


async def run_one(
    engine: AsyncEngine,
    handlers: Mapping[str, Handler],
    lease_seconds: float,
    worker_id: str | None = None,
) -> bool:
    """Claim and run one job. False when the queue had nothing for this worker.

    `lease_seconds` bounds the handler; the sweeper must use the same value."""
    worker = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
    async with session_scope(engine) as session:
        # Only types this worker can handle, so an unknown type waits for a worker that can.
        job = await claim_next(session, worker, sorted(handlers))
    if job is None:
        return False
    error: str | None = None
    try:
        # Stop a hung handler before the sweeper would presume it dead and requeue it.
        await asyncio.wait_for(handlers[job.job_type](job), timeout=lease_seconds)
    except Exception as caught:  # a failed job is a recorded state, never a crashed worker
        error = type(caught).__name__
    async with session_scope(engine) as session:
        if error is None:
            await complete(session, job.id, worker)
        else:
            await fail(session, job.id, worker, error)
    return True


async def run_until_idle(
    engine: AsyncEngine,
    handlers: Mapping[str, Handler],
    lease_seconds: float,
    worker_id: str | None = None,
) -> int:
    ran = 0
    while await run_one(engine, handlers, lease_seconds, worker_id):
        ran += 1
    return ran
