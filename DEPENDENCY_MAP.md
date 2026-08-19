# KORAS SaaS Starter — Dependency Map

## Overview

This document maps all dependency relationships within the `koras-saas-starter`
monorepo: between TypeScript packages, Python packages, applications, services,
and external platforms.

---

## 1. TypeScript Package Dependency Graph

```
types ◄────────────────────── everything (lowest layer)
        │
config ◄┤
        │
logger ◄┤
        │
validation ◄─────────────────┐
                              │
auth ◄── types, config        │
  │                           │
  ▼                           │
tenant ◄── auth, types        │
  │                           │
  ▼                           │
permissions ◄── tenant, auth  │
                              │
observability ◄── logger, config
                              │
audit ◄── auth, tenant, logger│
                              │
storage ◄── auth, tenant, config
                              │
billing ◄── tenant, auth      │
                              │
email ◄── config              │
                              │
notifications ◄── email, config
                              │
domains ◄── tenant            │
                              │
feature-flags ◄── tenant      │
                              │
security ◄── auth, config     │
                              │
branding ◄── tenant           │
                              │
api-client ◄── auth, types, config
                              │
ui ◄── branding, types        │
```

### Dependency table

| Package          | Depends on                                      |
|------------------|-------------------------------------------------|
| `types`          | (none — foundation layer)                       |
| `config`         | `types`                                         |
| `logger`         | `config`, `types`                               |
| `validation`     | `types`                                         |
| `auth`           | `types`, `config`                               |
| `tenant`         | `auth`, `types`                                 |
| `permissions`    | `tenant`, `auth`, `types`                       |
| `observability`  | `logger`, `config`                              |
| `audit`          | `auth`, `tenant`, `logger`                      |
| `storage`        | `auth`, `tenant`, `config`                      |
| `billing`        | `tenant`, `auth`                                |
| `email`          | `config`                                        |
| `notifications`  | `email`, `config`                               |
| `domains`        | `tenant`                                        |
| `feature-flags`  | `tenant`                                        |
| `security`       | `auth`, `config`                                |
| `branding`       | `tenant`                                        |
| `api-client`     | `auth`, `types`, `config`                       |
| `ui`             | `branding`, `types`                             |

---

## 2. Python Package Dependency Graph

```
koras-logging ◄──────────────── everything (lowest layer)
       │
koras-database ◄── koras-logging
       │
koras-auth ◄── koras-logging, koras-database
       │
koras-tenant ◄── koras-auth, koras-database
       │
koras-storage ◄── koras-auth, koras-tenant, koras-database
       │
koras-queue ◄── koras-logging, koras-database
       │
koras-audit ◄── koras-auth, koras-tenant, koras-logging
       │
koras-ai ◄── koras-auth, koras-logging
       │
koras-observability ◄── koras-logging
```

### Dependency table

| Package              | Depends on                                        |
|----------------------|---------------------------------------------------|
| `koras-logging`      | (none — foundation layer)                         |
| `koras-database`     | `koras-logging`                                   |
| `koras-auth`         | `koras-logging`, `koras-database`                 |
| `koras-tenant`       | `koras-auth`, `koras-database`                    |
| `koras-storage`      | `koras-auth`, `koras-tenant`, `koras-database`    |
| `koras-queue`        | `koras-logging`, `koras-database`                 |
| `koras-audit`        | `koras-auth`, `koras-tenant`, `koras-logging`     |
| `koras-ai`           | `koras-auth`, `koras-logging`                     |
| `koras-observability`| `koras-logging`                                   |

---

## 3. Application → Package Dependencies

### `apps/web` (product)

**TypeScript packages:**
- `auth` — ZITADEL OIDC integration
- `tenant` — tenant context, tenant switcher
- `permissions` — role-based UI rendering
- `branding` — product + customer branding tokens
- `ui` — shared component library
- `api-client` — generated API client
- `feature-flags` — feature gates
- `config` — environment config
- `types` — shared types
- `logger` — client-side logging
- `observability` — OpenTelemetry browser

### `apps/admin` (product — internal ops)

**TypeScript packages:**
- `auth`, `permissions`, `tenant`, `ui`, `api-client`, `audit`, `feature-flags`,
  `config`, `types`, `logger`, `observability`

### `apps/marketing`

**TypeScript packages:**
- `ui`, `branding`, `config`, `types`

### `apps/admin` (control-plane — platform admin)

**TypeScript packages:**
- `auth`, `permissions`, `ui`, `api-client`, `audit`, `config`, `types`, `logger`,
  `observability`

### `apps/portal` (control-plane)

**TypeScript packages:**
- `auth`, `tenant`, `ui`, `api-client`, `billing`, `config`, `types`, `logger`,
  `observability`

---

## 4. Service → Package Dependencies

### `services/api`

**Python packages:**
- `koras-auth` — JWT validation, ZITADEL introspection
- `koras-tenant` — tenant resolution, middleware
- `koras-database` — SQLAlchemy sessions, RLS context
- `koras-logging` — structured request logging
- `koras-observability` — OpenTelemetry traces + metrics
- `koras-audit` — audit log writes
- `koras-storage` — file upload/download
- `koras-queue` — enqueue background jobs

