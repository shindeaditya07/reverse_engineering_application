# Legacy Reverse-Engineering Platform

A multi-agent platform that reverse-engineers an undocumented legacy Node/Express application into evidence-linked documentation, diagrams, characterization tests and a modernization plan. A human reviews every claim.

**Status: scaffold only (API health endpoint, settings, CI). No analysis code yet.**

- Agent and coding rules: [AGENTS.md](AGENTS.md)
- Business case: [docs/business-case.md](docs/business-case.md)
- Rules (IDs cited by code and tests): [docs/rules.md](docs/rules.md), numbers in [rules_constants.yaml](rules_constants.yaml)
- Spec: [docs/spec.md](docs/spec.md)
- Build plan: [docs/build-plan.md](docs/build-plan.md)
- Branches and environments: [docs/branching-and-environments.md](docs/branching-and-environments.md)

Eval results: none yet.

## Run locally

```bash
uv sync            # install
make lint          # ruff, ruff format check, mypy --strict
make test          # pytest with coverage
docker compose up --build   # db + api on http://localhost:8000/healthz
```

Targets that are not built yet (`migrate`, `seed`, `eval`, `eval-smoke`, `policy-check`, `generate-types`) fail on purpose.
