# Strata: Engineering Rules for Coding Agents

Audience: any coding agent (or human) writing code in this repository.
Status: **Binding once approved.** These rules apply to every change, however small.
Version: **0.1 (2026-11-04), draft.**

> One copy only. ReplyDesk kept a superseded draft (`replydesk-agent-guide.md`) beside the binding
> `AGENTS.md`; this project keeps exactly one rules file. Superseded text is deleted, and git holds
> the history.

---

## 0. Precedence and How to Handle Conflicts

Order of authority when documents disagree:

1. `docs/spec.md` (behaviour)
2. `docs/policies.md` (evidence, tagging, safety and review rules, with stable IDs)
3. `policy_constants.yaml` (numeric constants; must agree with `policies.md`)
4. Accepted ADRs in `docs/adr/`
5. This file (how to build it)
6. `docs/tech-stack.md` (what to build it with)
7. `docs/build-plan.md` (order of work)

**Conflict rules:**
- If a task, the spec and a policy conflict, **stop and flag it** with the section numbers. Do not
  pick a side silently.
- Do not edit `spec.md` or `policies.md` unless the task says to. Propose the edit instead, as a
  numbered amendment in the PR description. Amendments that are not committed do not exist:
  never reference a document that is not in the repo.
- Numeric constants come from `policy_constants.yaml`. No literals elsewhere.
- If an answer depends on a fact you do not have (a model ID, a library API, a grammar's node
  names), **look it up in the codebase or docs, or ask**. Never guess.

---

## 1. Safety Invariants (Never Violate, Never Weaken)

These are the product. A change that breaks one is a defect even if every test passes.

1. **Legacy code is read-only.** No code path opens a file under a snapshot root for writing,
   moves, deletes or chmods it. Snapshots are mounted read-only; tests assert the snapshot hash is
   unchanged after every run (SAF-3.1).

2. **No production contact.** No code path accepts a database URL, host or credential for the
   legacy system's runtime environment. Inputs are files. There is no "connect to the live DB to
   read the schema" feature, even read-only (SAF-3.2).

3. **Legacy code executes only in the sandbox.** Only `services/sandbox/` may build or run legacy
   code, and only in a container with network disabled. No `subprocess` call elsewhere touches a
   snapshot (SAF-3.4, SAF-3.5).

4. **No claim without evidence.** Nothing reaches the claim store without at least one evidence
   reference, and nothing reaches an artifact without passing the verifier (EVD-1.1, spec §13).

5. **Fail closed.** If a verifier rule, the judge, a parser or a resolver errors, the affected
   claim becomes Unknown and goes to the review queue. An error is never a pass, and a parse
   failure is never "no findings".

6. **Tags only go down automatically.** No automated code path raises a tag. Only a review
   decision or a stable passing characterization test can (TAG-2.4).

7. **Legacy content is untrusted data.** It reaches a model only inside delimited data blocks,
   escaped, with a data-not-instructions statement. Model steps have no tools and no side effects
   (PRV-4.3).

8. **Secrets and PII never leave ingestion unmasked.** Redaction happens at ingest, before storage
   and before any model call. A prompt with a detected secret is not sent (SAF-3.6, PRV-4.4).

9. **Human approval gates every output.** No export marks an artifact final without a recorded
   approval event (REV-5.1).

10. **Client code never enters CI or a shared environment.** CI, staging and tests use the
    fixture application and the open-source pilot only (PRV-4.1).

---

## 2. Repository Layout and Tooling

