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

All planning and reference documents live in `docs/`, matching
`koras-control-plane`. Only `README.md` and this file sit at the root.

| Document                         | Purpose                                          |
|----------------------------------|--------------------------------------------------|
| `docs/ARCHITECTURE.md`           | System overview and technology choices           |
| `docs/PROFILE_ARCHITECTURE.md`   | Capability matrix for both profiles              |
| `docs/PRODUCT_GENERATOR_PLAN.md` | Generator CLI design                             |
| `docs/INFRASTRUCTURE_PLAN.md`    | Terraform module strategy                        |
| `docs/ENVIRONMENT_STRATEGY.md`   | Branch ↔ environment mapping (immutable)         |
| `docs/DEPENDENCY_MAP.md`         | Package and service dependency graph             |
| `docs/IMPLEMENTATION_ROADMAP.md` | Phase-by-phase build plan                        |
| `docs/BOOTSTRAP_DOCTOR.md`       | `pnpm koras bootstrap:doctor` — preflight checks |
| `docs/PROVISIONING_RUNBOOK.md`   | Commands, estate prerequisites, failure recovery |
| `docs/RISK_REGISTER.md`          | Identified risks and mitigations                 |
| `docs/SYNC_BACKLOG.md`           | Gaps between the factory, the two profiles and the generated repositories |
| `docs/CLAUDE_CODE.md`            | Claude Code skills, profiles and inheritance      |

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
- **Queue:** Upstash Redis — one database per environment, never shared
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
- `--output-dir` is effectively required — generating into the starter is refused
- Terraform never auto-applies — explicit human approval required
- Generator never silently overwrites or destroys existing resources
- Secret values are never exposed in logs, output, or registration payloads
- `--profile control-plane` never requires a pre-existing Control Plane
- Credentials are pulled from Doppler by the CLI itself; no `doppler run`
  wrapper is typed, and an outer one is never nested
- Generated projects claim no fixed host port — `local/scripts/ports.sh`
  resolves them per machine into `local/.env`

## Claude Code configuration

`.claude/` at the repository root is the **single source of truth** for the
Claude Code configuration of every KORAS repository — this one and every project
generated from it.

```
.claude/
  CLAUDE.md                     Shared Koras engineering instructions
  commands/                     /feature, /review, /test, /ui-review
  agents/                       architect, frontend, reviewer, tester
  skills/koras-*/               The twelve common Koras skills
  skills/frontend-design/          skills/webapp-testing/          } Vendored external skills, pinned in
  skills/react-best-practices/    } .claude/external-skills.yaml and locked in
  skills/web-design-guidelines/  /  .claude/external-skills.lock.json
  scripts/sync-external-skills.mjs
  external-skills.yaml
  external-skills.lock.json
```

Both profile manifests declare `.claude` as a `shared_asset`, so
`create-koras-app` copies this tree verbatim into every generated project. On
top of it each profile template carries exactly one overlay skill:

| Profile | Overlay, at `profiles/<profile>/template/.claude/skills/` |
|---------|----------------------------------------------------------|
| `product` | `koras-profile-product/` |
| `control-plane` | `koras-profile-control-plane/` |

Common configuration plus one profile overlay — never two duplicate trees. A
generated project identifies its own profile from `.koras/project.yaml`.

This starter is the factory, not a generated project: it carries the common
configuration and no overlay. Profile rules are *authored* here, not applied
here.

See `docs/CLAUDE_CODE.md` for how to add a skill, add a profile, upgrade the
external skills, and bring an existing project back into alignment.

## Current phase

**Phases 0–9 complete.** Phase 9 (`--provision`) met its exit criterion
2026-08-17.

**Open:**

| Phase                                  | State              | Note                                     |
|----------------------------------------|--------------------|------------------------------------------|
| 10 — Control Plane Registration Client | Not started        | `src/registration/` and `--skip-registration` do not exist |
| 11 — CI/CD                             | Work complete      | Both halves done; `generator-integration.yml` builds what it generates. Closes only when its exit criterion stops naming `main` |
| 12 — Security                          | Partially complete | Secret scanning, Dependabot and the state-artifact check done; RLS suite, JWT tests and the OWASP checklist missing |
| 13 — End-to-End Acceptance Tests       | Not started        | Blocked on Phase 10                      |

**Next step:** Phase 10, the Control Plane registration client. It is the only
remaining phase with no work started, and Phase 13 is blocked behind it.
`--skip-registration` matters beyond that phase: R-001's mitigation in
`docs/RISK_REGISTER.md` is written as though the flag exists.

Two caveats when reading the roadmap:

- Phases 11 and 12 define their exit criteria on `main`, which is 85 commits
  behind `develop` as of 2026-08-23 and last received a commit on 2026-08-17.
  Neither phase can close until that is resolved — by promotion, or by moving
  the criterion to `develop`.
- The roadmap does not cover R-020 through R-027 or the OIDC sign-in work.
  Roughly twenty commits of deployment and authentication work sit outside the
  phase structure, recorded only in `docs/RISK_REGISTER.md`. Nothing in the plan has
  "a user signs in to a deployed application" as an exit criterion.

`koras-control-plane` keeps a separate Phase 0–19 roadmap. The numbers are not
shared: Phase 12 is Security here and "Domains and branding" there.
