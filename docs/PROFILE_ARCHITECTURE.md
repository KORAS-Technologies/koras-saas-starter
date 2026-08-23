# KORAS SaaS Starter — Profile Architecture

## Overview

The KORAS generator uses a **declarative profile system**. Every aspect of what
gets generated — applications, services, capabilities, infrastructure, and
registration behavior — is controlled by a profile manifest. No profile-specific
`if` branches are scattered through generator code.

Two profiles exist initially:

| Profile         | Purpose                                           |
|-----------------|---------------------------------------------------|
| `product`       | Standard KORAS SaaS product (Docoris, Dianova, …) |
| `control-plane` | KORAS Control Plane — platform provisioning authority |

---

## 1. Profile Capability Matrix

| Capability                  | `product` | `control-plane` |
|-----------------------------|-----------|-----------------|
| **Applications**            |           |                 |
| `apps/web`                  | Yes       | No              |
| `apps/admin`                | Optional  | No (platform admin separately named) |
| `apps/marketing`            | Optional  | No              |
| `apps/platform-admin`       | No        | Yes             |
| `apps/portal`               | No        | Yes             |
| **Services**                |           |                 |
| `services/api`              | Yes       | Yes             |
| `services/worker`           | Optional  | Yes             |
| `services/scheduler`        | Optional  | Yes             |
| `services/ai-gateway`       | Optional  | No (default off)|
| **Data**                    |           |                 |
| Supabase                    | Yes       | Yes             |
| ZITADEL                     | Yes       | Yes             |
| **Infrastructure**          |           |                 |
| Doppler                     | Yes       | Yes             |
| Terraform                   | Yes       | Yes             |
| Vercel                      | Yes       | Yes             |
| Fly.io                      | Yes       | Yes             |
| Cloudflare                  | Yes       | Yes             |
| **Developer Experience**    |           |                 |
| Local development stack     | Yes       | Yes             |
| `make bootstrap/dev/down/…` | Yes       | Yes             |
| **Tenant & Identity**       |           |                 |
| Multi-tenant foundation     | Yes       | Yes             |
| Row-level security (RLS)    | Yes       | Yes             |
| Branding system             | Yes       | Yes             |
| Customer branding           | Yes       | No              |
| Custom domains              | Yes       | No              |
| White labeling              | Yes       | No              |
| **Control Plane Relationship** |        |                 |
| Control Plane client        | Yes       | No              |
| Registers as product        | Yes       | No              |
| Product registry            | No        | Yes             |
| Organization registry       | No        | Yes             |
| Tenant registry             | No        | Yes             |
| Provisioning authority      | No        | Yes             |
| Reconciliation engine       | No        | Yes             |
| Subscription management     | No        | Yes             |
| Entitlement authority       | No        | Yes             |
| Infrastructure registry     | No        | Yes             |

---

## 2. Profile Manifests

Every profile is defined by four things:

| Element | Where it lives |
|---------|----------------|
| Profile identifier | `profile:` in `profiles/<p>/manifest.yaml` |
| Profile version | `version:` in `profiles/<p>/manifest.yaml` (semver) |
| Profile manifest | `profiles/<p>/manifest.yaml` — capabilities, template map, infrastructure |
| Generated-project representation | `.koras/project.yaml` in every project the profile generates |

### Profile version vs starter version

Two versions travel with every generated project, and they are independent:

```
starter_version = version of KORAS SaaS Starter   (root package.json)
profile_version = version of the selected profile (profiles/<p>/manifest.yaml)
```

A starter bug fix — a generator defect, a corrected error message — raises
`starter_version` while profile behaviour is unchanged. A breaking change to
what a profile generates raises that profile's `profile_version`. Neither is
hard-coded in generator logic; both are read from metadata at generation time.

```
starter_version = 2.1.0
profile_version = 1.0.0
```

Both are recorded in the generated project's `.koras/project.yaml`, so a
repository can always be traced back to the exact starter *and* profile revision
that produced it. See PRODUCT_GENERATOR_PLAN.md §15 for the manifest contract.

### `profiles/product/manifest.yaml`

