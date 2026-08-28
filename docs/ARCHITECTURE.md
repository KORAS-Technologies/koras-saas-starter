# KORAS SaaS Starter — Architecture

## Overview

`koras-saas-starter` is the official KORAS application factory. It produces fully
structured, infrastructure-ready repositories for two distinct categories of project:

| Category        | Profile           | Description                                        |
|-----------------|-------------------|----------------------------------------------------|
| SaaS product    | `product`         | Docoris, Dianova, LegalApp, and future products    |
| Platform system | `control-plane`   | KORAS Control Plane — the provisioning authority   |

Both categories share the same engineering foundation (monorepo layout, TypeScript
packages, Python packages, Supabase, ZITADEL, Doppler, Terraform, local dev stack)
but differ in which applications, services, and capabilities are enabled.

---

## Generator Model

```
pnpm create-koras-app <project> --profile <profile>
```

```
                   koras-saas-starter
                           │
                           ▼
                    create-koras-app
                           │
              ┌────────────┴────────────┐
              │                         │
      --profile product       --profile control-plane
              │                         │
      ┌───────┼────────┐                │
      ▼       ▼        ▼                ▼
   Docoris  Dianova  LegalApp    koras-control-plane
```

The generator is declarative. Profile behavior is centralized in `profiles/` manifests.
No profile-specific `if` chains are scattered through generator code.

---

## Monorepo Layout

```
koras-saas-starter/
│
├── apps/                       # Frontend applications (Next.js)
│   ├── web/                    # Product: customer-facing SaaS UI
│   ├── admin/                  # Product: internal ops / Control Plane admin
│   └── marketing/              # Product: marketing site
│
├── services/                   # Backend services (FastAPI / Python)
│   ├── api/                    # Primary REST + WebSocket API
│   ├── worker/                 # Background job worker (ARQ / Celery)
│   ├── scheduler/              # Cron / task scheduler
│   └── ai-gateway/             # AI model proxy + routing
│
├── packages/                   # Shared TypeScript packages
│   ├── auth/
│   ├── tenant/
│   ├── permissions/
│   ├── ui/
│   ├── branding/
│   ├── config/
│   ├── api-client/
│   ├── validation/
│   ├── logger/
│   ├── observability/
│   ├── audit/
│   ├── storage/
│   ├── billing/
│   ├── email/
│   ├── notifications/
│   ├── domains/
│   ├── feature-flags/
│   ├── security/
│   └── types/
│
├── python-packages/            # Shared Python packages
│   ├── koras-auth/
│   ├── koras-platform/
│   ├── koras-tenant/
│   ├── koras-database/
│   ├── koras-storage/
│   ├── koras-ai/
│   ├── koras-queue/
│   ├── koras-audit/
│   ├── koras-logging/
│   └── koras-observability/
│
├── profiles/                   # Generator profile manifests
│   ├── product/
│   │   ├── manifest.yaml
│   │   ├── template/
│   │   └── defaults.yaml
│   └── control-plane/
│       ├── manifest.yaml
│       ├── template/
│       └── defaults.yaml
│
├── generators/
│   └── create-koras-app/
│       ├── src/
│       │   ├── cli/
│       │   ├── profiles/
│       │   ├── generation/
│       │   ├── validation/
│       │   ├── terraform/
│       │   └── registration/
│       ├── tests/
│       └── package.json
│
├── supabase/                   # Shared migration base
│   ├── migrations/
│   ├── policies/
│   ├── functions/
│   ├── fixtures/
│   ├── seed/
│   └── tests/
│
├── local/                      # Docker Compose local development stack
│   ├── docker/
│   ├── zitadel/
│   ├── queue/
│   ├── mail/
│   ├── storage/
│   ├── ai/
│   ├── proxy/
│   ├── observability/
│   ├── certs/
│   ├── scripts/
│   └── config/
│
├── infrastructure/
│   ├── terraform/
│   │   ├── modules/
│   │   │   ├── github/
│   │   │   ├── doppler/
│   │   │   ├── supabase/
│   │   │   ├── zitadel/
│   │   │   ├── vercel/
│   │   │   ├── fly/
│   │   │   ├── cloudflare/
│   │   │   └── project-bootstrap/
│   │   ├── environments/
│   │   └── templates/
│   ├── vercel/
│   ├── fly/
│   ├── doppler/
│   ├── zitadel/
│   └── cloudflare/
│
├── deploy/
├── scripts/
├── tooling/
├── docs/
├── tests/
├── .github/
├── .devcontainer/
├── .vscode/
├── turbo.json
├── pnpm-workspace.yaml
├── pyproject.toml
├── package.json
├── Makefile
├── CLAUDE.md
└── README.md
```

---

## Technology Stack

### Frontend
| Layer          | Technology        |
|----------------|-------------------|
| Framework      | Next.js 15 (App Router) |
| Language       | TypeScript 5      |
| UI components  | shadcn/ui + Radix |
| State          | Zustand / React Query |
| Styling        | Tailwind CSS      |
| Package mgr    | pnpm + Turborepo  |

### Backend
| Layer          | Technology        |
|----------------|-------------------|
| Framework      | FastAPI           |
| Language       | Python 3.12+      |
| ORM            | SQLAlchemy 2 + Alembic |
| Auth           | ZITADEL (OIDC/JWT)|
| Queue          | ARQ (Redis-backed)|
| Scheduler      | APScheduler       |

### Data
| Layer          | Technology        |
|----------------|-------------------|
| Primary DB     | Supabase (PostgreSQL) |
| Auth store     | ZITADEL           |
| Cache          | Redis (Upstash / self-hosted) |
| File storage   | Supabase Storage / S3-compatible |

### Infrastructure
| Layer          | Technology        |
|----------------|-------------------|
| IaC            | Terraform         |
| Frontend host  | Vercel            |
| Backend host   | Fly.io            |
| DNS / CDN      | Cloudflare        |
| Secrets        | Doppler           |
| Auth platform  | ZITADEL           |

---

## Identity Architecture

ZITADEL is the identity engine only. Customers must never see ZITADEL UI. All
authentication surfaces use product-branded or KORAS-branded experiences built on
top of ZITADEL's OIDC flows.

Four isolated ZITADEL instances are maintained:

```
ZITADEL DEV   →  develop branch  →  dev environment
ZITADEL TEST  →  test branch     →  test environment
ZITADEL STG   →  staging branch  →  stg environment
ZITADEL PROD  →  main branch     →  prod environment
```

---

## Security Principles

- Doppler is the sole secret authority — no secrets in code or environment files
- RLS enforced at the database layer for all tenant-scoped data
- ZITADEL JWT verification on every API request
- Terraform never auto-applies — explicit human approval required
- Generator never silently overwrites or destroys existing resources
- Control Plane registration never transmits secret values — only infrastructure references
- Registration is specified by `koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md`,
  which is authoritative for both directions; this repository implements the
  client half of it. See [REGISTRATION_LIFECYCLE.md](REGISTRATION_LIFECYCLE.md)