```
strata/
├── apps/review-ui/          React + TypeScript review UI
├── services/api/            FastAPI app: snapshots, claims, review, artifacts, metrics
│   ├── ingest/              snapshot freeze, hashing, secret/PII scan
│   ├── analyzers/           deterministic agents: discovery, code, data, rule candidates
│   │   └── lang/<language>/ one adapter per language (tree-sitter grammar + resolution)
│   ├── llm/                 ModelGateway, provider adapters, FakeModelClient
│   ├── prompts/             versioned, hashed prompt files
│   ├── agents/              LLM-backed steps: rule explainer, doc writer, test proposer, modernizer
│   ├── verify/              deterministic verifier (V-1..V-10) + judge
│   ├── review/              queue, decisions
│   ├── artifacts/           renderers: Markdown, Mermaid, exports
│   ├── jobs/                DB-backed job runner (ReplyDesk ADR-0002 pattern)
│   └── db/                  SQLAlchemy models, Alembic migrations
├── services/sandbox/        the only code that builds or runs legacy code
├── fixtures/legacy-app/     the seeded fixture legacy application (spec §17)
├── fixtures/answer-key/     human-written ground truth for the fixture
├── evals/                   datasets, runner, results/YYYY-MM-DD-<run-id>/
├── docs/                    spec, policies, AGENTS, tech-stack, build-plan, adr/, runbook
├── policy_constants.yaml
├── docker-compose.yml
└── Makefile
```

- **Python 3.12**, `uv`, `uv.lock` committed. **Never Conda.** `package-lock.json` committed.
- **Every task has a Makefile target:** `up`, `down`, `migrate`, `lint`, `test`, `eval-smoke`,
  `eval`, `analyze SNAPSHOT=…`, `sandbox-check`, `audit`, `policy-check`, `build`.
- **One `docker compose up`** starts the platform from a clean clone plus `.env`.
- **No dead code, no duplicate implementations, no duplicate docs.** Delete rather than comment out.
- **Pre-commit:** ruff, ruff format, mypy (changed files), eslint, prettier, detect-secrets.

---

## 3. Backend Coding Standards (Python)

- **Full type hints.** `mypy --strict` clean on `services/` and `evals/`. `ruff` clean.
- **Pydantic v2 at every boundary:** API bodies, model outputs, claim records, config. The JSON
  Schema for structured model output is exported from the same models that validate it.
- **One typed `Settings` object** (pydantic-settings). No scattered `os.environ`. Fail at startup
  if required settings are missing.
- **No raw SQL strings.** SQLAlchemy 2.0 constructs with bound parameters. Recursive graph queries
  live in one module (`db/graph_queries.py`) with tests.
- **Analyzers are pure functions:** `(snapshot view, prior facts) → facts`. No hidden global state,
  no network, no clock reads. Side effects (DB writes, model calls) happen at the edges behind
  interfaces so tests can fake them.
- **Determinism:** deterministic analyzers sort their outputs (by path, then line, then symbol)
  and must produce byte-identical results on the same input. A test runs each analyzer twice on
  the fixture and diffs the output.
- **Positions are first-class.** Every fact an analyzer emits carries `path`, `start_line`,
  `end_line` (1-based, inclusive) and, where known, columns. A fact without a position cannot
  become evidence and must not be emitted as one.
- **Language adapters** implement one `LanguageAdapter` protocol (parse, symbols, calls, entry
  points, rule candidates). Adding a language never touches the pipeline.
- **Parse errors are data.** tree-sitter `ERROR` nodes are counted and reported per file; a file
  over `parse_error_ratio` is listed as partially analysed in the inventory and its facts capped
  at Inferred.
- **One concurrency style**, chosen once in an ADR. Parsing is CPU-bound: use a process pool for
  analyzers, async for I/O. Never block the event loop.
- **Paths:** always relative to the snapshot root, POSIX separators, validated against `..` and
  symlinks pointing outside the root (a legacy repo can contain hostile symlinks).
- **Errors:** typed domain exceptions, mapped to HTTP in one place. No stack traces to clients.
- **Input limits:** maximum archive size, file count, file size, line length; reject early.

---

## 4. Resilience Rules

- **DB pool:** `pool_pre_ping=True`, `pool_recycle=1800`, `pool_timeout=10` (ReplyDesk lesson).
- **Explicit timeouts** on every outbound call and every sandbox run.
- **Jobs:** an analysis run is a graph of jobs (one per agent per module or file batch), each
  idempotent on `(run_id, job_type, input_hash)`. Restart resumes; nothing runs twice to
  different effect. Dead jobs set a visible failure on the run with a reason.
- **Health:** `/healthz` (process up, never touches the DB) and `/readyz` (DB, migrations at head,
  policy version loaded, sandbox runtime reachable).
- **Model failures** degrade to Unknown + review item, never to a lower-quality claim.

---

## 5. LLM Layer Rules