```yaml
profile: product
version: "1.0.0"

applications:
  web:
    required: true
    framework: nextjs
  admin:
    required: false
    framework: nextjs
  marketing:
    required: false
    framework: nextjs

services:
  api:
    required: true
    framework: fastapi
  worker:
    required: false
    framework: arq
  scheduler:
    required: false
    framework: apscheduler
  ai_gateway:
    required: false
    framework: litellm

capabilities:
  tenancy: true
  rls: true
  branding: true
  customer_branding: true
  custom_domains: true
  white_label: true
  control_plane_client: true

registration:
  registers_as_product: true
  endpoint: /api/platform/v1/products

infrastructure:
  supabase: true
  zitadel: true
  doppler: true
  vercel:
    applications: [web, admin, marketing]
  fly:
    services: [api, worker, scheduler, ai_gateway]
  cloudflare: true
```

### `profiles/control-plane/manifest.yaml`

```yaml
profile: control-plane
version: "1.0.0"

applications:
  platform_admin:
    required: true
    framework: nextjs
  portal:
    required: true
    framework: nextjs

services:
  api:
    required: true
    framework: fastapi
  worker:
    required: true
    framework: arq
  scheduler:
    required: true
    framework: apscheduler

capabilities:
  tenancy: true
  rls: true
  branding: true
  product_registry: true
  organization_registry: true
  tenant_registry: true
  provisioning: true
  reconciliation: true
  subscriptions: true
  entitlements: true
  infrastructure_registry: true

registration:
  registers_as_product: false

infrastructure:
  supabase: true
  zitadel: true
  doppler: true
  vercel:
    applications: [platform_admin, portal]
  fly:
    services: [api, worker, scheduler]
  cloudflare: true
```

### `template_map` — how the capability matrix reaches template selection

Each manifest ends with a `template_map` block that binds component keys to
template subtrees. The generator includes a subtree only when its component is
enabled, so profile behaviour stays declarative and the generator itself
contains no profile-specific branching:

```yaml
template_map:
  applications:
    platform_admin: apps/admin     # key and directory need not match
    portal: apps/portal
  services:
    api: services/api
    ai_gateway: services/ai-gateway
  capabilities:
    billing: packages/billing
    control_plane_client: packages/control-plane-client
```

Rules:

- A component key absent from `template_map` is generated unconditionally.
- A capability the manifest sets to `false` can never be enabled — `defaults.yaml`
  may switch a supported capability off, never on.
- Required applications and services cannot be disabled; the generator rejects
  `--without <required>` with an actionable error.
- `--with` / `--without` accept application, service, or capability keys and are
  the non-interactive equivalent of the optional-component prompts.

---

## 3. Generated Directory Structure

### `product` profile

```
<project>/
├── .koras/
│   └── project.yaml        KORAS project manifest — identity + versions
│
├── apps/
│   ├── web/                Next.js 15, product customer UI
│   ├── admin/              Next.js 15, internal operations UI   [optional]
│   └── marketing/          Next.js 15, marketing site           [optional]
│
├── services/
│   ├── api/                FastAPI, primary REST + WebSocket
│   ├── worker/             ARQ background jobs                  [optional]
│   ├── scheduler/          APScheduler cron tasks               [optional]
│   └── ai-gateway/         LiteLLM AI proxy                     [optional]
│
├── packages/               TypeScript shared packages
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
├── python-packages/        Python shared packages
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
├── supabase/
│   ├── migrations/         Tenant-aware schema migrations
│   ├── policies/           RLS policies per table
│   ├── functions/
│   ├── fixtures/
│   ├── seed/
│   └── tests/
│
├── local/                  Docker Compose local stack (product variant)
├── infrastructure/
│   ├── terraform/          Generated from modules/project-bootstrap
│   ├── vercel/
│   ├── fly/
│   ├── doppler/
│   ├── zitadel/
│   └── cloudflare/
│
├── deploy/
├── docs/
├── tests/
├── .github/
├── Makefile
├── turbo.json
├── pnpm-workspace.yaml
├── pyproject.toml
├── package.json
├── CLAUDE.md
└── README.md
```

### `control-plane` profile

