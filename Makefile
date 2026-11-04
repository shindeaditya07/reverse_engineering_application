.PHONY: help install up down lint test check-key fixture-syntax policy-check policy-lock migrate eval-smoke eval \
        sandbox-check build audit
.DEFAULT_GOAL := help

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install: ## Install Python dependencies
	uv sync

up: .env ## Start the local stack
	docker compose up --build

down: ## Stop and remove containers
	docker compose down

.env:
	cp .env.example .env

lint: ## ruff + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test: ## Unit tests (no network, no model calls)
	uv run pytest

policy-check: ## Policy constants, developer notes, version and SHA-256 lock must agree
	uv run python -m scripts.policy_check

policy-lock: ## Rewrite .policy_lock (only after a deliberate version bump of docs/policies.md)
	uv run python -m scripts.policy_check --lock

check-key: ## Fail if the fixture answer key has drifted from the fixture app
	uv run python fixtures/answer-key/check_key.py

fixture-syntax: ## node --check every fixture source file (does not run or install anything)
	find fixtures/legacy-app -name '*.js' -not -path '*/public/*' -print0 | xargs -0 -n1 node --check

migrate: ## Apply database migrations (needs DATABASE_URL)
	uv run alembic upgrade head

audit: ## Known-vulnerability check of Python dependencies
	uv run --with pip-audit pip-audit

# Not implemented yet. These fail on purpose so a stub can never read as a pass.
eval-smoke eval sandbox-check build:
	@echo "$@: not implemented yet (see docs/build-plan.md)"; exit 1