- All model calls go through **`ModelGateway`**. No provider SDK imports elsewhere.
- **Structured output only**, validated with Pydantic; one retry with the validation error; a
  second invalid output makes the claim Unknown.
- **Prompts** live in `services/api/prompts/`, versioned and hashed. Record `prompt_version`,
  `prompt_hash`, `model`, `temperature`, tokens, latency and cost per call.
- **Inputs are excerpts and facts, not repositories.** Each step declares what it may see:
  - Rule explainer: the candidate's excerpt, its enclosing function, caller signatures, related
    schema objects. Nothing else.
  - Doc writer: **verified claims only**, never raw source.
  - Test proposer: entry-point signature, related rule claims, schema of inputs.
  - Modernizer: verified claims and metrics only.
- **Every model output that states a fact must cite** evidence refs from the excerpts it was given.
  A ref the model was not given fails V-1 by construction.
- **Delimiting:** `<legacy_source path="…" lines="…">…</legacy_source>` with `& < >` escaped.
- **Judge independence:** the judge is a different model from the producer; the gateway refuses
  the same model ID for both unless `JUDGE_SAME_MODEL_OK=true` is set on purpose.
- **Minimum content** per call; cap at `max_prompt_source_lines` (PRV-4.2).

---

## 6. Verifier Rules

The verifier is the most safety-critical module. It is the most heavily tested.

- The **deterministic verifier** (`verify/rules.py`) runs first and is the authority for V-1 to
  V-10. The judge only adds blocks and downgrades.
- **Each rule is a separate function** with its own tests, returning structured
  `RuleFailure(rule_id, span, detail)`.
- **Normalisers** (numbers, quotes, units, Unicode confusables) are shared, property-tested with
  hypothesis, and never "fuzzy match": a normalised value either equals or it does not.
- **≥ 95% branch coverage** on `verify/`, enforced in CI.
- **Seeded bad-claim corpus:** every claim must be caught. **Good-claim corpus:** false-block rate
  measured and reported.