```
<project>/
├── .koras/
│   └── project.yaml        KORAS project manifest — identity + versions
│
├── apps/
│   ├── admin/              Next.js 15, platform administration UI
│   └── portal/             Next.js 15, customer account portal
│
├── services/
│   ├── api/                FastAPI, platform API
│   ├── worker/             ARQ background jobs (always included)
│   └── scheduler/          APScheduler (always included)
│
├── packages/               Same TypeScript shared packages
│   (billing, ai, domains, feature-flags, customer_branding omitted from defaults)
│
├── python-packages/        Same Python shared packages
│   (koras-ai omitted from defaults)
│
├── supabase/
│   ├── migrations/         Platform schema (no customer tenant tables)
│   ├── policies/           RLS scoped to platform principals
│   ├── functions/
│   ├── fixtures/
│   ├── seed/
│   └── tests/
│
├── local/                  Docker Compose local stack (control-plane variant)
├── infrastructure/
│   ├── terraform/
│   ├── vercel/
│   ├── fly/
│   ├── doppler/
│   ├── zitadel/
│   └── cloudflare/
│
├── deploy/
├── docs/
├── tests/
├── .github/
├── Makefile
├── turbo.json
├── pnpm-workspace.yaml
├── pyproject.toml
├── package.json
├── CLAUDE.md
└── README.md
```

**Explicitly absent from control-plane:**
- `apps/web`
- `apps/marketing`
- `services/ai-gateway`

---

## 4. Infrastructure Differences by Profile

### GitHub

Both profiles create the same branch and environment structure:

```
Branches:  develop, test, staging, main
Envs:      dev, test, stg, prod
Mapping:   develop→dev, test→test, staging→stg, main→prod
```

No infrastructure difference.

### Doppler

Both profiles use the same naming convention:

```
<project>-dev
<project>-test
<project>-stg
<project>-prod
```

No infrastructure difference.

### Supabase

Both profiles create four physically isolated projects:

```
<project>-dev
<project>-test
<project>-stg
<project>-prod
```

**Schema differs:**
- `product` — includes `tenants`, `tenant_members`, `tenant_settings`, RLS per tenant
- `control-plane` — platform schema only; no customer tenant tables in baseline

### ZITADEL

Both profiles create one ZITADEL project per instance:

```
ZITADEL DEV   → <project>
ZITADEL TEST  → <project>
ZITADEL STG   → <project>
ZITADEL PROD  → <project>
```

Project names are NOT suffixed with environment (the instance represents the env).

**OIDC application configuration differs:**
- `product` — product-branded login flows, customer SSO support
- `control-plane` — KORAS staff login flows, MFA enforced

### Vercel

```
product:       web, admin, marketing   (optional components filtered)
control-plane: admin (platform), portal
```

Application names differ. The Vercel Terraform module receives the app list
from the profile manifest.

### Fly.io

```
product:
  <project>-api-<env>
  <project>-worker-<env>       [if enabled]
  <project>-scheduler-<env>    [if enabled]
  <project>-ai-<env>           [if enabled]

control-plane:
  koras-control-plane-api-<env>
  koras-control-plane-worker-<env>
  koras-control-plane-scheduler-<env>
```

No AI Gateway for control-plane by default.

### Cloudflare

Both profiles manage DNS records and WAF rules. Domain structure differs:

```
product:       <project>.app, <project>-admin.app   (customizable)
control-plane: platform.koras.app, portal.koras.app (fixed)
```

---

## 5. Terraform Behavior

The `project-bootstrap` Terraform module receives `profile` as a variable:

```hcl
variable "profile" {
  type        = string
  description = "Generator profile: product or control-plane"
  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "Profile must be 'product' or 'control-plane'."
  }
}
```

Profile-aware resource decisions are confined to the `project-bootstrap` module.
Individual modules (github, doppler, supabase, …) are profile-agnostic and receive
only what they need via explicit variables.

**Never auto-apply.** The generator runs `terraform plan`, shows the output, and
requires explicit human confirmation before `terraform apply`.

---

## 6. Registration Behavior

| Profile         | Registers with Control Plane? | Notes                          |
|-----------------|-------------------------------|--------------------------------|
| `product`       | Yes                           | After infrastructure is live   |
| `control-plane` | No                            | It IS the Control Plane        |

Control Plane bootstrap flow:

```
create-koras-app koras-control-plane --profile control-plane --provision
  ↓
Generate source
  ↓
Terraform (GitHub, Doppler, Supabase, ZITADEL, Vercel, Fly, Cloudflare)
  ↓
Deploy Control Plane
  ↓
Control Plane becomes the platform authority
```

