# Branching and environments

Version 1.0 · 2026-11-04 · draft for review · Phase 1, step 8
Agrees with `build-plan.md` v1.0. **Staging rule:** merging into `develop` deploys `staging`; `main` is release only.

## Part 1. Branches

### Rules
- `develop` is the default and integration branch. `main` is release only. Never commit to either directly.
- Feature branches: `feature/p<phase>-<name>`; later `feature/<name>`, `fix/<name>`, `docs/<name>`. Cut each from fresh `develop` **when it starts**, never in advance.
- Each PR into `develop` is exactly one squashed commit. One component per PR.
- Aditya merges. After a merge: staging deploy run on `develop` checked, open branches rebased, memory updated.
- Release: `release/vX.Y.Z` is one commit on top of `main` with `develop`'s tree (`git read-tree -u --reset origin/develop`), PR into `main`, merged with "Create a merge commit"; Aditya pushes the tag. A bad release becomes the next patch tag.

### Feature branches
Format: scope · key files · acceptance · depends on.

**Phase 1**
1. `feature/p1-planning-docs` · commit the planning documents (`AGENTS.md` at root; `docs/spec.md`, `rules.md`, `build-plan.md`, this file, ADRs template; `rules_constants.yaml`) · files only, no code · docs present once, no duplicates · depends on: GitHub setup.
2. `feature/p1-repo-scaffold` · layout, Makefile, compose, `.env.example`, pre-commit, CI with 7 jobs, typed Settings, `/healthz` · `make lint test` green, all 7 jobs green · depends on: 1.
3. `feature/p1-staging-pipeline` · `staging-deploy.yml`, image build and push, deploy hook, health wait · run on `develop` is green · depends on: 2 · manual: images public, Render guide written after merge.
4. `feature/p1-rules-check` · `scripts/policy_check.py`, SHA lock, `Policy Integrity Check` · fails on a wrong value · depends on: 2.
5. `feature/p1-db-schema` · models, Alembic 0001, Migration Check, append-only guards · migration applies and reverses · depends on: 2 · manual: run migration on staging.
6. `feature/p1-source-ingest` · URL and path to pinned revision, limits, secret and PII scan · hostile-source tests pass, source hash unchanged · depends on: 5.
7. `feature/p1-evidence-resolver` · references to bytes, hashing, encodings · all kinds resolve in tests · depends on: 6.
8. `feature/p1-verifier` · V-1 to V-10, 50 + 50 corpora · 100% bad caught, 95% branch coverage · depends on: 7.
9. `feature/p1-fixture-app` · legacy app with 35 traps, answer key (`needs_review`), `Fixture Answer Key` job · key and app agree · depends on: 2 · manual: Aditya reviews the key.
10. `feature/p1-eval-harness` · scoring, Wilson intervals, results folder, `Eval Smoke` · hand-computed cases pass · depends on: 8, 9.
11. `feature/p1-baseline` · grep/regex finder and its score · score recorded, not tuned · depends on: 10.

**Phase 2**
12. `feature/p2-job-runner` · `SKIP LOCKED`, sweeper, resume · kill and resume test · depends on: 5.
13. `feature/p2-discovery` · inventory, entry points, integrations · meets fixture targets · depends on: 10, 12.
14. `feature/p2-code-analysis` · tree-sitter, call graph, data flow · meets fixture targets · depends on: 13.
15. `feature/p2-data-agent` · schema, ER data, lineage · meets fixture targets · depends on: 13.
16. `feature/p2-review-cli` · queue, accept, edit, reject, Markdown export, audit · no accept without decision · depends on: 8, 12.

**Phase 3** (gate: model benchmark)
17. `feature/p3-model-client` · local-only client, FakeClient, call log, recordings · hosted URL rejected · depends on: 2.
18. `feature/p3-model-benchmark` · timing and quality probe, report committed · decision point for Aditya · depends on: 17.
19. `feature/p3-business-rules` · Business Rule agent · scored on fixture · depends on: 14, 17, 18.
20. `feature/p3-verification-wiring` · retry, demote to Unknown, judge demote-only · judge cannot promote · depends on: 8, 17.
21. `feature/p3-diagrams` · Mermaid from stored data · every node maps to a claim · depends on: 14, 15.
22. `feature/p3-documentation` · assemble docs from claims · V-8 passes · depends on: 19, 20, 21.
23. `feature/p3-sandbox-tests` · sandbox, two-stage fetch, Test agent, `Sandbox Safety` · escape tests pass · depends on: 14.
24. `feature/p3-modernization` · accepted claims only · cites claims · depends on: 22.

**Phase 4 and 5**
25. `feature/p4-pilot-tools` · slice selector, claim sampler script, time log template · sampler is random and reproducible · depends on: 16.
26. `feature/p5-e2e-traps` · all 35 traps end to end · every trap passes or is explained · depends on: 22, 23.
27. `feature/p5-docs-runbook` · README, runbook, eval table · depends on: 26.
28. `feature/p5-live-eval-tooling` · paced runner, cost and time ceiling, invalid-run rule · depends on: 26.
29. `feature/p5-review-ui` · optional React UI · only if the pilot needs it · depends on: 25.
30. `release/v1.0.0` · release branch per rules above.

### Dependency graph
```
1 -> 2 -> 3
2 -> 4
2 -> 5 -> 6 -> 7 -> 8 -> 10 -> 11
2 -> 9 -> 10
5 -> 12 -> 13 -> 14 -> 19
                13 -> 15 -> 21
8 + 12 -> 16 -> 25
2 -> 17 -> 18 -> 19
8 + 17 -> 20
19 + 20 + 21 -> 22 -> 24
14 -> 23
22 + 23 -> 26 -> 27, 28, 29 -> 30
```

## Part 2. Environments

| Environment | Where | Deploys on | Data | Model |
|---|---|---|---|---|
| dev | operator's laptop, `docker compose up` | manual | fixture, pilot, private code | local model |
| CI | GitHub Actions | every PR | fixture only | FakeClient only |
| staging | Render free tier, one region | **merge into `develop`** | fixture only | none; replays recorded outputs |

No non-prod, no production (decision D-4: Render free tier allows one free Postgres). Releases are `v*` tags on `main` that create a GitHub Release and build images; they deploy nothing. If a second database is ever paid for, add `production` then.

### GitHub environment
`staging` only, deployment branch `develop`. Secrets on that environment only: `RENDER_STAGING_API_DEPLOY_HOOK` (and the web hook only if the UI deploys). Variable: `STAGING_API_URL`, no trailing slash. No repository-level secrets, no model keys in GitHub, no registry tokens (images are public).

### Required checks
Added one at a time, only after the job has run: see `build-plan.md`.

### Staging deploy
Workflow `staging-deploy.yml` on push to `develop`: build images, push to GHCR, call the deploy hook, wait for `/healthz`, run the smoke eval, **fail the deploy if the smoke eval fails**. Re-run via workflow_dispatch after any Render env change.
