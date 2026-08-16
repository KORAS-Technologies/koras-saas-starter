.DEFAULT_GOAL := help

.PHONY: help install bootstrap dev down reset seed test health lint typecheck build clean \
        generate generate-product generate-control-plane

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────

install: ## Install all dependencies (Node + Python)
	pnpm install
	uv sync

bootstrap: install ## Full local environment setup (certs, images, ZITADEL init)
	@echo "bootstrap: stub — implemented in Phase 5"

# ── Local development ─────────────────────────────────────────────────────────

dev: ## Start the full local development stack
	@echo "dev: stub — implemented in Phase 5"

down: ## Stop and clean local containers
	@echo "down: stub — implemented in Phase 5"

reset: down bootstrap ## Wipe volumes and re-bootstrap
	@echo "reset: stub — implemented in Phase 5"

seed: ## Populate development fixtures
	@echo "seed: stub — implemented in Phase 5"

health: ## Poll all local services until healthy
	@echo "health: stub — implemented in Phase 5"

# ── Quality ───────────────────────────────────────────────────────────────────

lint: ## Lint all TypeScript and Python sources
	pnpm turbo run lint
	uv run ruff check .

typecheck: ## Type-check all TypeScript and Python sources
	pnpm turbo run typecheck
	uv run mypy .

test: ## Run all test suites
	pnpm turbo run test
	uv run pytest

build: ## Build all packages and applications
	pnpm turbo run build

clean: ## Remove build artifacts and caches
	pnpm turbo run clean
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

# ── Generator ─────────────────────────────────────────────────────────────────

generate: ## Run the interactive generator
	pnpm create-koras-app

generate-product: ## Generate a product project (PROJECT=<name> required)
	@test -n "$(PROJECT)" || (echo "Usage: make generate-product PROJECT=myapp"; exit 1)
	pnpm create-koras-app $(PROJECT) --profile product

generate-control-plane: ## Generate the KORAS Control Plane project
	pnpm create-koras-app koras-control-plane --profile control-plane
