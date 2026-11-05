# Job runner

`services/jobs/` runs work as database rows (NFR-7, OPS-1.1). No in-memory queue: a crash loses nothing.

| Piece | Behaviour |
|---|---|
| `enqueue` | Idempotent per (`run_id`, `job_type`, `input_hash`). A repeat returns the existing job in any state and never runs it twice. |
| `claim_next` | `SELECT … FOR UPDATE SKIP LOCKED`, oldest first. Concurrent workers pass over each other's rows, so one job never has two holders. Sets `running`, `attempts + 1`, `locked_at`, `locked_by`. |
| `run_one` | Commits the claim, then runs the handler, then records the result in a second transaction. A crash in between leaves a `running` row with a lease. |
| `fail` | Requeues while retries remain, otherwise `failed` (visible, with `last_error`). Runs at most `1 + max_job_retries` times (`OPS-1.1`). |
| `sweep` | A `running` job past the lease counts as a failed attempt (`LeaseExpired`). Call `sweep_on_startup` when a worker starts. |
| Stale worker | `complete` and `fail` only act while `locked_by` still matches, so a worker whose job was swept cannot overwrite the new holder. |

**Handler contract.** After a crash a handler runs again from its start, so it must be idempotent: write claims through the claim store's identities (an upsert keyed by claim id), not blind inserts. The runner guarantees one *job*; the handler guarantees one *result*.

**Stored errors.** `last_error` is the error class name only. Messages can carry source values (SEC-1.3).

**Constants.** `max_job_retries` (OPS-1.1) and `job_lease_seconds` (OPS-1.2, 600, approved 2026-11-05) come from `rules_constants.yaml`. `lease_seconds()` reads the second. The runner and sweeper still take it as an argument with no default, so a worker must pass the same value to both.

**Not built here.** The API does not start a worker or call the sweeper: no agent exists to run yet. The first agent PR wires `sweep_on_startup` into a worker entry point. A healthy handler that runs longer than the lease is stopped by `asyncio.wait_for` and counted as a failed attempt, so size the lease to the slowest legitimate job.

Tests: `tests/test_jobs.py` (includes `test_resume_idempotent` and a four-worker exactly-once test).
