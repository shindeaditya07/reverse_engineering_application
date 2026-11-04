.PHONY: install up down lint test audit build secrets migrate seed eval eval-smoke policy-check generate-types

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

# Not built yet. These fail on purpose instead of passing as stubs.
migrate seed eval eval-smoke policy-check generate-types:
	@echo "make $@ is not built yet (see docs/build-plan.md)"; exit 1
