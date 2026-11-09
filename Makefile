.PHONY: sandbox-safety install up down lint test audit build secrets policy-check policy-lock answer-key migrate seed eval eval-smoke generate-types

install:
	uv sync

up:
	docker compose up --build

down:
	docker compose down

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test:
	uv run pytest --cov=services --cov-branch --cov-report=term-missing --cov-report=json
	uv run python -I scripts/check_verifier_coverage.py

# Smoke eval: no model. Verifier catch rate on the seeded bad corpus (must be 100%) and a
# check that scoring a run that copies the key gives 100%. Prints rates with intervals.
eval-smoke:
	uv run python -m services.evals smoke

audit:
	uv run pip-audit

build:
	docker build -t platform-api:local .

secrets:
	git ls-files -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline

policy-check:
	uv run python -I scripts/policy_check.py

# After a reviewed change to docs/rules.md (version bumped) or rules_constants.yaml.
policy-lock:
	uv run python -I scripts/policy_check.py --write-lock

# Drift check: the fixture answer key still matches the fixture app. Passing does not mean reviewed.
answer-key:
	uv run python -I scripts/check_answer_key.py

# Apply migrations to DATABASE_URL (never run at API startup).
migrate:
	uv run alembic upgrade head

# Needs a running Docker daemon. Pulls the pinned image, then runs hostile code in it and
# requires every escape attempt to fail (TST-1.2, TST-1.3).
sandbox-safety:
	docker pull "$$(uv run python -c 'from services.sandbox.spec import DEFAULT_IMAGE as i; print(i)')"
	REQUIRE_DOCKER=1 uv run pytest tests/test_sandbox_docker.py --no-cov -p no:warnings

# Not built yet. These fail on purpose instead of passing as stubs.
seed eval generate-types:
	@echo "make $@ is not built yet (see docs/build-plan.md)"; exit 1
