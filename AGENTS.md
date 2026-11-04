# AGENTS.md: binding rules for any coding agent on this repository

Version 1.0 · 2026-11-04 · draft for review · Phase 1, step 6 · goes at the **repo root** (not `docs/`), one copy only.

Each rule ends with `[enforced by: …]` naming the test, lint or CI job, or `[review]` when only a human can check it. Rule IDs (EVD, CLM, VER, REV, SEC, TST, OUT, OPS) are in `docs/rules.md`; requirement IDs (FR, NFR, V-) are in `docs/spec.md`.

## 0. Precedence and conflicts
1. Order: `spec.md`, then `rules.md`, then `rules_constants.yaml`, then this file, then `build-plan.md`.
2. If a task contradicts a higher document, **stop and flag it with section numbers**. Never resolve it silently. [review]
3. Do not edit `spec.md`, `rules.md` or `rules_constants.yaml` unless told to; propose the change instead. [enforced by: Policy Integrity Check, SHA lock on rules.md]
4. Never guess a fact (a number, a model name, a library version, a licence). Look it up or ask. [review]

## 1. Safety invariants (never weaken)
1. No path marks a claim accepted without a recorded human decision (REV-1.1). [enforced by: test_no_accept_without_decision]
2. Errors, timeouts and missing inputs block; they never pass (VER-1.3). [enforced by: verifier failure-path tests]
3. The deterministic verifier decides; a model can only demote (VER-1.1, VER-1.7). [enforced by: test_judge_cannot_promote]
4. A model alone never produces Confirmed (CLM-1.2, CLM-1.8). [enforced by: V-6]
5. The legacy repository is read-only and unchanged by a run (SEC-1.1). [enforced by: Source Unchanged test]
6. No code, excerpt or derived text goes to a hosted model (SEC-2.1). [enforced by: test_model_client_is_local_only, Secret Scan]
7. Legacy text is untrusted data in delimited blocks; the generating call has no tools and no network (SEC-2.2). [enforced by: injection tests on fixture case 33]
8. Secrets and tokens are never stored, logged or prompted (SEC-1.3, SEC-1.7). [enforced by: V-9, Secret Scan]
9. Every number comes from `rules_constants.yaml`. [enforced by: Policy Integrity Check, lint rule against numeric literals in `services/`]

## 2. Repo layout and tooling
- Python 3.12 with `uv`; never Conda. `uv.lock` and `package-lock.json` are committed. [enforced by: CI lockfile check]
- Layout: `services/api`, `services/analyzers`, `services/verifier`, `services/sandbox`, `apps/review` (CLI first, React later), `fixtures/`, `evals/`, `docs/`, `docs/adr/`, `scripts/`.
- Every task is a Makefile target: `install up down migrate seed lint test eval eval-smoke build audit policy-check generate-types`. One `docker compose up` works from a clean clone. [enforced by: Container Build]
- Pre-commit runs ruff, ruff-format, mypy on changed files, eslint, prettier, detect-secrets. [enforced by: pre-commit, Secret Scan]
- No dead code, no commented-out code. [enforced by: ruff]

## 3. Backend standards
- `mypy --strict` and ruff clean. [enforced by: Lint (Backend)]
- Pydantic v2 at every boundary; the JSON schema given to a model is exported from the same model that validates its reply. [enforced by: schema drift test]
- One typed `Settings` object; no scattered `os.environ`. [enforced by: ruff rule]
- SQLAlchemy 2.0; no raw SQL outside migrations. [enforced by: grep check in lint]
- Pure analysis stages; side effects behind interfaces. [review]
- UTC storage, `time_utils.py` for time, injected clock. [enforced by: ruff ban on `datetime.now`]
- Typed exceptions mapped in one handler; input size limits at the edge. [enforced by: API tests]

## 4. Resilience
- `pool_pre_ping=True`, `pool_recycle=1800`; API starts without the database and reports degraded. [enforced by: test_starts_without_db]
- `/healthz` (liveness, no DB) and `/readyz` (DB and migrations). [enforced by: API tests]
- DB-backed jobs with `SELECT … FOR UPDATE SKIP LOCKED` and a startup sweeper; retries and timeouts per OPS-1.1; a visible failed state. [enforced by: job runner tests]
- A run killed halfway resumes without duplicating claims (idempotent per run, job type and input hash). [enforced by: test_resume_idempotent]

## 5. Model layer
- One client interface; providers behind it; a `FakeClient` for tests. [enforced by: Test (Backend)]
- Only local or private endpoints are allowed by configuration; a hosted URL is rejected at startup. [enforced by: settings validator test]
- Every call is logged with run ID, tokens, latency, prompt hash and model name; never the source text. [enforced by: test_model_call_log_has_no_source]
- Temperature and seed pinned for evals; timeouts per OPS-1.1.
- Never hard-code a model name; it comes from settings. [enforced by: lint]

## 6. Verifier rules
- V-1 to V-10 live in one package, each check a pure function with a stable ID. [review]
- Fail closed (VER-1.3). V-10 only demotes (VER-1.7).
- At least 95% branch coverage, enforced. [enforced by: Test (Backend) coverage gate]
- The bad-claim corpus must be caught at 100%; a miss fails CI. [enforced by: Eval Smoke]

