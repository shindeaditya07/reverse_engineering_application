# Legacy Reverse-Engineering Platform

A multi-agent platform that reverse-engineers an undocumented legacy Node/Express application into evidence-linked documentation, diagrams, characterization tests and a modernization plan. A human reviews every claim.

**Status: scaffold only (API health endpoint, settings, CI). No analysis code yet.**

- Agent and coding rules: [AGENTS.md](AGENTS.md)
- Business case: [docs/business-case.md](docs/business-case.md)
- Rules (IDs cited by code and tests): [docs/rules.md](docs/rules.md), numbers in [rules_constants.yaml](rules_constants.yaml)
- Spec: [docs/spec.md](docs/spec.md)
- Build plan: [docs/build-plan.md](docs/build-plan.md)
- Review CLI: [docs/review.md](docs/review.md)
- Branches and environments: [docs/branching-and-environments.md](docs/branching-and-environments.md)

Eval results (committed under [evals/results/](evals/results/); how to read them: [docs/evals.md](docs/evals.md)):

| Run | What | Recall vs the key | Precision (floor) | Date |
|---|---|---|---|---|
| [baseline-grep](evals/results/2026-11-05-baseline-grep/report.md) | Grep and regex baseline, no model. Recall on the 4 kinds it targets: 89% (8/9). | 20% (8/41, 95% interval 10% to 34%) | 27% (8/30) | 2026-11-05 |
| [discovery-v1](evals/results/2026-11-05-discovery-v1/report.md) | Discovery agent, no model. Scored only on the 5 kinds it targets (11 facts, not 41); patterns written after the fixture was read, so optimistic. | 82% (9/11, 95% interval 52% to 95%) | 100% (9/9) | 2026-11-05 |
| [discovery-v2](evals/results/2026-11-06-discovery-v2/report.md) | Discovery agent after the computed `require` moved to Code Analysis (10 facts, not 11); supersedes discovery-v1; patterns written after the fixture was read, so optimistic. | 80% (8/10, 95% interval 49% to 94%) | 100% (8/8) | 2026-11-06 |
| [codeanalysis-v1](evals/results/2026-11-06-codeanalysis-v1/report.md) | Code Analysis agent, no model. Scored on 3 kinds (4 facts); written after the fixture was read, so optimistic; precision is a floor (key lists 2 of 10 routes). | 100% (4/4, 95% interval 51% to 100%) | 33% (4/12) | 2026-11-06 |
| [codeanalysis-v2](evals/results/2026-11-06-codeanalysis-v2/report.md) | Code Analysis agent after taking the computed `require` (T03-F1, stated Unknown); supersedes codeanalysis-v1. Scored on 4 kinds (5 facts); optimistic; precision is a floor (key lists 2 of 10 routes). | 100% (5/5, 95% interval 57% to 100%) | 38% (5/13) | 2026-11-06 |
| [codeanalysis-v3](evals/results/2026-11-06-codeanalysis-v3/report.md) | Code Analysis agent with `flow` claims (callback, promise, async); supersedes codeanalysis-v2. Scored on 5 kinds (8 facts); optimistic; flow recall is by kind and span, the claims are structural; precision is a floor. | 100% (8/8, 95% interval 68% to 100%) | 47% (8/17) | 2026-11-06 |
| [data-v1](evals/results/2026-11-06-data-v1/report.md) | Data agent, no model. Scored on 3 kinds (6 facts); written after the fixture was read, so optimistic; precision is a floor (key lists 6 data facts, the fixture has many more). | 100% (6/6, 95% interval 61% to 100%) | 26% (6/23) | 2026-11-06 |

The smoke eval (`make eval-smoke`) is a self-check of the harness, not a result.

## Run locally

```bash
uv sync            # install
make lint          # ruff, ruff format check, mypy --strict
make test          # pytest with coverage
docker compose up --build   # db + api on http://localhost:8000/healthz
```

`make eval-smoke` runs the no-model smoke eval (verifier catch rate, scoring sanity). Targets that are not built yet (`seed`, `eval`, `generate-types`) fail on purpose.
