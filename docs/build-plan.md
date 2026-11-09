# Build plan

Version 1.0 · 2026-11-04 · draft for review · Phase 1, step 7
Spec: `spec.md` v1.1 · Rules: `rules.md` v1.2 · Agent rules: `AGENTS.md` v1.0. Branch-by-branch detail: `branching-and-environments.md`.

**Staging rule (identical in both documents):** merging into `develop` deploys `staging`. `main` is release only and deploys nothing. There is exactly one deployed environment, `staging`, holding fixture data only.

## Principle
Build the thing that can tell you whether you are right before the thing you want to be right: fixture and answer key, claim store and verifier come before any model call. Deterministic analysis before model analysis. Phases 1 and 2 need no model at all.

## Repo layout
```
AGENTS.md  README.md  Makefile  docker-compose.yml  pyproject.toml  uv.lock  .env.example
rules_constants.yaml  .pre-commit-config.yaml  .secrets.baseline  .gitattributes
.github/workflows/    ci.yml  staging-deploy.yml  release.yml
docs/                 spec.md rules.md build-plan.md branching-and-environments.md input-contract.md runbook.md  <component>.md  adr/
services/             api/  analyzers/  verifier/  sandbox/  models/  jobs/
apps/review/          CLI first; React UI after the pilot
fixtures/             legacy-app/  answer-key/  recorded-model-outputs/
evals/                datasets/  results/YYYY-MM-DD-<run-id>/
scripts/              policy_check.py  sample_claims.py  ...
```

## Makefile targets
`install up down migrate seed lint test eval eval-smoke build audit policy-check generate-types`. Targets not built yet exit non-zero on purpose instead of passing as stubs.

## CI jobs (exact names; added to rulesets only when the job exists)
`Lint (Backend)`, `Lint (Frontend)`, `Test (Backend)`, `Test (Frontend)`, `Secret Scan`, `Dependency Audit`, `Container Build` (all in the scaffold PR; Frontend jobs are no-ops until the UI exists, so they are added to the ruleset later), `Policy Integrity Check`, `Migration Check`, `Eval Smoke`, `API Types`, `Sandbox Safety`, `Fixture Answer Key`.

## Phase 1. Foundation
**Goal:** everything needed to measure correctness before any analyzer exists.
**Validation:** `make lint && make test && make eval-smoke && make policy-check`
1. Repo scaffold with CI (7 jobs green).
2. Staging pipeline: build images, push to GHCR, Render deploy hook, wait for health.
3. Rules integrity check: constants against passages, SHA-256 lock on `rules.md`.
4. DB schema: claims, evidence, snapshots, review items, decisions, audit log, jobs, model calls; Alembic 0001; Migration Check.
5. Source ingest: GitHub URL or local path to pinned revision, read-only, limits, secret and PII scan.
6. Evidence resolver: every reference kind to bytes, excerpt hashes, encoding and line endings.
7. Verifier V-1 to V-10 with 50 bad and 50 good claims; 95% branch coverage.
8. Fixture app with 35 traps and hand-written answer key; drift check.
9. Eval harness: precision, recall, Wilson intervals, results folder.
10. Grep/regex baseline finder.

## Phase 2. Deterministic agents
**Validation:** `make eval-smoke` meets the Phase 2 targets in spec §19 on the fixture.
1. Job runner (`SKIP LOCKED`, sweeper, resume, idempotent).
2. Discovery agent.
3. Code Analysis agent (tree-sitter: routes, swallowed errors, dead code, unresolved requires, call graph, async flow; value-level data flow not yet).
4. Data agent (schema, ER data, SQL lineage; PII in sample data by pattern).
5. Review CLI with Markdown export (accept, edit, reject; audit log). Built: queue, show, accept, reject, edit, history, export ([docs/review.md](review.md)). REV-3 coverage and accuracy reports with random sampling are built too.

## Phase 3. Model-assisted agents
**Gate:** benchmark the local model on the operator's laptop first. If speed or quality is unusable, stop and report before building on it.
1. Model client (local only), FakeClient, recorded outputs.
2. Business Rule agent.
3. Verification wiring: retry, then demote to Unknown.
4. Diagram agent (Mermaid from stored data).
5. Documentation agent.
6. Sandbox and Test agent (two-stage dependency fetch).
7. Modernization agent (accepted claims only).

## Phase 4. Pilot
1. Choose the pilot (permissive licence, no install scripts or native builds) and slice it so total claims are at most 400.
2. Manual baseline: the operator does one manual analysis of the slice with a stopwatch, before the agents run.
3. Pilot run, review session, accuracy sample, characterization test report, time-saved number.

## Phase 5. Hardening and release
1. All 35 fixture traps end to end.
2. Runbook, README with eval table.
3. Live eval on the operator's laptop; invalid runs discarded; results committed with model and prompt hashes.
4. React review UI only if the pilot shows the CLI is the bottleneck.
5. Release `v1.0.0`; notes state any unmet gate.

## Deployment architecture
Local `docker compose`: db, api, jobs worker, sandbox runner, local model endpoint (host). Render `staging`: api and Postgres, fixture only, replays recorded outputs, no model, no sandbox (cannot run there). Region: one, used for every Render resource. External setup guides are written after the PR that makes them possible merges.

## Risk register
| Risk | Effect | Mitigation |
|---|---|---|
| 7B to 8B local model is too weak | many Unknown claims, low coverage | Phase 3 benchmark gate; report honestly |
| Review load exceeds 4 h a week | pilot stalls | claim cap of 400 (REV-3.5) |
| Pilot app needs install scripts | not testable | choose a pilot without them |
| Free Render Postgres expires after 30 days | staging DB lost | fixture only; reseed |
| Fixture answer key not truly reviewed | evals meaningless | key stays `needs_review` until Aditya says reviewed |
| Dynamic JS defeats static analysis | Unknown claims | correct behavior; counted in coverage |
| Scope: nine agents | late delivery | Diagram and Modernization may ship simple; Verification never cut |

## Open items
Pilot app; which slice; local model benchmark result; whether the React UI is built.
