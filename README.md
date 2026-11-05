# Legacy Reverse-Engineering Platform

A multi-agent platform that reverse-engineers an undocumented legacy Node/Express application into evidence-linked documentation, diagrams, characterization tests and a modernization plan. A human reviews every claim.

**Status: scaffold only (API health endpoint, settings, CI). No analysis code yet.**

- Agent and coding rules: [AGENTS.md](AGENTS.md)
- Business case: [docs/business-case.md](docs/business-case.md)
- Rules (IDs cited by code and tests): [docs/rules.md](docs/rules.md), numbers in [rules_constants.yaml](rules_constants.yaml)
- Spec: [docs/spec.md](docs/spec.md)
- Build plan: [docs/build-plan.md](docs/build-plan.md)
- Branches and environments: [docs/branching-and-environments.md](docs/branching-and-environments.md)

Eval results: none yet. The smoke eval is a self-check of the harness, not a result; real runs are committed under `evals/results/` ([docs/evals.md](docs/evals.md)).

## Run locally

```bash
uv sync            # install
make lint          # ruff, ruff format check, mypy --strict
make test          # pytest with coverage
docker compose up --build   # db + api on http://localhost:8000/healthz
```

`make eval-smoke` runs the no-model smoke eval (verifier catch rate, scoring sanity). Targets that are not built yet (`seed`, `eval`, `generate-types`) fail on purpose.
