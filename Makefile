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
	KORAS_PROFILE=$(PROFILE) bash local/scripts/bootstrap.sh

# ── Local development ─────────────────────────────────────────────────────────

PROFILE ?= product
COMPOSE_BASE = -f local/docker/shared.compose.yml
COMPOSE_PRODUCT = $(COMPOSE_BASE) -f local/docker/product.compose.yml
COMPOSE_CP = $(COMPOSE_BASE) -f local/docker/control-plane.compose.yml
COMPOSE_FILES = $(if $(filter control-plane,$(PROFILE)),$(COMPOSE_CP),$(COMPOSE_PRODUCT))

dev: ## Start the full local development stack
	docker compose $(COMPOSE_FILES) up -d
	pnpm turbo run dev

down: ## Stop and clean local containers
	docker compose $(COMPOSE_FILES) down

reset: ## Disabled for the legacy root stack (refuses; see local/scripts/reset.sh)
	KORAS_PROFILE=$(PROFILE) bash local/scripts/reset.sh

seed: ## Populate development fixtures
	bash local/scripts/seed.sh

health: ## Poll all local services until healthy
	bash local/scripts/health.sh

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
