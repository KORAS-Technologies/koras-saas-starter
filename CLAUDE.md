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
| `docs/PROVISIONING_RUNBOOK.md`   | Commands, estate prerequisites, failure recovery, teardown |
| `docs/RISK_REGISTER.md`          | Identified risks and mitigations                 |
| `docs/OWASP_CHECKLIST.md`        | OWASP API Top 10 review of the generated API     |
| `docs/SYNC_BACKLOG.md`           | Gaps between the factory, the two profiles and the generated repositories |
| `docs/CLAUDE_CODE.md`            | Claude Code skills, profiles and inheritance      |

## Repository layout (target state)

```
apps/              Next.js applications
services/          FastAPI / Python backend services
packages/          Shared TypeScript packages
python-packages/   Shared Python packages
profiles/          Generator profile manifests and templates
  _shared/         Template layer both profiles draw from; not a profile
  product/         SaaS product profile
  control-plane/   Platform authority profile
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

## Profile templates

A generated project is rendered from two template layers:

```
profiles/_shared/template/     walked first
profiles/<profile>/template/   walked second, and wins on a shared path
```

Both are rendered through Handlebars and then filtered by the profile's
`template_map`, so a shared file may be a `.hbs` and may live inside a
capability-gated subtree. A profile that ships its own copy of a shared path
overrides it — the file existing twice is the signal that the divergence was
deliberate.

`shared_assets` in a profile manifest is a different mechanism and stays for a
different job: it copies a directory **verbatim and unconditionally** from the
starter, which is right for the Terraform modules and for `.claude/`, and wrong
for anything that needs rendering or capability gating.

`profiles/_shared/` is not a profile. `VALID_PROFILES` is an explicit list, so
nothing enumerates it as one.

No file exists twice. `shared-template-parity.test.ts` asserts that
structurally -- no path may exist in both profile templates with byte-identical
content -- rather than by listing paths, so a file duplicated tomorrow is caught
without anyone remembering to add it. 126 files are single-sourced in `_shared/`;
the 63 paths that exist in both profiles do so with genuinely different content,
which is deliberate divergence rather than duplication.

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

**Phases 0–12 complete.** Phases 10, 11 and 12 met their exit criteria on
2026-08-25. Phase 13 is complete except its live-infrastructure variant.

**Open:**

| Phase | State | Note |
|-------|-------|------|
| 13 — End-to-End Acceptance Tests | All but the live apply | Both scenarios automated and passing. The live variant is gated behind `KORAS_E2E_LIVE` and needs an explicit authorisation. It can now be torn down: all seven providers have deleters, though none has been run against a real API — see R-036 |

**Open risks:** R-036 only, and narrowed: teardown covers all seven providers,
but every one of them has only ever been exercised against an injected `fetch`.
A green suite says the requests are shaped as the APIs document, not that any
API accepts them.
R-031 stands accepted with mitigation.

**Next step:** the `--with` / `--without` paths through the generator are
untested. Nothing generates with optional components and checks the result, and
a defect sat in one of those paths for as long as the flag existed (R-037).

**What is verified, and how.** CI, Security and Generator Integration all run on
`develop` and are green. Generator Integration generates both profiles and
lints, builds, typechecks and tests each, runs the row-level security suite
against a real Postgres, and mutation-tests that suite by removing `force` and
requiring it to fail. Local `pnpm lint`, `typecheck` and `test` cover Python as
well as JavaScript; they did not until 2026-08-25, and `turbo` was replaying
cached results across template edits until the same day (R-035).

**Registration, in one paragraph.** A product registers itself with the Control
Plane after `terraform apply`, from `generators/create-koras-app/src/registration/`.
The address and bearer token come from Doppler as `KORAS_CONTROL_PLANE_URL` and
`KORAS_CONTROL_PLANE_TOKEN`; `--control-plane-url` overrides the former and
nothing overrides the latter. An unconfigured Control Plane is a skip, not a
failure — that is the documented bootstrap order (R-001). A failure never
unwinds infrastructure. The Control Plane profile registers nothing, refused
three independent times.


Caveats when reading the roadmap:

- Phases 11 and 12 now define their exit criteria on `develop` (decided
  2026-08-24). `main` was 85 commits behind and last received a commit on
  2026-08-17, so a criterion defined there could not close on work already
  done. Promotion to `main` is a release step, not a definition of done.
- **The workflows now run** (resolved 2026-08-25). They had zero recorded runs
  across 85+ commits; the cause was Actions billing on a private repository,
  and the repository being public is what makes minutes free. Jobs are observed
  starting and succeeding. **Making the repository private again re-blocks
  every run** and returns each CI-based criterion to unmeasurable — see R-030,
  which reopens rather than being rediscovered.
- The roadmap does not cover R-020 through R-027 or the OIDC sign-in work.
  Roughly twenty commits of deployment and authentication work sit outside the
  phase structure, recorded only in `docs/RISK_REGISTER.md`. Nothing in the plan has
  "a user signs in to a deployed application" as an exit criterion.

`koras-control-plane` keeps a separate Phase 0–19 roadmap. The numbers are not
shared: Phase 12 is Security here and "Domains and branding" there.