The `control-plane` profile must never require a running Control Plane.
There is no chicken-and-egg dependency.

Product registration flow (only after Control Plane is live):

```
create-koras-app docoris --profile product --provision
  ↓
Generate source
  ↓
Terraform
  ↓
Validate infrastructure
  ↓
POST /api/platform/v1/products
  {
    "name": "docoris",
    "slug": "docoris",
    "github_repo": "koras-org/docoris",
    "supabase_projects": { "dev": "...", "test": "...", ... },
    "vercel_projects": { "web": "...", "admin": "..." },
    "fly_apps": { "api": "...", "worker": "..." },
    "zitadel_project": "docoris"
  }
```

The payload contains **only infrastructure references** — never secret values
such as API keys, connection strings, or tokens.

---

## 7. Local Development

### Shared services (both profiles)

```
Supabase (local)       — PostgreSQL + Auth + Storage
ZITADEL (local)        — Identity provider
Redis                  — Queue and cache
Mailpit                — Local SMTP trap
MinIO                  — Local S3-compatible storage
Caddy                  — Local reverse proxy with TLS
OpenTelemetry          — Collector + Grafana + Loki + Tempo
```

### Product additions

```
LiteLLM proxy          — Local AI gateway  [if ai-gateway enabled]
```

### Make targets (both profiles)

| Target            | Action                                              |
|-------------------|-----------------------------------------------------|
| `make bootstrap`  | Install deps, generate TLS certs, init ZITADEL      |
| `make dev`        | Start full Docker Compose stack                     |
| `make down`       | Stop and clean containers                           |
| `make reset`      | `down` + wipe volumes + `bootstrap`                 |
| `make seed`       | Populate development fixtures                       |
| `make test`       | Run all test suites                                 |
| `make health`     | Poll all services until healthy or timeout          |

---

## 8. Tests

Generator tests must cover both profiles. Required test cases:

```
generate product
  ✓ creates apps/web
  ✓ creates apps/admin (if enabled)
  ✓ creates services/api
  ✓ does NOT create apps/platform-admin
  ✓ includes packages/billing
  ✓ includes control-plane client in packages/api-client
  ✓ registration payload generated

generate control-plane
  ✓ creates apps/admin (platform-admin variant)
  ✓ creates apps/portal
  ✓ creates services/api, worker, scheduler
  ✓ does NOT create apps/web
  ✓ does NOT create apps/marketing
  ✓ does NOT create services/ai-gateway
  ✓ does NOT generate registration payload
  ✓ does NOT require running Control Plane

profile-aware naming
  ✓ Doppler names: <project>-dev, -test, -stg, -prod
  ✓ Supabase names: <project>-dev, -test, -stg, -prod
  ✓ ZITADEL project names: <project> (no env suffix)
  ✓ Fly app names: <project>-api-<env>

profile manifest
  ✓ profile=product loaded from manifest.yaml
  ✓ profile=control-plane loaded from manifest.yaml
  ✓ invalid profile rejected with actionable error

Terraform
  ✓ profile variable passed to project-bootstrap module
  ✓ product generates AI Gateway Fly app when enabled
  ✓ control-plane does NOT generate AI Gateway Fly app
```

---

## 9. Future Profile Extension Strategy

Adding a new profile requires:

1. Create `profiles/<new-profile>/manifest.yaml` defining applications, services,
   capabilities, and registration behavior.
2. Create `profiles/<new-profile>/defaults.yaml` for default prompt answers.
3. Create `profiles/<new-profile>/template/` with the rendered skeleton.
4. Add the profile name to the CLI `--profile` validation allowlist.
5. Add the profile to the `project-bootstrap` Terraform module's `profile` variable
   validation list if infrastructure differs.
6. Add profile tests in `tests/generator/`.

No changes to generator core logic are required for new profiles that fit the
existing capability model. Profiles that require genuinely new infrastructure
primitives add those primitives to the relevant Terraform modules.

### Candidate future profiles

| Profile              | Purpose                                               |
|----------------------|-------------------------------------------------------|
| `internal-tool`      | Staff-only internal tooling (no tenant, no billing)   |
| `data-pipeline`      | Data-heavy product with Airflow/Prefect instead of scheduler |
| `mobile-backend`     | API + worker, no frontend (React Native app separately) |
| `microservice`       | Single-service extraction from existing monolith      |
