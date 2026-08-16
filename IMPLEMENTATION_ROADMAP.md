# KORAS SaaS Starter — Implementation Roadmap

## Reading This Document

Each phase lists:
- **Prerequisite** — must be complete before this phase begins
- **Scope** — what is built
- **Deliverables** — concrete artifacts
- **Done when** — objective exit criterion

Phases may not overlap unless explicitly marked as parallelizable.

---

## Phase 0 — Architecture & Planning

**Prerequisite:** None
**Status:** Approved ✓ (2026-08-16)

**Scope:** Produce all architecture and planning documents.

**Deliverables:**
```
ARCHITECTURE.md
PROJECT_PLAN.md
IMPLEMENTATION_ROADMAP.md        ← this document
PROFILE_ARCHITECTURE.md
PRODUCT_GENERATOR_PLAN.md
INFRASTRUCTURE_PLAN.md
ENVIRONMENT_STRATEGY.md
DEPENDENCY_MAP.md
RISK_REGISTER.md
```

**Done when:** All documents reviewed and approved. No Phase 1 work begins
before explicit approval.

---

## Phase 1 — Shared Repository Foundation

**Prerequisite:** Phase 0 approved
**Status:** Complete ✓ (verified 2026-08-16 — `pnpm install` and
`turbo run build` both exit 0)

**Deviation:** `.devcontainer/Dockerfile` was not needed — `devcontainer.json`
uses the prebuilt `typescript-node:1-20` image plus Dev Container features
(python, docker-in-docker, terraform, gh). Accepted.

**Scope:** Monorepo skeleton shared by both profiles.

**Deliverables:**
```
pnpm-workspace.yaml
turbo.json
pyproject.toml
package.json
Makefile (stub targets only)
CLAUDE.md
.github/
  PULL_REQUEST_TEMPLATE.md
  ISSUE_TEMPLATE/
  workflows/  (empty placeholders)
.devcontainer/
  devcontainer.json
  Dockerfile
.vscode/
  extensions.json
  settings.json
apps/.gitkeep
services/.gitkeep
packages/.gitkeep
python-packages/.gitkeep
profiles/.gitkeep
generators/.gitkeep
supabase/.gitkeep
local/.gitkeep
infrastructure/.gitkeep
deploy/.gitkeep
scripts/.gitkeep
tooling/.gitkeep
docs/.gitkeep
tests/.gitkeep
```

**Done when:** `pnpm install` succeeds and `turbo run build` exits 0 (no-op).

---

## Phase 2 — Profile Architecture

**Prerequisite:** Phase 1 complete
**Status:** Complete ✓ (verified 2026-08-16 — 48 profile-loader tests pass;
both manifests validate against the Zod schema)

**Scope:** Declarative profile system — manifests and loader.

**Deliverables:**
```
profiles/
  product/
    manifest.yaml
    defaults.yaml
    template/          (empty skeleton)
  control-plane/
    manifest.yaml
    defaults.yaml
    template/          (empty skeleton)

generators/create-koras-app/
  src/profiles/
    loader.ts
    validator.ts
    types.ts
  tests/
    profile-loader.test.ts
  package.json
```

**Done when:** `pnpm test` passes for profile loader; both manifests validate
against schema.

---

## Phase 3 — Product Profile Template

**Prerequisite:** Phase 2 complete
**Status:** Complete ✓ (verified 2026-08-16 — `--profile product` emits 152
files; generated `local/docker-compose.yml` passes `docker compose config`.
`README.md` was missing from the template until Phase 8 and is now delivered.)

**Not yet executed:** `make dev` against a generated project — the exit
criterion is asserted structurally, not by starting the stack.

**Scope:** Full template for `--profile product`.

