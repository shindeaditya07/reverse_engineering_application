# Worker

`python -m services.worker` runs the job queue ([jobs.md](jobs.md)) and stores what the agents find through the claim writer ([claims.md](claims.md)).

| Command | Does |
|---|---|
| `work` | Sweeps jobs a dead worker left running (lease from OPS-1.2), runs queued jobs until the queue is empty, then exits. |
| `analyze <source> [--ref REF]` | Pins a GitHub URL or local path, stores the snapshot, queues a Discovery job for a new run, works it, and prints counts: jobs, claims by status, review queue by reason. Never prints claim text. |

`Point `analyze` at your own database, **never the one the tests use**. It commits claims, which can never be deleted (CLM-1.5), and the tests assume an empty claim store and a fixture snapshot that is not yet ingested; after an `analyze` of the fixture they fail. (I hit this: I reset my local test database.)

`DATABASE_URL`, `SNAPSHOT_DIR` and `GITHUB_TOKEN` come from Settings, like `python -m services.ingest`. The token stays on this machine (SEC-1.7).

## How a job gets its input

`jobs.snapshot_id` (migration 0005) names the snapshot. The handler rebuilds the evidence reader from the store: the file list and hashes from `snapshot_files`, the bytes from `<SNAPSHOT_DIR>/<revision>`. Every read re-hashes the file, so a pinned copy changed since ingest fails the job with `Unresolved` instead of producing claims about other bytes (SEC-1.1). The job's input hash is the snapshot revision.

## Guarantees and their tests (`tests/test_worker.py`)

- A crash inside the handler rolls back everything it wrote; the retry writes everything, once. The job ends `succeeded` with `attempts = 2`.
- A worker killed after claiming the job: the sweeper requeues it after the lease, a second worker finishes it, and re-queueing the same input adds nothing (`test_a_killed_worker_is_swept_and_the_job_finishes_without_duplicates`).
- A changed snapshot fails the job visibly after 1 + 3 attempts, with no claims stored.

## What it does not do

- **It exits when the queue is empty.** There is no polling loop: a poll interval would be a number no rule fixes. A supervisor (cron, a shell loop, later the API) calls `work` again. Say if you want a long-running mode and what interval.
- **Discovery only.** Code Analysis, the Data agent and the later agents add handlers; the pipeline order (Discovery before Code Analysis) is not enforced here yet.
- **`analyze` is not covered by an automated test**, because it commits claims, which can never be deleted. Its parts are tested separately, and I ran it once by hand (see the PR).
- A job whose snapshot is missing fails like any other error and burns its retries; it cannot succeed on retry.
