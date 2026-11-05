"""Queue operations. Each function takes a session and leaves the transaction to the caller.

A job is identified by (run_id, job_type, input_hash). Enqueueing the same identity again returns
the existing row and never runs it twice, which is what lets a killed run resume without
duplicating work (AGENTS.md section 4).

`attempts` counts executions. OPS-1.1 allows at most `max_job_retries` retries, so a job runs at
most 1 + max_job_retries times, then enters the visible `failed` state. `last_error` holds an
error class name only, never a message, because messages can carry source values (SEC-1.3).
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import Job
from services.rules_constants import rule_constants

LEASE_EXPIRED = "LeaseExpired"


@dataclass(frozen=True)
class Claimed:
    id: uuid.UUID
    run_id: uuid.UUID
    job_type: str
    input_hash: str
    attempts: int
    worker_id: str


def max_retries() -> int:
    return int(rule_constants("OPS-1.1")["max_job_retries"])


async def enqueue(
    session: AsyncSession, run_id: uuid.UUID, job_type: str, input_hash: str
) -> tuple[uuid.UUID, bool]:
    """(job id, created). `created` is False when the identity already exists in any state."""
    stmt = (
        insert(Job)
        .values(run_id=run_id, job_type=job_type, input_hash=input_hash)
        .on_conflict_do_nothing(constraint="uq_job_identity")
        .returning(Job.id)
    )
    created = (await session.execute(stmt)).scalar_one_or_none()
    if created is not None:
        return created, True
    existing = await session.execute(
        select(Job.id).where(
            Job.run_id == run_id, Job.job_type == job_type, Job.input_hash == input_hash
        )
    )
    return existing.scalar_one(), False


async def claim_next(
    session: AsyncSession, worker_id: str, job_types: list[str] | None = None
) -> Claimed | None:
    """Take the oldest queued job. SKIP LOCKED lets concurrent workers pass over each other's
    rows instead of waiting, so no two workers ever hold the same job."""
    query = select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id)
    if job_types is not None:
        query = query.where(Job.job_type.in_(job_types))
    locked = query.limit(1).with_for_update(skip_locked=True)
    job = (await session.execute(locked)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_at = dt.datetime.now(dt.UTC)
    job.locked_by = worker_id
    await session.flush()
    return Claimed(job.id, job.run_id, job.job_type, job.input_hash, job.attempts, worker_id)


async def complete(session: AsyncSession, job_id: uuid.UUID, worker_id: str) -> bool:
    """Mark succeeded. False when this worker no longer holds the job (it was swept)."""
    result = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "running", Job.locked_by == worker_id)
        .values(status="succeeded", last_error=None, locked_at=None, locked_by=None)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def _next_state(attempts: int) -> str:
    return "failed" if attempts > max_retries() else "queued"


async def fail(session: AsyncSession, job_id: uuid.UUID, worker_id: str, error: str) -> str | None:
    """Record a failed attempt: requeue while retries remain, else `failed`.
    Returns the new status, or None when this worker no longer holds the job."""
    job = (
        await session.execute(
            select(Job)
            .where(Job.id == job_id, Job.status == "running", Job.locked_by == worker_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = _next_state(job.attempts)
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    await session.flush()
    return job.status


async def sweep(
    session: AsyncSession, lease_seconds: float, now: dt.datetime | None = None
) -> dict[str, int]:
    """Recover jobs whose worker died: a running job past its lease counts as a failed attempt.
    Returns how many were requeued and how many were failed for good.

    The lease length is the caller's to give: no rule fixes it yet (see docs/jobs.md)."""
    now = now or dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(seconds=lease_seconds)
    stale = (
        (
            await session.execute(
                select(Job)
                .where(Job.status == "running", Job.locked_at < cutoff)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    counts = {"requeued": 0, "failed": 0}
    for job in stale:
        job.status = _next_state(job.attempts)
        job.last_error = LEASE_EXPIRED
        job.locked_at = None
        job.locked_by = None
        counts["requeued" if job.status == "queued" else "failed"] += 1
    await session.flush()
    return counts


__all__ = [
    "LEASE_EXPIRED",
    "Claimed",
    "claim_next",
    "complete",
    "enqueue",
    "fail",
    "max_retries",
    "sweep",
]