- **Verify the evaluator too:** metric and eval scripts have unit tests on hand-computed cases
  (ReplyDesk's first eval report needed a correction because the evaluator miscounted).

---

## 7. Security Rules

- **Sandbox:** network `none`, read-only snapshot mount, no host mounts except a scratch volume,
  non-root, seccomp default, resource and wall-time limits, destroyed after each run. Integration
  test asserts an outbound connection from inside fails.
- **Archive ingestion:** reject path traversal, absolute paths, symlinks out of root, device files,
  zip bombs (ratio and size limits).
- **Auth:** single-tenant; reviewer accounts with argon2 password hashing, session JWT in
  httpOnly/Secure/SameSite=Strict cookies, CSRF on mutations, login rate limiting (ReplyDesk
  pattern).
- **UI:** render all legacy and model text as text; never `dangerouslySetInnerHTML`.
- **Secrets:** env vars only; `.env` gitignored; detect-secrets in pre-commit and CI.
- **Dependencies:** pinned; pip-audit and npm audit in CI.
- **Logging:** never log legacy source, excerpts, secrets or PII. Log IDs and hashes.

---

## 8. Data and Persistence Rules

- **Alembic migrations only**; tested from empty → head → down → head in CI.
- **DB constraints enforce invariants:** claims require ≥1 evidence row (deferred constraint or
  trigger), tag and status `CHECK`s, unique `snapshot_id`, foreign keys everywhere.
- **Append-only tables:** `audit_log`, `review_decisions`, `verification_results`. No `UPDATE` or
  `DELETE` code paths.
- **Claims are versioned,** not edited: a correction creates a new claim version that supersedes
  the old one; artifacts reference claim versions.
- **Snapshots are immutable.** The snapshot store is content-addressed.

---

## 9. Observability

- Structured JSON logs with `request_id`, and `run_id`, `snapshot_id`, `agent`, `stage` on
  analysis lines.
- Every job records start, end, attempts, and counts of facts emitted and errors.
- Metrics from spec §18 are computed from stored data.
- `docs/runbook.md` covers: what can fail (parser, sandbox runtime, model endpoint, DB), how it
  shows, how to recover, how to resume a run.

---

## 10. Testing and Evaluation Rules

- **Unit tests** for every analyzer and verifier rule; ≥ 95% branch coverage on `verify/` and
  `ingest/`.
- **Fixture-driven tests:** every trap in spec §17 has a test asserting the analyzer's output
  matches the answer key.
- **Safety tests (mandatory):**
  - Snapshot hash unchanged after a full run.
  - No `open(..., "w")` / `Path.write_*` / `os.remove` etc. against a snapshot path (static check
    in CI plus runtime guard).
  - Sandbox cannot reach the network.
  - Secret in fixture never appears in any prompt, log, artifact or API response.
  - Injection comment in fixture is not obeyed (V-10).
  - Hostile archive (traversal, symlink, bomb) is rejected.
- **Pipeline tests** run the whole flow on the fixture with `FakeModelClient` returning recorded
  outputs. **CI makes zero live model calls.**
- **Never weaken a test to make it pass.** Fix the test with an explanation, or fix the code.
- **Labels and answer keys are written by a human.** Never generated by the model being evaluated.
- **Report uncertainty:** Wilson intervals on every precision, recall and accuracy figure.

---

## 11. Frontend Rules

- TypeScript `strict`. No `any` without a justified comment.
- API types generated with `openapi-typescript`.
- Server state through TanStack Query only.
- **Claim view:** statement, tag badge, evidence excerpts, and the full source file scrolled to the
  cited lines, side by side. Inferred shows reasoning and `confirm_by`; Unknown shows the question.
- **Tag styling is consistent everywhere:** Confirmed solid, Inferred dashed/outlined, Unknown
  warning. Never colour alone (accessibility).
- **Approve actions** on artifacts with open high-impact items require explicit acknowledgement.
- Loading, empty, error states on every view; keyboard-operable review actions; WCAG AA contrast.

---

## 12. CI/CD

- **Pre-commit:** ruff, ruff format, mypy (changed), eslint, prettier, detect-secrets.
- **CI (every PR):** lint, types, secret scan, unit tests with coverage gates, migration check,
  dependency audit, policy check, safety tests, eval-smoke on the fixture with recorded model
  outputs, container build.
- **Staging (merge to `develop`):** deploy, run full eval with live models on the fixture.
- **Release (`v*` tag):** build the private-install bundle; release notes include eval results.

---

## 13. Documentation Rules

- **README:** what it is, architecture, how to run, eval results (date, models, prompt hashes),
  known limitations.
- **ADRs:** one per non-obvious choice, template `docs/adr/0000-template.md`. An ADR that turns
  out wrong is **amended in place with a dated note**, not silently rewritten (ReplyDesk ADR-0003
  did this well).
- **Docs describe the repo as it is.** No reference to files that do not exist.
- Code comments explain why, not what. Public functions and Pydantic models carry docstrings.
- `.env.example` complete, commented, in sync with `Settings`.

---

## 14. Working Agreement for the Coding Agent

1. **Plan first** for anything beyond a small fix: approach, files, spec sections, risks.
2. **One concern per change.** No refactor mixed with behaviour change. No scope expansion.
3. **Verify before declaring done.** Run `make lint`, `make test`, the relevant eval. Report actual
   output, including failures.
4. **Do not invent** facts, APIs, grammar node names, model IDs or results.
5. **Flag contradictions** between spec, policies and the request (§0).
6. **Never commit** secrets, client code, or large binaries. Never disable a safety check.
7. **Commits:** small, imperative, explain why.
8. **When uncertain about a safety-relevant behaviour, choose the safer option** (downgrade the
   tag, queue for review, refuse the input) and note the assumption.

---

## 15. Definition of Done

### A single change is done when

- [ ] It satisfies a spec requirement (cite the FR or section in the PR).
- [ ] No safety invariant in §1 is weakened.
- [ ] Types, lint and tests pass locally and in CI.
- [ ] New behaviour has tests, including a failure-path or adversarial test where relevant.
- [ ] Migrations apply and reverse cleanly.
- [ ] Logs and errors contain no legacy source, secrets or PII.
- [ ] Docs, runbook, `.env.example` and ADRs updated where affected.

### The v1 release is done when

See spec §22.