**TypeScript packages (generated OpenAPI client docs):**
- `types` — shared type definitions

### `services/worker`

**Python packages:**
- `koras-auth` — service-to-service auth
- `koras-database` — database access
- `koras-queue` — job consumption
- `koras-logging`, `koras-observability`
- `koras-audit`
- `koras-storage`
- `koras-ai` (product only, if AI Gateway enabled)

### `services/scheduler`

**Python packages:**
- `koras-database`
- `koras-queue` — enqueue scheduled jobs
- `koras-logging`, `koras-observability`

### `services/ai-gateway` (product only)

**Python packages:**
- `koras-auth` — validate caller identity
- `koras-tenant` — per-tenant rate limits
- `koras-ai` — model routing, provider abstraction
- `koras-logging`, `koras-observability`
- `koras-audit` — AI request/response audit

---

## 5. Generator → Profile Dependencies

```
generators/create-koras-app
    │
    ├── profiles/product/manifest.yaml
    │       ├── profiles/product/defaults.yaml
    │       └── profiles/product/template/
    │               ├── apps/web
    │               ├── apps/admin
    │               ├── apps/marketing
    │               ├── services/api
    │               ├── services/worker
    │               ├── services/scheduler
    │               ├── services/ai-gateway
    │               └── packages/* (all)
    │
    └── profiles/control-plane/manifest.yaml
            ├── profiles/control-plane/defaults.yaml
            └── profiles/control-plane/template/
                    ├── apps/admin (platform variant)
                    ├── apps/portal
                    ├── services/api
                    ├── services/worker
                    ├── services/scheduler
                    └── packages/* (subset)
```

---

## 6. Infrastructure Dependency Chain

```
project-bootstrap Terraform module
    │
    ├── modules/github     (no external deps)
    │
    ├── modules/doppler    (no external deps)
    │        │
    │        └── populated with Supabase keys, ZITADEL client secrets
    │               (post-apply provisioner)
    │
    ├── modules/supabase   (no external deps)
    │
    ├── modules/zitadel    (no external deps — platform ZITADEL instances pre-exist)
    │
    ├── modules/vercel
    │        └── depends on: modules/github (repository must exist)
    │
    ├── modules/fly        (no external deps)
    │
    └── modules/cloudflare
             └── depends on: modules/vercel outputs (for CNAME targets)
                           + modules/fly outputs (for A record targets)
```

Apply order enforced by Terraform dependency graph — no manual orchestration needed.

---

## 7. Control Plane → Product Registration Dependency

```
KORAS Control Plane (running)
        │
        ▼
POST /api/platform/v1/products
        ▲
        │
  Product generator (--provision, post-Terraform)
```

The Control Plane must be deployed and reachable before a product can register.
The Control Plane itself never registers with anything — it is bootstrapped
independently.

---

## 8. Local Development Service Dependencies

Host ports are **not fixed**. A port is a machine-global resource, so a literal
one collides with whatever else is running — a second KORAS stack, a Supabase
CLI stack, or a Windows kernel reservation. `local/scripts/ports.sh` resolves an
available port per machine at `make bootstrap` and writes `local/.env`, which
Docker Compose, the Caddyfile, and the app dev servers all read. `make ports`
re-resolves.

The values below are the **preferences** each profile starts from; the two
profiles use disjoint blocks so a product and the Control Plane can run at once.

```
Caddy (proxy)                        product   control-plane
    ├── apps/web           →         3000      —
    ├── apps/admin         →         3001      3010
    ├── apps/marketing     →         3002      —
    ├── apps/portal        →         —         3011
    ├── services/api       →         8000      8010
    ├── services/ai-gateway →        4000      —
    └── ZITADEL            →         8080      8083
    proxy HTTP / HTTPS     →         8090/8443 8091/8444

services/api
    ├── Supabase (local)   →         54322     54332
    ├── ZITADEL            →         8080      8083
    └── Redis              →         6379      6380

services/worker, services/scheduler
    └── Redis              →         6379      6380

services/ai-gateway (product only)
    └── services/api       → auth check

Supabase (local)
    └── PostgreSQL         →         54322     54332
```

The proxy never binds 80/443: those need root on Linux, and on Windows 80 is
reserved by `http.sys` whenever IIS is installed. Application URLs therefore
carry the proxy's HTTPS port — `https://app.localhost:8443` — and `make health`
prints the resolved ones.

---

## 9. External Platform Accounts Required

| Platform       | Required for    | Account type        |
|----------------|-----------------|---------------------|
| GitHub         | All projects    | GitHub Org          |
| Doppler        | All projects    | Doppler Workplace   |
| Supabase       | All projects    | Supabase Org        |
| ZITADEL Cloud  | All projects    | ZITADEL Cloud Org   |
| Vercel         | All projects    | Vercel Team         |
| Fly.io         | All projects    | Fly.io Org          |
| Cloudflare     | All projects    | Cloudflare Account  |
| Terraform Cloud| All projects    | HCP Terraform Org   |

These are platform-level accounts owned by KORAS, not created per project.
Per-project resources are created within these accounts by Terraform.
