# Worker

`python -m services.worker` runs the job queue ([jobs.md](jobs.md)) and stores what the agents find through the claim writer ([claims.md](claims.md)).

| Command | Does |
|---|---|
| `work` | Sweeps jobs a dead worker left running (lease from OPS-1.2), runs queued jobs until the queue is empty, then exits. |
| `analyze <source> [--ref REF]` | Pins a GitHub URL or local path, stores the snapshot, queues one job per agent (Discovery, Code Analysis, Data) for a new run, works them, and prints counts: jobs, the job types that failed, claims by status, review queue by reason. Never prints claim text. |

Point `analyze` at your own database, **never the one the tests use**. It commits claims, which can never be deleted (CLM-1.5), and the tests assume an empty claim store and a fixture snapshot that is not yet ingested; after an `analyze` of the fixture they fail. (I hit this: I reset my local test database.)

`DATABASE_URL`, `SNAPSHOT_DIR` and `GITHUB_TOKEN` come from Settings, like `python -m services.ingest`. The token stays on this machine (SEC-1.7).

## How a job gets its input

`jobs.snapshot_id` (migration 0005) names the snapshot. The handler rebuilds the evidence reader from the store: the file list and hashes from `snapshot_files`, the bytes from `<SNAPSHOT_DIR>/<revision>`. Every read re-hashes the file, so a pinned copy changed since ingest fails the job with `Unresolved` instead of producing claims about other bytes (SEC-1.1). The job's input hash is the snapshot revision.

## The agent jobs

| Job type | Agent | Claim keys |
|---|---|---|
| `discovery` | [Discovery](discovery.md) | `disc:` |
| `code_analysis` | [Code Analysis](codeanalysis.md) | `ca:` |
| `data` | [Data](data.md) | `data:` |

`enqueue_agents` queues all three for a (run, snapshot); queueing the same run again adds nothing. Each handler is the same few lines (`_agent_handler`): rebuild the reader, run the agent, store through the claim writer, one transaction. The three read only the snapshot, never each other's claims, so they run independently and in any order. The spec draws Discovery first and the other two after it; that order is **not** enforced because nothing depends on it.

One agent failing does not stop the others. Its job fails visibly after 1 + 3 attempts and `analyze` names it in `failed_job_types` and exits 1; the other agents' claims stay stored.

**One owner per finding.** Where two agents could report the same line, one owns it: the computed `require` in `services/orders_service.js` is Code Analysis's (an Unknown `dependency` claim), and Discovery does not report it.

## Guarantees and their tests (`tests/test_worker.py`, `tests/test_worker_agents.py`)

- A crash inside the handler rolls back everything it wrote; the retry writes everything, once. The job ends `succeeded` with `attempts = 2`.
- A worker killed after claiming the job: the sweeper requeues it after the lease, a second worker finishes it, and re-queueing the same input adds nothing (`test_a_killed_worker_is_swept_and_the_job_finishes_without_duplicates`).
- A changed snapshot fails the job visibly after 1 + 3 attempts, with no claims stored.
- Code Analysis and Data: each handler stores exactly what its agent finds and nothing from another agent; a crash stores nothing and the retry stores once; a failing Data job leaves the other two succeeded.

## What it does not do

- **It exits when the queue is empty.** There is no polling loop: a poll interval would be a number no rule fixes. A supervisor (cron, a shell loop, later the API) calls `work` again. Say if you want a long-running mode and what interval.
- **Three agents only.** The later agents (Business Rule, Diagram, Documentation, Test, Modernization) add handlers, and some of them do read earlier claims, so they will need an order.
- **`analyze` is not covered by an automated test**, because it commits claims, which can never be deleted. Its parts are tested separately, and I ran it by hand on a scratch database, never the test one (see the PR).
- A job whose snapshot is missing fails like any other error and burns its retries; it cannot succeed on retry.
