# Legacy Reverse-Engineering Platform

A multi-agent platform that reverse-engineers an undocumented legacy Node/Express application into evidence-linked documentation, diagrams, characterization tests and a modernization plan. A human reviews every claim.

**Status: scaffold only (API health endpoint, settings, CI). No analysis code yet.**

- Agent and coding rules: [AGENTS.md](AGENTS.md)
- Business case: [docs/business-case.md](docs/business-case.md)
- Rules (IDs cited by code and tests): [docs/rules.md](docs/rules.md), numbers in [rules_constants.yaml](rules_constants.yaml)
- Spec: [docs/spec.md](docs/spec.md)
- Build plan: [docs/build-plan.md](docs/build-plan.md)
- Branches and environments: [docs/branching-and-environments.md](docs/branching-and-environments.md)

Eval results (committed under [evals/results/](evals/results/); how to read them: [docs/evals.md](docs/evals.md)):

| Run | What | Recall vs the key | Precision (floor) | Date |
|---|---|---|---|---|
| [baseline-grep](evals/results/2026-11-05-baseline-grep/report.md) | Grep and regex baseline, no model. Recall on the 4 kinds it targets: 89% (8/9). | 20% (8/41, 95% interval 10% to 34%) | 27% (8/30) | 2026-11-05 |

No analyzer has been scored yet. The smoke eval (`make eval-smoke`) is a self-check of the harness, not a result.

## Run locally

```bash
uv sync            # install
make lint          # ruff, ruff format check, mypy --strict
make test          # pytest with coverage
docker compose up --build   # db + api on http://localhost:8000/healthz
```

`make eval-smoke` runs the no-model smoke eval (verifier catch rate, scoring sanity). Targets that are not built yet (`seed`, `eval`, `generate-types`) fail on purpose.
