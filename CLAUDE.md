# KORAS SaaS Starter — AI Agent Context

## What this repository is

`koras-saas-starter` is the KORAS application factory. It generates two categories
of repository through a declarative CLI:

```
pnpm create-koras-app <project> --profile <profile>
```

| Profile         | What it generates                                    |
|-----------------|------------------------------------------------------|
| `product`       | A KORAS SaaS product (Docoris, Dianova, LegalApp, …) |
| `control-plane` | KORAS Control Plane — the provisioning authority     |

## Key documents

| Document                  | Purpose                                        |
|---------------------------|------------------------------------------------|
| `ARCHITECTURE.md`         | System overview and technology choices         |
| `PROFILE_ARCHITECTURE.md` | Capability matrix for both profiles            |
| `PRODUCT_GENERATOR_PLAN.md` | Generator CLI design                         |
| `INFRASTRUCTURE_PLAN.md`  | Terraform module strategy                      |
| `ENVIRONMENT_STRATEGY.md` | Branch ↔ environment mapping (immutable)       |
| `DEPENDENCY_MAP.md`       | Package and service dependency graph           |
| `IMPLEMENTATION_ROADMAP.md` | Phase-by-phase build plan                    |
| `BOOTSTRAP_DOCTOR.md`     | `pnpm koras bootstrap:doctor` — preflight checks |
| `RISK_REGISTER.md`        | Identified risks and mitigations               |

## Repository layout (target state)

```
apps/              Next.js applications
services/          FastAPI / Python backend services
packages/          Shared TypeScript packages
python-packages/   Shared Python packages
profiles/          Generator profile manifests and templates
generators/        create-koras-app CLI
supabase/          Database migrations, policies, functions
local/             Docker Compose local development stack
infrastructure/    Terraform modules
deploy/            Deployment scripts
scripts/           Utility scripts
tooling/           Build tooling
docs/              Documentation
tests/             Integration and e2e tests
```

## Technology stack

- **Frontend:** Next.js 15, TypeScript 5, Tailwind CSS, shadcn/ui, Turborepo, pnpm
- **Backend:** FastAPI, Python 3.12+, SQLAlchemy 2, ARQ, APScheduler
- **Database:** Supabase (PostgreSQL) with RLS
- **Auth:** ZITADEL (OIDC — customers never see ZITADEL UI)
- **Secrets:** Doppler (sole secret authority — nothing committed)
- **IaC:** Terraform
- **Hosting:** Vercel (frontend), Fly.io (backend), Cloudflare (DNS/CDN)

## Environment model

| Environment | Branch    | Notes                        |
|-------------|-----------|------------------------------|
| `dev`       | `develop` | Fast feedback; may be broken |
| `test`      | `test`    | Automated test suites        |
| `stg`       | `staging` | Pre-production sign-off      |
| `prod`      | `main`    | Live traffic                 |

This mapping is immutable (ADR required to change).

## Generator rules

- `--profile` is always required in non-interactive mode
- Profile is never inferred from project name
- Terraform never auto-applies — explicit human approval required
- Generator never silently overwrites or destroys existing resources
- Secret values are never exposed in logs, output, or registration payloads
- `--profile control-plane` never requires a pre-existing Control Plane

## Current phase

**Phase 1 — Shared Repository Foundation** (Phase 0 approved 2026-08-16)

Do not implement Phase 2 until Phase 1 is reviewed.
