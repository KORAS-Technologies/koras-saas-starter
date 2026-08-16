# KORAS SaaS Starter — Project Plan

## Purpose

`koras-saas-starter` is the KORAS application factory. It produces two categories
of project through a declarative generator CLI:

| Profile         | Output                  |
|-----------------|-------------------------|
| `product`       | Docoris, Dianova, LegalApp, any future SaaS product |
| `control-plane` | KORAS Control Plane — the provisioning and entitlement authority |

This document defines the phased delivery plan, success criteria, and owner
responsibilities for building and maintaining the starter.

---

## Phased Delivery Plan

### Phase 0 — Architecture & Planning ✦ current phase ✦

**Goal:** Produce reviewed, approved documentation before any code is written.

**Deliverables:**
- `ARCHITECTURE.md` — system overview and technology choices
- `PROJECT_PLAN.md` — this document
- `IMPLEMENTATION_ROADMAP.md` — phase-by-phase build sequence
- `PROFILE_ARCHITECTURE.md` — full capability matrix for both profiles
- `PRODUCT_GENERATOR_PLAN.md` — generator CLI design
- `INFRASTRUCTURE_PLAN.md` — Terraform module strategy
- `ENVIRONMENT_STRATEGY.md` — branch-to-environment mapping
- `DEPENDENCY_MAP.md` — package and service dependency graph
- `RISK_REGISTER.md` — identified risks and mitigations

**Exit criterion:** All documents reviewed and approved by the KORAS team.

---

### Phase 1 — Shared Repository Foundation

**Goal:** Establish the monorepo skeleton that both profiles share.

**Deliverables:**
- `pnpm-workspace.yaml` — workspace declaration
- `turbo.json` — Turborepo pipeline
- `pyproject.toml` — Python workspace root
- `package.json` — root package
- `Makefile` — developer convenience targets
- `.github/` — PR templates, issue templates, initial workflows
- `.devcontainer/` — reproducible dev container
- `.vscode/` — recommended extensions and settings
- `CLAUDE.md` — AI agent context document
- Empty `apps/`, `services/`, `packages/`, `python-packages/`, `profiles/`,
  `generators/`, `supabase/`, `local/`, `infrastructure/`, `deploy/`,
  `scripts/`, `tooling/`, `docs/`, `tests/` directories with `.gitkeep`

**Exit criterion:** `pnpm install` succeeds; `turbo run build` runs (no-op).

---

### Phase 2 — Profile Architecture

**Goal:** Implement the declarative profile system that drives the generator.

**Deliverables:**
- `profiles/product/manifest.yaml`
- `profiles/product/defaults.yaml`
- `profiles/product/template/` skeleton
- `profiles/control-plane/manifest.yaml`
- `profiles/control-plane/defaults.yaml`
- `profiles/control-plane/template/` skeleton
- Profile loader library (`generators/create-koras-app/src/profiles/`)
- Profile validation schema

**Exit criterion:** Profile manifests load and validate without errors.

---

### Phase 3 — Product Profile Template

**Goal:** Complete the template that `--profile product` renders.

**Deliverables:**
- All `apps/web`, `apps/admin`, `apps/marketing` scaffolds
- `services/api`, `services/worker`, `services/scheduler`, `services/ai-gateway`
- Shared `packages/` stubs
- Shared `python-packages/` stubs
- `supabase/` migration base with tenant-aware RLS policies
- `local/docker-compose.yml` for product profile

**Exit criterion:** A generated product project starts with `make dev`.

---

### Phase 4 — Control Plane Profile Template

**Goal:** Complete the template that `--profile control-plane` renders.

**Deliverables:**
- `apps/admin` (platform admin) and `apps/portal` (customer portal) scaffolds
- `services/api`, `services/worker`, `services/scheduler`
- Same shared package stubs as product (no AI Gateway, no web, no marketing)
- `local/docker-compose.yml` for control-plane profile

**Exit criterion:** A generated control-plane project starts with `make dev`.

---

### Phase 5 — Local Development Stack

**Goal:** Fully functional `make bootstrap && make dev` for both profiles.

**Deliverables:**
- `local/docker/` — per-profile Docker Compose files
- `local/zitadel/` — ZITADEL local configuration
- `local/queue/` — Redis configuration
- `local/mail/` — Mailpit / MailHog configuration
- `local/storage/` — MinIO configuration
- `local/ai/` — LiteLLM proxy configuration
- `local/proxy/` — Caddy / Traefik with local TLS
- `local/observability/` — OpenTelemetry Collector + Grafana + Loki + Tempo
- `local/certs/` — mkcert certificate generation scripts
- `local/scripts/` — bootstrap, seed, reset helpers
- `Makefile` targets: `bootstrap`, `dev`, `down`, `reset`, `seed`, `test`, `health`

**Exit criterion:** Both profile local stacks pass `make health`.

---

### Phase 6 — Terraform Modules

**Goal:** Reusable, profile-aware Terraform modules for all provisioning targets.

