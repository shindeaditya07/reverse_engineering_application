# ADR-0006: Synchronous SQLAlchemy with psycopg 3

**Status:** accepted (2026-11-04)
**Relates to:** ADR-0003 (Postgres claim store), AGENTS §8

## Context
The pipeline is batch work run by a job runner, not a high-concurrency request path. The API
mostly reads claims for the review UI. The claim store depends on Postgres triggers and deferred
constraints, which behave the same under sync and async drivers.

## Decision
Use synchronous SQLAlchemy 2 Core with psycopg 3 and a small pool (5, overflow 5, pre-ping,
recycle 30 min). FastAPI endpoints that touch the database are plain `def` so they run in the
thread pool. Schema is defined in `services/api/db/tables.py` and changed only through Alembic;
a test compares the metadata to the migrated database.

## Rejected
- **Async SQLAlchemy / asyncpg:** more moving parts, no throughput need, harder to test triggers.
- **ORM sessions:** claims are append-only rows; Core keeps writes explicit.

## Consequences
If review-UI concurrency outgrows the thread pool, revisit; the table layer does not change.