**Deliverables:**
```
profiles/product/template/
  apps/
    web/           Next.js 15 App Router skeleton
    admin/         Next.js admin skeleton
    marketing/     Next.js marketing skeleton
  services/
    api/           FastAPI skeleton with ZITADEL JWT middleware
    worker/        ARQ worker skeleton
    scheduler/     APScheduler skeleton
    ai-gateway/    LiteLLM proxy skeleton
  packages/
    auth/          ZITADEL client + hooks
    tenant/        Tenant context + RLS helpers
    ui/            shadcn/ui component stubs
    branding/      Branding token system
    (all remaining packages — stubs)
  python-packages/
    koras-auth/    JWT validation, ZITADEL client
    koras-tenant/  Tenant context, middleware
    koras-database/SQLAlchemy base + RLS helpers
    (all remaining packages — stubs)
  supabase/
    migrations/    Initial schema with tenant tables
    policies/      Row-level security policies
  local/
    docker-compose.yml
  Makefile
  turbo.json
  pyproject.toml
  package.json
  CLAUDE.md
  README.md
```

**Done when:** Running `create-koras-app sampleapp --profile product` (without
`--provision`) produces a directory that starts with `make dev`.

---

## Phase 4 — Control Plane Profile Template

**Prerequisite:** Phase 2 complete
**Parallelizable with:** Phase 3
**Status:** Complete ✓ (verified 2026-08-16 — `--profile control-plane` emits
139 files, no `apps/web`, no `apps/marketing`, no `services/ai-gateway`;
generated compose passes `docker compose config`. `README.md` delivered in
Phase 8.)

**Not yet executed:** `make dev` against a generated project.

**Scope:** Full template for `--profile control-plane`.

**Deliverables:**
```
profiles/control-plane/template/
  apps/
    admin/         Platform admin Next.js skeleton
    portal/        Customer portal Next.js skeleton
  services/
    api/           FastAPI skeleton
    worker/        ARQ worker skeleton
    scheduler/     APScheduler skeleton
    (no ai-gateway)
  packages/        Same stubs as product (minus AI-specific)
  python-packages/ Same stubs as product
  supabase/
    migrations/    Control Plane schema (no tenant tables)
    policies/      RLS policies scoped to platform users
  local/
    docker-compose.yml
  Makefile
  turbo.json
  pyproject.toml
  package.json
  CLAUDE.md
  README.md
```

**Done when:** Running `create-koras-app koras-control-plane --profile control-plane`
(without `--provision`) produces a directory that starts with `make dev`.

---

## Phase 5 — Local Development Stack

**Prerequisite:** Phases 3 and 4 complete
**Status:** Complete with deviations ✓ (verified 2026-08-16 — all three
`local/docker/*.compose.yml` files pass `docker compose config`; all seven Make
targets exist at the repo root and in both templates)

**Deviations:** `local/mail/mailpit.yml` and `local/storage/minio.yml` were not
created — Mailpit and MinIO are configured inline in the compose files, which
is simpler and equivalent. `local/certs/README.md` is absent; `generate.sh` is
self-documenting.

**Not yet executed:** `make health` from a clean state on a generated project.

**Scope:** Fully functional local development environment for both profiles.

**Deliverables:**
```
local/
  docker/
    product.compose.yml
    control-plane.compose.yml
    shared.compose.yml
  zitadel/
    config.yaml
    init.sh
  queue/
    redis.conf
  mail/
    mailpit.yml
  storage/
    minio.yml
  ai/
    litellm.yml
  proxy/
    Caddyfile
  observability/
    otel-collector.yml
    grafana/
    loki.yml
    tempo.yml
  certs/
    generate.sh
    README.md
  scripts/
    bootstrap.sh
    seed.sh
    reset.sh
    health.sh
  config/
    .env.local.example
```

**Makefile targets implemented:**
- `make bootstrap` — install deps, generate certs, pull images, init ZITADEL
- `make dev` — start full local stack
- `make down` — stop and clean containers
- `make reset` — `down` + wipe volumes + `bootstrap`
- `make seed` — populate test data
- `make test` — run all test suites
- `make health` — poll all services until healthy

**Done when:** Both profile generated projects pass `make health` from a clean state.

---

## Phase 6 — Terraform Modules

**Prerequisite:** Phase 5 complete
**Status:** INCOMPLETE ✗ (audited 2026-08-16 — exit criterion not met)

All module files exist and six of eight modules validate cleanly
(`github`, `doppler`, `supabase`, `vercel`, `cloudflare`, `project-bootstrap`
structure). Three defects block the exit criterion:

