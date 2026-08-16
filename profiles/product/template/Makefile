.DEFAULT_GOAL := help

.PHONY: help install bootstrap dev down reset seed test health lint typecheck build clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies
	pnpm install
	uv sync

bootstrap: install ## Full local environment setup
	./local/scripts/bootstrap.sh

dev: ## Start local development stack
	docker compose -f local/docker-compose.yml up -d
	pnpm turbo run dev

down: ## Stop local stack
	docker compose -f local/docker-compose.yml down

reset: down ## Wipe volumes and re-bootstrap
	docker compose -f local/docker-compose.yml down -v
	$(MAKE) bootstrap

seed: ## Populate development fixtures
	./local/scripts/seed.sh

test: ## Run all test suites
	pnpm turbo run test
	uv run pytest

health: ## Poll all services until healthy
	./local/scripts/health.sh

lint: ## Lint all sources
	pnpm turbo run lint
	uv run ruff check .

typecheck: ## Type-check all sources
	pnpm turbo run typecheck
	uv run mypy .

build: ## Build all packages
	pnpm turbo run build

clean: ## Remove build artifacts
	pnpm turbo run clean
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