## 7. Security
- Ingest limits and path-escape checks for every source type (SEC-1.4). [enforced by: hostile-source tests]
- Secret and PII scan with redaction before storage (SEC-1.3, SEC-1.5). [enforced by: fixture case 29, 30]
- Sandbox: no network, read-only mount, resource limits, two-stage dependency fetch (TST-1.2, TST-1.3, TST-1.6). [enforced by: Sandbox Safety]
- GitHub tokens stay on the operator's machine. [enforced by: grep test for token fields in schema]
- Auth for the review UI or CLI: Argon2 password hash, httpOnly cookie for the UI. No tokens in `localStorage`. [enforced by: auth tests]
- Dependencies audited; no unpinned installs. [enforced by: Dependency Audit]

## 8. Data and persistence
- Append-only tables: `review_decisions`, `audit_log`; enforced by DB triggers or permissions, not by convention. [enforced by: migration test]
- Claims are versioned, never overwritten. [enforced by: test_claim_versions]
- Constraints per spec §10; migrations apply and reverse. [enforced by: Migration Check]
- A migration is never run at API startup; each PR that adds one says how to apply it. [review]
- DB tests share one database; filter by your own unique IDs, never count globally. [review]

## 9. Observability
- Structured logs with run ID. Logs carry no source text, no secrets, no personal data. [enforced by: log scrubber test]
- Metrics from spec §18 computed from the database. [enforced by: eval tests]
- `docs/runbook.md` says what can sleep, how to wake it, where logs are. [review]

## 10. Testing and evals
- CI never calls a live model (SEC-2.3). [enforced by: network-off test job]
- Fixture answer key is hand-written and reviewed by Aditya; the model under test never writes labels. Every key entry is marked `needs_review` until Aditya says it is reviewed. [review]
- Seeded bad-claim and good-claim corpora; Wilson intervals on every rate; bad numbers are reported too. [enforced by: eval report tests]
- A run with provider errors or timeouts is invalid, not a pass; count failures separately and stop after three in a row. [enforced by: eval runner tests]
- Adversarial tests are mandatory: prompt injection in comments, delimiter breaking, path traversal, symlink escape, oversized files, invalid encoding, CRLF, Unicode digits, non-English comments. [enforced by: fixture cases 31 to 33 and hostile-source tests]
- Never weaken a test, lint rule or safety check to get green. Never skip or quarantine a test. [review]

## 11. Frontend
(Applies when the React UI is built, after the pilot.)
- TS `strict`; API types generated from OpenAPI, never hand-written (`make generate-types`). [enforced by: API Types]
- TanStack Query for server state; loading, empty, error and "server waking up" states everywhere. [review]
- WCAG AA, keyboard actions, dialog focus. [enforced by: axe test]
- No `dangerouslySetInnerHTML` on legacy or model text; source excerpts render as escaped text. [enforced by: eslint rule]

## 12. CI/CD and deployment
- `develop` is the default and integration branch and **deploys staging on merge**; `main` is release only; there is one deployed environment, `staging`, fixture data only (SEC-3.1). The build plan and branching document MUST say the same. [review]
- Job names are fixed and used verbatim in rulesets: `Lint (Backend)`, `Lint (Frontend)`, `Test (Backend)`, `Test (Frontend)`, `Secret Scan`, `Dependency Audit`, `Container Build`, `API Types`, `Migration Check`, `Eval Smoke`, `Policy Integrity Check`, `Sandbox Safety`, `Fixture Answer Key`. Add each only when its job exists.
- No `continue-on-error` on a check that gates anything. [enforced by: workflow lint test]
- Smoke eval after staging deploy must fail the deploy when it fails. [enforced by: Staging Deploy workflow]
- Saving any env var on a Render image service redeploys the original tag; re-run Staging Deploy after every env change. [review]
- External setup is written as a click-by-click guide in `/mnt/project-files/guides/` after the code PR merges. [review]

## 13. Documentation
- One `docs/<component>.md` per component, written in the component's PR. [review]
- One ADR per non-obvious choice (Status, Date, Context, Decision, Consequences); update the ADR when reality changes it. [review]
- `.env.example` complete, commented, and in sync with `Settings`. [enforced by: test_env_example_matches_settings]
- README has an eval results table; empty until a real run exists. [review]
- Only one copy of these rules exists in the repo. [review]

## 14. Working agreement
1. Plan first for anything beyond a small fix: approach, files, spec sections, risks.
2. Branches `feature/p<phase>-<name>`, cut from fresh `develop`; never commit to `main` or `develop` directly.
3. **One component per PR.** Do not bundle two.
4. Each PR into a higher branch is exactly **one squashed commit**.
5. Verify before claiming done. Run `make lint; make test; make eval-smoke; policy-check`, **read the exit status**, never pipe pytest into `tail` before committing. Report real output, including failures and what could not be verified.
6. Don't invent. Flag contradictions. Never commit secrets. When unsure about safety, choose the safer option and say so.
7. After a merge: check the **staging deploy run on `develop`**, not only the PR checks; rebase open branches; update project memory.
8. If a pushed PR has the wrong commit and force-push is blocked, amend locally, push a new branch name, open a new PR, close the old one, and list the stray branch for deletion.
9. Do not paste URLs, keys or passwords into chat or commits.

## 15. Definition of done (per change)
- Cites the FR, NFR or rule ID.
- No invariant weakened.
- Lint, types and tests pass locally and in CI.
- New behavior has a failure-path test.
- Migrations apply and reverse.
- Logs carry no source text, secrets or personal data.
- Docs, runbook, `.env.example` and ADRs updated.
- Any API route or docstring change ran `make generate-types`.

## Commit and PR format
Imperative or conventional title (`feat(verifier): add V-3 excerpt hash check`); body says why; ends with the attribution lines the session requires. PRs merge into `develop` as merge commits.
