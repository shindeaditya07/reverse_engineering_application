.PHONY: install up down lint test audit build secrets policy-check policy-lock answer-key migrate seed eval eval-smoke generate-types

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
	uv run pytest --cov=services --cov-report=term-missing

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

# Not built yet. These fail on purpose instead of passing as stubs.
seed eval eval-smoke generate-types:
	@echo "make $@ is not built yet (see docs/build-plan.md)"; exit 1