**Deliverables:**
- `infrastructure/terraform/modules/github/`
- `infrastructure/terraform/modules/doppler/`
- `infrastructure/terraform/modules/supabase/`
- `infrastructure/terraform/modules/zitadel/`
- `infrastructure/terraform/modules/vercel/`
- `infrastructure/terraform/modules/fly/`
- `infrastructure/terraform/modules/cloudflare/`
- `infrastructure/terraform/modules/project-bootstrap/` — orchestration module
- `infrastructure/terraform/environments/` — per-env variable files
- `infrastructure/terraform/templates/` — rendered per-project configs

**Exit criterion:** `terraform validate` passes for both profile configurations.

---

### Phase 7 — Generator CLI

**Goal:** Implement the `create-koras-app` CLI binary.

**Deliverables:**
- `generators/create-koras-app/src/cli/` — argument parsing, interactive mode
- `generators/create-koras-app/src/generation/` — file rendering engine
- `generators/create-koras-app/src/validation/` — slug, profile, conflict checks
- `generators/create-koras-app/package.json` — binary declaration

**Commands:**
```
pnpm create-koras-app
pnpm create-koras-app <project> --profile <profile>
pnpm create-koras-app --help
pnpm create-koras-app --list-profiles
pnpm create-koras-app <project> --profile <profile> --dry-run
```

**Exit criterion:** Generator runs for both profiles without `--provision`; dry-run
outputs file manifest without writing files.

---

### Phase 8 — `--profile` Implementation

**Goal:** Generator correctly applies profile manifests to template rendering.

**Deliverables:**
- Profile capability matrix applied during generation
- Optional components prompted when interactive
- Generated repository passes structural tests
- Profile-specific README and CLAUDE.md rendered correctly

**Exit criterion:** All Phase 23 generator tests pass for both profiles.

---

### Phase 9 — `--provision`

**Goal:** `--provision` orchestrates Terraform bootstrap and waits for approval.

**Deliverables:**
- `generators/create-koras-app/src/terraform/` — Terraform runner
- Explicit `terraform plan` → human approval → `terraform apply` flow
- Input variable assembly from generator context
- Post-apply infrastructure reference extraction

**Exit criterion:** `--provision --dry-run` prints full Terraform plan without
applying. `--provision` with confirmation creates all resources.

---

### Phase 10 — Control Plane Registration Client

**Goal:** Product profile registers itself with the KORAS Control Plane after
infrastructure provisioning.

**Deliverables:**
- `generators/create-koras-app/src/registration/` — registration client
- Registration contract schema
- Only infrastructure references transmitted — never secrets
- Control plane profile skips registration entirely

**Exit criterion:** Product registration POST succeeds against a running Control
Plane. Control Plane profile produces no registration attempt.

---

### Phase 11 — CI/CD

**Goal:** GitHub Actions pipelines for the starter itself and for generated projects.

**Deliverables:**
- `.github/workflows/ci.yml` — lint, test, build
- `.github/workflows/release.yml` — package publishing
- `.github/workflows/generator-integration.yml` — full generator run in CI
- Generated project workflow templates (committed into `profiles/*/template/`)

**Exit criterion:** All CI workflows pass on `main`.

---

### Phase 12 — Security

**Goal:** Security hardening of the starter, generator, and generated output.

**Deliverables:**
- Dependency audit pipeline (Dependabot / `pnpm audit`)
- Secret scanning (GitHub secret scanning + `gitleaks`)
- SAST (CodeQL)
- OWASP Top 10 review of all generated API surface
- RLS policy tests
- ZITADEL JWT validation test coverage

**Exit criterion:** Zero critical/high findings in automated scans.

---

### Phase 13 — End-to-End Acceptance Tests

**Goal:** Automated validation of Phase 24 and Phase 25 acceptance criteria.

**Deliverables:**
- `tests/e2e/control-plane-provision.test.ts`
- `tests/e2e/product-provision.test.ts`
- Teardown utilities (delete test GitHub repos, Doppler projects, Supabase projects)

**Exit criterion:** Both acceptance tests pass against live infrastructure using
test credentials.

---

## Team Responsibilities

| Area               | Owner                   |
|--------------------|-------------------------|
| Generator CLI      | Platform Engineering    |
| Profile manifests  | Architecture            |
| Terraform modules  | DevOps / Infrastructure |
| Python packages    | Backend Engineering     |
| TypeScript packages| Frontend Engineering    |
| Security review    | Security Engineering    |
| CI/CD pipelines    | DevOps                  |
| Documentation      | All teams               |

---

## Key Constraints

1. Phase 1 does not begin until Phase 0 documents are reviewed and approved.
2. Terraform never auto-applies. Human approval is always required.
3. The Control Plane bootstrap path must work without a pre-existing Control Plane.
4. Secret values are never committed, logged, or transmitted by the generator.
5. Profile behavior is centralized — no scattered `if profile === 'product'` logic.
