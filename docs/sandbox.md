# Sandbox and Test agent (FR-8, TST-1.x): parts 6a and 6b

Status: 6a (testability, inputs, command, keep/drop) and 6b (Docker runner, Sandbox Safety job) are
built. Still not built: the dependency-fetch stage, running generated tests to fill in `passed`,
storing observations as claims, and a worker job (see the end).

## What 6a does
1. **Testability** (`testable.py`, deterministic). A module is a test target only if it and every
   file it requires by a relative path load nothing but snapshot files and pure Node built-ins
   (`assert buffer events path querystring string_decoder url util`). Everything else is refused
   with a fixed-sentence reason and stored as an Unknown claim `sb:untestable:<path>` (CLM-1.7):
   a package (TST-1.6), `fs`/`net`/`https`/`os`/... (TST-1.2, SEC-1.2), a computed `require`, ES
   module syntax, a missing file. `sb:app:no-lockfile` states that no lockfile exists when a module
   needed a package. Functions with default, rest, destructured or async parameters, or over 40
   lines, are counted and skipped.
2. **Inputs** (`propose.py`). The local model sees one function inside an UNTRUSTED block (SEC-2.2)
   and returns argument lists only, never expected outputs (TST-1.1). Right arity, plain JSON, no
   NaN, at most 500 characters each, unique, at most 5. No retry: nothing usable means no test,
   reported.
3. **Sandbox command** (`spec.py`). `docker run` with `--network none`, read-only root, all
   capabilities dropped, no new privileges, user 65534, 2 CPUs, 2048 MB with no swap, 256
   processes, a `noexec` 64 MB tmpfs, the snapshot and our harness mounted read-only, no
   environment, no other mounts. The job travels on stdin. `assert_safe` re-checks the finished
   command and refuses anything looser, including the Docker socket, extra mounts and any unpinned
   image. The 300 s wall-clock kill belongs to the runner (6b).
4. **Harness** (`harness.js`, ours). Calls the function twice per input on fresh copies and prints
   one JSON line. A legacy `console.log` goes to stderr. `parse_output` accepts exactly that line
   and fails closed on anything else (NFR-2).
5. **Keep or drop** (`keep.py`). Kept: a returned value or a thrown error class. Dropped with a
   fixed reason: timeout, memory, crash, malformed reply, async, not storable as JSON, different
   result on two identical calls, or a test text holding a secret or personal data (SEC-1.3,
   SEC-1.5). A limit hit is a failure, never a pass (TST-1.3). `render_test` writes a `node:test`
   file that asserts exactly what was observed, stamped with snapshot, run and date (OUT-1.2).
6. **Report** (TST-1.5): tests kept, passed and dropped, each drop with its reason. `passed` shows
   "not run" until 6b runs the generated file against the original.

## On the fixture
13 functions in 7 modules qualify (`python -m services.sandbox`). They are formatting, totals,
pricing and validation helpers. Orders, payments, stock and every database path are refused, so
a passing suite here says little about the app as a whole.

## Not done, on purpose
- **No claims from observations yet.** The verifier says a test confirms or says nothing (V-5), and
  CLM-1.8 needs a reference to the test. Evidence references today are file ranges only, so a
  "test run" reference type is a schema and rules decision for 6b.
- **No worker job and no recorded model run.** The proposal prompt has never met the real model;
  tests use the fake client.
- **No dependency fetch.** The fixture has no lockfile, so the stage could not run on it.
- **Isolation is proven in 6b**, not 6a (see below).

Constants not in `rules_constants.yaml` (mine): process cap 256, tmpfs 64 MB, at most 5 inputs per
function, 500 characters per input.

## Part 6b: the Docker runner and the proof
`docker.py` `DockerRunner(snapshot_dir)` is the only code that executes legacy code. It builds the
command with `docker_command` (re-checked by `assert_safe`), writes the job to stdin, reads stdout
up to 256 KB, discards stderr (nothing the legacy code prints is kept), and kills the container
by name at 300 s. Statuses: `ok`, `timeout`, `memory` (exit 137 that we did not cause), `crash`,
`bad_output`. Each is a failure except `ok`. The docker client is reaped as well, because it can
outlive its container. The pinned image is `DEFAULT_IMAGE` in `spec.py` (node 22 slim, by digest).

`tests/test_sandbox_docker.py` runs 13 hostile probes in a real container, calling the runner
directly so they hold even if the testability check were bypassed:
runs as 65534 with no capabilities and no-new-privileges; none of the host's environment gets in;
no network, not even loopback; `/app`, `/` and the harness are read-only; `/tmp` cannot execute; no
Docker socket and only expected mounts; a fork bomb stops under the process cap; a 4 GB allocation
is killed and reported as `memory`; an endless loop is killed at the deadline and leaves no
container; a 400 KB reply is `bad_output`; a path outside the snapshot is refused.

`make sandbox-safety` pulls the pinned image and runs them with `REQUIRE_DOCKER=1`, where a missing
Docker or image is a failure. CI runs it as the **Sandbox Safety** job. Without `REQUIRE_DOCKER`,
the tests skip when Docker or the image is missing, so `make test` still works without Docker.

Snapshot files must be readable by user 65534. The pinned copy is mode 444/555, so they are.

## Still not done
- **Dependency-fetch stage (TST-1.6).** The fixture has no lockfile, so it could not be exercised.
- **`passed` count.** Running the generated test file against the original needs a third mount,
  which `assert_safe` refuses. It needs a deliberate change to the allowed mounts.
- **Observations as claims.** Still blocked by V-5 and the file-range-only evidence references.
- **Worker job and recorded model run.**
- Add `Sandbox Safety` to the required checks after it has run green once.
