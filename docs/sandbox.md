# Sandbox and Test agent (FR-8, TST-1.x): part 6a

Status: built for Phase 3 item 6, part 6a. **Nothing here executes legacy code.** The Docker
runner, the CI job that tries to break out, and the dependency-fetch stage are part 6b.

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
- **Isolation is unproven.** The container that runs this has the Docker client but no daemon.
  6b adds a `Sandbox Safety` CI job (network call, write to the mount, host file read, fork bomb,
  memory bomb, timeout) that must see each fail.

Constants not in `rules_constants.yaml` (mine): process cap 256, tmpfs 64 MB, at most 5 inputs per
function, 500 characters per input.