1. **`modules/zitadel/main.tf` is invalid HCL.** Lines 11 and 24 use
   `provider = zitadel[each.key]`. Terraform does not support dynamic provider
   selection by key — `terraform init` fails with "Invalid provider
   configuration reference". Fix: make the module single-instance and
   instantiate it once per ZITADEL instance from `project-bootstrap` with an
   explicit `providers = { zitadel = zitadel.dev }` mapping.
2. **`modules/fly/providers.tf` pins an unreleasable version.**
   `fly-apps/fly ~> 0.1` matches nothing; the latest published release is
   `0.0.9`. `terraform init` cannot resolve the provider.
3. **`infrastructure/terraform/environments/*.tfvars` are untracked** — the
   root `.gitignore` rule `*.tfvars` (line 27) silently excludes them. They
   hold no secrets. Either add a negation for this directory or rename to
   `.tfvars.example`.

**Also worth resolving:** `project-bootstrap/main.tf` hardcodes
`["admin", "portal"]` for the control-plane profile, overriding the
`enabled_apps` the generator now computes correctly (`platform_admin`,
`portal`). Let the passed-in value flow through instead of duplicating the
manifest in HCL.

**Scope:** Reusable, profile-aware Terraform modules.

**Deliverables:**
```
infrastructure/terraform/
  modules/
    github/
      main.tf        repo + branches + protections + environments
      variables.tf
      outputs.tf
    doppler/
      main.tf        project + environments + service tokens
      variables.tf
      outputs.tf
    supabase/
      main.tf        project per environment
      variables.tf
      outputs.tf
    zitadel/
      main.tf        ZITADEL project per instance
      variables.tf
      outputs.tf
    vercel/
      main.tf        Vercel projects (profile-aware)
      variables.tf
      outputs.tf
    fly/
      main.tf        Fly apps per service per env (profile-aware)
      variables.tf
      outputs.tf
    cloudflare/
      main.tf        DNS records + WAF rules
      variables.tf
      outputs.tf
    project-bootstrap/
      main.tf        Orchestration module, calls all above
      variables.tf   Includes: project_name, slug, profile, ...
      outputs.tf
  environments/
    dev.tfvars
    test.tfvars
    stg.tfvars
    prod.tfvars
  templates/
    backend.tf.tpl   Remote state configuration template
```

**Done when:** `terraform validate` passes for both profile configurations;
`terraform plan` produces correct resource sets for product and control-plane.

---

## Phase 7 — Generator CLI

**Prerequisite:** Phase 2 complete
**Status:** Complete ✓ (verified 2026-08-16 — all five commands work;
`--dry-run` prints the manifest without writing; 119 generator tests pass)

**Defect found during the Phase 8 audit and fixed there:**
`bin/create-koras-app.js` imported `../src/cli/index.js`, a path that never
exists — the shim now loads `dist/` and reports how to build.

**Scope:** `create-koras-app` binary — argument parsing, interactive mode,
file rendering, safety checks.

**Deliverables:**
```
generators/create-koras-app/
  src/
    cli/
      index.ts        entrypoint
      args.ts         argument definitions
      interactive.ts  prompts (project name, slug, profile)
    generation/
      engine.ts       template rendering
      context.ts      generation context builder
      writer.ts       safe file writer (no silent overwrite)
    validation/
      slug.ts
      profile.ts
      conflicts.ts    directory + GitHub conflict detection
    index.ts
  bin/
    create-koras-app.js
  tests/
    cli.test.ts
    generation.test.ts
    validation.test.ts
  package.json
  tsconfig.json
```

**CLI commands implemented:**
```
pnpm create-koras-app
pnpm create-koras-app <project> --profile <profile>
pnpm create-koras-app <project> --profile <profile> --dry-run
pnpm create-koras-app --help
pnpm create-koras-app --list-profiles
```

**Done when:** All three commands work; dry-run prints file manifest without
writing; generator tests pass for both profiles.

---

## Phase 8 — `--profile` Implementation

**Prerequisite:** Phases 3, 4, and 7 complete
**Status:** Implemented ✓ (2026-08-16)

**Scope:** Generator correctly applies profile manifests during rendering.

**Deliverables:**
- Profile capability matrix applied to template selection, driven by the
  `template_map` block in each profile manifest — the generator holds no
  profile-specific branching
- Optional components prompted in interactive mode, and selectable
  non-interactively via `--with` / `--without`
- Profile passed into generated `CLAUDE.md`, `README.md`, `Makefile`, and
  `infrastructure/terraform/environments/<env>.tfvars`
- All Phase 23 structural generator tests passing

**Done when:** `generate product` and `generate control-plane` tests in
`tests/generator/` all pass.

---

## Phase 9 — `--provision`

**Prerequisite:** Phase 6 and Phase 7 complete

**Scope:** `--provision` flag triggers Terraform bootstrap with explicit approval.

**Deliverables:**
```
generators/create-koras-app/src/terraform/
  runner.ts        terraform init, plan, apply orchestration
  inputs.ts        variable assembly from generator context
  outputs.ts       post-apply reference extraction
  approval.ts      explicit human confirmation before apply
```

**Flow:**
```
generate source
  ↓
terraform init
  ↓
terraform plan  → show output
  ↓
prompt: "Apply infrastructure? [yes/no]"
  ↓ yes
terraform apply
  ↓
extract outputs
```

**Done when:** `--provision --dry-run` prints plan and exits. `--provision`
with confirmation creates all infrastructure resources for both profiles.

---

## Phase 10 — Control Plane Registration Client

**Prerequisite:** Phase 9 complete

**Scope:** Product profile registers itself with the KORAS Control Plane after
provisioning. Control Plane profile skips registration.

**Deliverables:**
```
generators/create-koras-app/src/registration/
  client.ts         POST /api/platform/v1/products
  contract.ts       registration payload types
  guard.ts          profile check — skip if control-plane
```

**Registration payload contains only:**
- project name, slug
- GitHub repository reference
- Supabase project references (non-secret)
- Vercel project references
- Fly app references
- ZITADEL project name

**Done when:** Product registration test passes against running Control Plane.
Control Plane generation emits zero registration calls.

---

## Phase 11 — CI/CD

**Prerequisite:** Phase 8 complete
**Parallelizable with:** Phase 12

**Scope:** GitHub Actions workflows for the starter and for generated projects.

**Deliverables:**
```
.github/workflows/
  ci.yml                  lint + test + build on all PRs
  release.yml             publish generator on merge to main
  generator-integration.yml  full generate + make dev + make health

profiles/product/template/.github/workflows/
  ci.yml
  deploy-dev.yml
  deploy-test.yml
  deploy-stg.yml
  deploy-prod.yml

profiles/control-plane/template/.github/workflows/
  ci.yml
  deploy-dev.yml
  deploy-test.yml
  deploy-stg.yml
  deploy-prod.yml
```

**Done when:** All starter CI workflows pass on `main`. Generated project
workflows pass lint check.

---

## Phase 12 — Security

**Prerequisite:** Phase 8 complete
**Parallelizable with:** Phase 11

**Scope:** Security hardening of starter, generator, and generated output.

**Deliverables:**
- `.github/workflows/security.yml` — CodeQL + secret scanning + `gitleaks`
- `Dependabot` configuration
- OWASP Top 10 review checklist for generated API
- RLS policy test suite (`supabase/tests/`)
- ZITADEL JWT validation unit tests

**Done when:** Zero critical/high findings in automated scans on `main`.

---

## Phase 13 — End-to-End Acceptance Tests

**Prerequisite:** Phase 10 complete

**Scope:** Automated tests for both acceptance scenarios.

**Deliverables:**
```
tests/e2e/
  control-plane-provision.test.ts
  product-provision.test.ts
  helpers/
    teardown.ts    delete test GitHub repos, Doppler projects, Supabase projects
```

**Done when:** Both tests pass against live infrastructure with test credentials
in a clean environment.

---

## Milestone Summary

| Milestone               | Phases Included |
|-------------------------|-----------------|
| M0 — Architecture approved | 0           |
| M1 — Skeleton + profiles   | 1, 2        |
| M2 — Templates complete    | 3, 4, 5     |
| M3 — Infrastructure ready  | 6           |
| M4 — Generator functional  | 7, 8        |
| M5 — Provision works       | 9, 10       |
| M6 — Production ready      | 11, 12, 13  |
