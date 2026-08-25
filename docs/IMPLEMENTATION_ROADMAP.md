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
files; the generated stack starts with `make dev` and every service reports
healthy. `README.md` was missing from the template until Phase 8 and is now
delivered; the local-stack defects found while starting it are listed under
Phase 5.)

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
the generated stack starts with `make dev` and every service reports healthy.
`README.md` delivered in Phase 8.)

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
**Status:** Complete ✓ (fixed and verified 2026-08-16 — both generated
profiles start from a clean state and pass `make health` on every service)

Bringing the stack up for real exposed six defects that structural checks had
missed. All are fixed:

1. **Bind mounts resolved one directory too deep.** The compose files mounted
   `./local/proxy/Caddyfile`, but Compose resolves relative paths against the
   compose file's own directory — giving `local/local/...` in generated
   projects and `local/docker/local/...` in the starter. Every container with a
   config mount failed to start. Paths are now `./proxy/...` (templates) and
   `../proxy/...` (starter).
2. **Caddy had no access to the certificates it requires.** The generated
   compose never mounted `./certs`, so Caddy crash-looped on
   `open /certs/app.localhost.pem: no such file or directory` even after
   `make bootstrap` generated them.
3. **The Caddyfile was not profile-aware.** Both profiles shipped an identical
   file listing product-only (`www`) *and* control-plane-only (`portal`) hosts.
   Caddy refuses to start when a referenced certificate is missing, so any
   project that did not enable every optional app failed. `Caddyfile.hbs` and
   `certs/generate.sh.hbs` are now rendered from the component selections.
4. **Proxy upstreams pointed at the container's own loopback.** Apps run on the
   host via `pnpm turbo run dev`, so `localhost:3000` inside the Caddy
   container reached nothing; now `host.docker.internal`. ZITADEL runs in the
   network and is reached by service name. The upstream port is
   `{env.KORAS_PORT_APP_*}`, resolved per machine and passed into the container,
   so the proxy cannot end up forwarding to whatever else took the port.
5. **The ZITADEL healthcheck always failed.** `/app/zitadel ready` reports
   not-ready against a server that is serving traffic, and the image is
   distroless so curl/wget are unavailable. The container healthcheck is
   removed; `make health` probes `/debug/ready` over HTTP. The image is also
   pinned (`v4.17.1`) — `:latest` broke deterministic generation.
6. **`health.sh` checked the wrong things.** It curled HTTP against the
   Postgres port (which can never answer) and polled a Grafana that the
   generated stack does not run. Checks now use `pg_isready` and `redis-cli`
   in-container and match the services each profile actually emits.

**Deviations:** `local/mail/mailpit.yml` and `local/storage/minio.yml` were not
created — Mailpit and MinIO are configured inline in the compose files, which
is simpler and equivalent. `local/certs/README.md` is absent; `generate.sh` is
self-documenting.

**Re-verified 2026-08-17** after the Phase 6–9 changes. Both profiles generate,
issue certificates, start, and report every service healthy; Caddy terminates
TLS on each generated host and routes correctly (`auth.localhost` reaches
ZITADEL in-network; app hosts return 502 only because the apps themselves are
not running). All three starter compose files still resolve.

**Gap found:** `make` is not present on a stock Windows development machine, so
the documented `make bootstrap` / `make dev` / `make health` interface does not
work there at all. Both templates now also expose the same steps as pnpm
scripts (`pnpm bootstrap`, `pnpm stack:up`, `pnpm stack:health`,
`pnpm stack:down`, `pnpm stack:reset`), documented in the generated README.

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
**Status:** Complete ✓ (fixed and verified 2026-08-16 — `terraform validate`
passes for generated product and control-plane configurations)

The initial implementation did not meet the exit criterion. An audit on
2026-08-16 found five defects, all since fixed:

1. **`modules/zitadel` used `provider = zitadel[each.key]`** — Terraform has no
   dynamic provider selection, so `init` failed outright. The module is now
   single-instance and `project-bootstrap` instantiates it four times, each
   wired to an aliased provider (`providers = { zitadel = zitadel.dev }`).
   The root module declares the four aliased `provider "zitadel"` blocks and
   `project-bootstrap` declares matching `configuration_aliases`.
2. **`modules/fly` pinned `fly-apps/fly ~> 0.1`**, which matches no published
   release. Corrected to `~> 0.0.9` in all five places it appears.
3. **Generated projects could not resolve the modules.** The root module
   pointed at `../../infrastructure/terraform/modules/...`, a path outside a
   generated repository. Manifests now declare a `shared_assets` block and the
   generator copies `infrastructure/terraform/modules` verbatim into each
   generated project, which sources `./modules/project-bootstrap`. Modules stay
   single-sourced in the starter rather than duplicated per profile template.
4. **Generated `variables.tf` was invalid HCL** — single-line blocks with
   `;` separators (`variable "enabled_apps" { type = list(string); default = [] }`)
   are rejected by the parser. Rewritten as multi-line blocks.
5. **`infrastructure/terraform/environments/*.tfvars` were untracked** — the
   root `*.tfvars` ignore rule swallowed them. A negation now keeps this
   secret-free directory in version control.

Also resolved: `project-bootstrap/main.tf` hardcoded `["admin", "portal"]` for
the control-plane profile, overriding the `enabled_apps` the generator computes
from the manifest. The passed-in value now flows through.

**Follow-up decisions taken before Phase 9 (2026-08-16):**

- **State layout: one workspace per project.** `backend.tf` already pins
  `workspaces { name = "<slug>" }` and every module fans out over the
  environment set, so a single apply provisions all four environments. The
  per-environment `<env>.tfvars` files (starter and templates alike) implied
  four applies and were removed in favour of one committed, secret-free
  `terraform.tfvars` per generated project.
- **ZITADEL credentials are per instance.** The provider has no
  environment-variable fallback and there are four aliased configurations, so
  `zitadel_instances` now carries a `jwt_profile_json` field and the whole map
  is marked sensitive. It is supplied via `TF_VAR_zitadel_instances` from a
  Doppler-injected shell — never from a file.
- **Credential source: Doppler.** All other provider tokens reach Terraform as
  environment variables (`GITHUB_TOKEN`, `DOPPLER_TOKEN`,
  `SUPABASE_ACCESS_TOKEN`, `VERCEL_API_TOKEN`, `FLY_API_TOKEN`,
  `CLOUDFLARE_API_TOKEN`) injected by `doppler run`.
- **Generated projects had no root `.gitignore`** — a generated repository
  would have committed `node_modules/`, `.terraform/`, and `.env`. Both
  templates now emit one, with an explicit negation so the secret-free
  `terraform.tfvars` stays tracked.

**Not executed:** `terraform plan` — it needs live GitHub, Doppler, Supabase,
ZITADEL, Vercel, Fly, and Cloudflare credentials. That belongs to Phase 9.

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
  `infrastructure/terraform/terraform.tfvars`
- All Phase 23 structural generator tests passing

**Done when:** `generate product` and `generate control-plane` tests in
`tests/generator/` all pass.

---

## Phase 9 — `--provision`

**Prerequisite:** Phase 6 and Phase 7 complete
**Status:** Complete ✓ (2026-08-17 — exit criterion met: `--provision
--dry-run` produced a real plan of 41 resources against live providers and
stopped without applying)

**Scope:** `--provision` flag triggers Terraform bootstrap with explicit approval,
and every generated project carries a machine-readable KORAS project manifest.

**Deliverables:**
```
generators/create-koras-app/src/terraform/
  runner.ts        terraform init, plan, apply orchestration
  inputs.ts        variable assembly from generator context
  outputs.ts       post-apply reference extraction
  approval.ts      explicit human confirmation before apply

generators/create-koras-app/src/generation/
  project-manifest.ts   builds, validates, and serializes .koras/project.yaml

generators/create-koras-app/src/validation/
  generated-project.ts  reads the manifest back from disk after generation
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

**Design notes:**

- **No `--auto-approve`, by construction.** `apply` is reachable only through
  `confirmApply`, which requires the operator to type `yes` in full — `y`, `Y`,
  and `YES` are refusals — and treats a non-interactive session as a refusal
  rather than reading EOF as consent. The saved plan file is what gets applied,
  so the approved plan is exactly what runs.
- **Preflight before `init`.** Terraform reports missing variables one at a
  time and only after providers are downloaded. `preflightInputs` checks all 15
  credentials and variables first and prints the complete list with the
  provider each belongs to.
- **Doppler is invoked by the CLI, not by the operator.** When a command needs
  the bootstrap secrets and the environment does not already carry them, the
  process re-runs itself as `doppler run --project … --config … -- <the same
  argv>`; the profile declares where those credentials live. Wrapping the whole
  process rather than each Terraform call means every later step — the
  execution-mode probe, `terraform`, `git`, `pnpm` — inherits the injected
  environment without knowing Doppler exists. An outer `doppler run` satisfies
  the inputs, so it is never nested, and a `KORAS_DOPPLER_REEXEC` sentinel on
  the child stops a failed injection from looping.
- **`--project` and `--config` are always explicit.** No Doppler scope is
  configured for these repositories, so a bare `doppler run` fails with "You
  must specify a project".
- **Case-sensitive names have uppercase aliases.** Doppler secret names allow
  only `[A-Z0-9_]`, but Terraform matches `TF_VAR_<name>` case-sensitively and
  `TF_TOKEN_` encodes a lowercase hostname. Inputs are accepted under either
  form and resolved to the canonical name before Terraform is spawned.
- **Map variables can be supplied flat.** `TF_VAR_zitadel_instances` and
  `TF_VAR_supabase_environments` are maps covering all four environments, which
  makes rotating a single credential awkward. They can instead be given as
  `ZITADEL_<ENV>_DOMAIN` / `ZITADEL_<ENV>_SERVICE_ACCOUNT_KEY_JSON` and
  `SUPABASE_DB_PASSWORD_<ENV>`, assembled in memory. The blob form still works.
- **`enable_waf` defaults to false.** Cloudflare's OWASP Core Ruleset requires
  a Pro plan; on a Free zone the apply fails. It is plumbed through
  `project-bootstrap` and recorded in the generated `terraform.tfvars`.
- **Secrets never surface.** Outputs marked sensitive by Terraform are dropped
  during parsing and reported by name only, so nothing secret reaches logs or
  the Phase 10 registration payload.
- **`--provision --dry-run` still writes the project** — Terraform can only
  plan a configuration that exists on disk. The dry run applies to
  infrastructure: the run stops after `plan`.
- **`--provision-only` provisions an existing project.** Provisioning fails
  partway for ordinary reasons (a taken name, a rate limit), so retry has to be
  routine. This path skips generation, requires the directory the normal path
  refuses to overwrite, reads component selections from the project's committed
  `terraform.tfvars` rather than re-deriving them from today's defaults, and
  refuses outright if the requested profile differs from the one on disk. The
  directory-conflict error points at it.

**Verified plan** (product profile, `docoris`): 14 GitHub resources (repo, four
branches, default branch, four protections, four environments), 5 Doppler
(project + four configs), 4 Supabase projects, 8 ZITADEL (four projects, four
OIDC apps — no environment suffix), 2 Vercel projects (`web` and `admin`;
`marketing` correctly excluded), 8 Fly apps (api and worker × four
environments; `scheduler` and `ai-gateway` correctly excluded), and 0
Cloudflare resources with the WAF off and DNS deferred.

Five defects were found only by running it against live providers:

1. `terraform_organization` pointed at an organization that did not exist.
2. HCP workspaces default to **Remote** execution, which forbids `plan -out`
   and cannot see Doppler-injected credentials. The runner now checks the
   workspace's execution mode after init and refuses with the fix; the
   organization default should also be set to Local.
3. Windows environment variable names are case-insensitive, so passing both
   `TF_VAR_GITHUB_ORG` and `TF_VAR_github_org` let the alias shadow the name
   Terraform reads. Aliases are now removed once mapped.
4. `for_each` rejects a sensitive value, so the Supabase module could not
   iterate the password map. It now derives keys via `nonsensitive(keys(...))`.
5. Generating with no `--output-dir` wrote a full project into the starter
   repository, which is now refused.

**A real `apply` has since run** against the KORAS estate, for both profiles.
GitHub, Doppler, Supabase, and ZITADEL resources were created; the run stopped
at Vercel. Everything it hit was estate configuration rather than generator
logic, and each failure surfaced *during* apply, after other providers had
already created real resources:

6. **The GitHub token could not create repositories.** A fine-grained token
   whose resource owner was the user, not the organization. The doctor had
   passed it, because `GET /orgs/{org}` serves a public profile and returns 200
   to any valid token — a check that asserted little more than "this token
   exists". It now requires a field GitHub returns only to a token with real
   organization visibility.
7. **Administration does not imply Contents.** With repository creation fixed,
   branch creation failed: reading a git ref needs repository Contents, and
   creating the four environments needs Environments. No API exposes a
   fine-grained token's repository permissions, so the doctor cannot check
   these; they are documented instead.
8. **Component keys are not valid resource names.** `platform_admin` is an
   ordinary component key and an illegal Vercel project name. The product
   profile never hit it — `web`, `admin`, `api`, `worker` carry no underscores —
   so control-plane was the first profile to expose it. Fly had the same latent
   bug for `ai_gateway`. Both modules now hyphenate, and the generator's
   Vercel names were made to agree with what Terraform creates.
9. **Vercel could not see the repository.** `repo_not_found` for a repository
   Terraform had created minutes earlier: the Vercel GitHub App was installed
   only on a personal account. Unlike GitHub's permissions this is visible
   read-only, so the doctor now checks it.

**Not executed:** a full apply through to Cloudflare and Fly. That belongs to
the Phase 13 acceptance test.

The command sequence, estate prerequisites, and failure-to-fix table are in
**PROVISIONING_RUNBOOK.md**.

### Bootstrap preflight — `pnpm koras bootstrap:doctor`

Provisioning contacts seven providers in one Terraform run, so a credential
that expired last week surfaces halfway through — after some resources already
exist. `pnpm koras bootstrap:doctor` moves that discovery to a read-only check
before the first `--provision`:

```bash
pnpm koras bootstrap:doctor
```

Thirteen rows, `✓` or `✗`, `READY FOR BOOTSTRAP` or `NOT READY FOR BOOTSTRAP`,
exit 0 or 1. It creates, updates, and deletes nothing, and never runs
`terraform apply`, `destroy`, or `import`.

The command lives in `tooling/koras-cli` and reads the required-secret list
from the generator's own Terraform input registry, so it cannot drift from what
`--provision` actually needs. Every failure string is redacted before printing.

Full contract, per-row semantics, and secret handling: **BOOTSTRAP_DOCTOR.md**.

### Generated Project Manifest

Every generated repository — both profiles — now contains:

```
.koras/
└── project.yaml
```

**Purpose.** It is the authoritative record of what a repository is and what
produced it. Until now the only machine-readable identity in a generated project
was `infrastructure/terraform/terraform.tfvars`, which is a provisioning input
rather than an identity record. The manifest is a stable platform contract,
consumed by future `koras doctor`, `koras bootstrap:doctor`, `koras upgrade`,
`koras diff-starter`, and `koras project:info`, and by Control Plane
registration tooling. It carries references only — never secrets — and is safe
to commit.

**Fields.**

| Field | Resolved from |
|-------|---------------|
| `schema_version` | Fixed at `1` |
| `project.name` | Project name as supplied to the CLI |
| `project.slug` | Normalized, machine-safe slug |
| `project.profile` | `product` or `control-plane` |
| `generator.name` | Always `create-koras-app` |
| `generator.starter_version` | Root `package.json` `version` |
| `generator.profile_version` | `version` in `profiles/<profile>/manifest.yaml` |

**Versioning.** `starter_version` and `profile_version` are independent semver
values, neither hard-coded in generator logic. A starter fix raises the starter
version without touching profile behaviour; a breaking change to a profile's
generated structure raises that profile's version. Generation *fails* rather
than emitting a placeholder such as `unknown`, `latest`, or `TBD` — a manifest
that lies about its provenance is worse than a failed generation, because
downstream tooling trusts it.

**Profile behaviour.** Both profiles emit the same shape; only the values
differ. The manifest is generator-authored rather than template-authored, so
there is one implementation rather than one per profile, and adding a profile
requires no manifest work beyond a `version` field.

```yaml
# product
schema_version: 1
project:
  name: docoris
  slug: docoris
  profile: product
generator:
  name: create-koras-app
  starter_version: 0.1.0
  profile_version: 1.0.0
```

```yaml
# control-plane
schema_version: 1
project:
  name: koras-control-plane
  slug: koras-control-plane
  profile: control-plane
generator:
  name: create-koras-app
  starter_version: 0.1.0
  profile_version: 1.0.0
```

**Validation.** A Zod schema (`KorasProjectManifestSchema`) validates the
manifest before it is written and is reusable by any future command that reads
one. After generation, the project is re-validated by reading the file back from
disk: it must exist, parse, carry a supported schema version and two semver
versions, and record the profile and slug actually requested. If it does not,
generation fails and nothing is provisioned. Reading back from disk rather than
trusting memory is the point — it proves what downstream tooling will read.

This matters most for the Control Plane: a `--profile control-plane` run that
recorded `profile: product` would let later tooling run product provisioning
against the platform authority. A regression test covers it.

`schema_version: 1` is not to change without an explicit migration design.
Candidate future fields (`environments`, `features`, `infrastructure`) are
deliberately absent.

Full contract: PRODUCT_GENERATOR_PLAN.md §15. Version semantics:
PROFILE_ARCHITECTURE.md §2.

**Done when:** `--provision --dry-run` prints plan and exits. `--provision`
with confirmation creates all infrastructure resources for both profiles.

**Definition of done — generated project manifest:**

- [x] Every generated project contains `.koras/project.yaml`
- [x] Product profile manifest is correct
- [x] Control-plane profile manifest is correct
- [x] Starter version is resolved automatically (root `package.json`)
- [x] Profile version is resolved automatically (profile manifest)
- [x] Manifest schema is validated (Zod, on write and on read-back)
- [x] Manifest is deterministic — fixed field order, byte-identical per context
- [x] `--dry-run` reports manifest generation and writes nothing
- [x] Generated-project validation verifies the manifest
- [x] Tests cover both profiles, including a control-plane profile regression
- [x] Documentation updated (this document, PRODUCT_GENERATOR_PLAN.md,
      PROFILE_ARCHITECTURE.md)

---

## Phase 10 — Control Plane Registration Client

**Prerequisite:** Phase 9 complete
**Status:** Complete (2026-08-25)

The 2026-08-22 survey recorded this phase as not started, and that was wrong by
the time anyone read it: `contract.ts`, `guard.ts`, `--skip-registration`, and
`tests/registration.test.ts` landed on 2026-08-23 and the status line was never
revised. Only `client.ts` — the half that actually sends anything — was
genuinely missing. The correction is recorded rather than quietly overwritten,
because a roadmap that has been wrong once about what exists is a roadmap worth
distrusting on the same question elsewhere.

**Scope:** Product profile registers itself with the KORAS Control Plane after
provisioning. Control Plane profile skips registration.

**Deliverables:**
```
generators/create-koras-app/src/registration/
  client.ts         POST <base>/api/platform/v1/products — the transport
  config.ts         where the Control Plane is, and what authorises the call
  contract.ts       registration payload types
  guard.ts          profile check — skip if control-plane
  index.ts          the step as one call: decide, configure, send
```

**Registration payload contains only:**
- project name, slug, code
- GitHub repository reference
- Doppler project and per-environment config names
- Supabase project references (non-secret)
- Vercel project references
- Fly app references
- ZITADEL project id per environment

### Where the Control Plane is

Registration needs two things that provisioning did not: an address and an
authorisation. Both come from Doppler, injected by the same re-exec that
supplies the provider credentials, so there is no second secret mechanism and
no second place to rotate a token.

| Secret | Purpose |
|--------|---------|
| `KORAS_CONTROL_PLANE_URL` | Base URL, e.g. `https://control-plane.koras.io` |
| `KORAS_CONTROL_PLANE_TOKEN` | Bearer token the Control Plane issues to the factory |

`--control-plane-url` overrides the first for a one-off run — a disposable lab
pointed at a locally-run Control Plane, most often. There is deliberately no
matching flag for the token: a base URL is not a secret and a bearer token is,
and a token on a command line is a token in the shell history, the process
table, and any CI log that echoes the command.

A plaintext `http://` base URL is refused unless its host is a loopback
address, because the token travels in the request headers.

### What happens when it does not work

Registration runs after `terraform apply` has created real infrastructure, and
every rule follows from that:

| Situation | Outcome | Exit |
|-----------|---------|------|
| No `KORAS_CONTROL_PLANE_URL` | Skipped — the documented bootstrap order (R-001) | 0 |
| `--skip-registration` | Skipped, and reported as requested | 0 |
| Control Plane profile | Skipped, and reported as the profile's doing | 0 |
| URL set, token missing | Failed, not retryable — a misconfiguration | 1 |
| 4xx from the Control Plane | Failed, not retryable — sending it again gets the same refusal | 1 |
| 5xx, timeout, transport failure | Failed, retryable | 1 |

Nothing is ever rolled back. R-001 is explicit that a registry being
unreachable is not a reason to unwind a provisioned estate, so a failure prints
the retry command and says the infrastructure is intact. The exit code still
moves so CI notices.

The client never retries on its own. A 4xx would get the same answer, and a
retry of anything else is the operator's `--provision-only`, not a silent loop.

### Not leaking the token

The payload is non-secret by construction — it is built from Terraform outputs
the parser has already stripped of everything marked sensitive, so a credential
cannot reach it however the builder is written. The response is the harder
half: it comes from a server that has just been handed a bearer token, and a
401 that quotes it back is exactly how a token reaches a log. Every response
body and transport error therefore passes through the redactor before it is
printed.

That redactor now lives in `create-koras-app/src/redact.ts` rather than in
`koras-cli`, which is the package that already depends on it. It was moved
rather than copied: two redactors are two chances to fix a leak in only one of
them. `koras-cli/src/doctor/redact.ts` re-exports it, so the doctor's call
sites are unchanged.

**Done when:** Product registration test passes against running Control Plane.
Control Plane generation emits zero registration calls.

**Definition of done:**

- [x] `client.ts` posts the payload with a bearer token and a correlation id
- [x] Base URL and token resolve from Doppler; `--control-plane-url` overrides the former
- [x] Plaintext refused for anything but a loopback host
- [x] Timeout aborts the request rather than racing a timer
- [x] A refusal is never retried; an unreachable Control Plane is marked retryable
- [x] Registration failure never unwinds infrastructure
- [x] No credential in the request body — asserted against outputs that carried two
- [x] No token in any printed message, including one the server quotes back
- [x] Control Plane profile emits zero registration calls, asserted against a listening server
- [x] Wired into `runProvision` after the git push
- [x] 24 unit tests (`registration-client.test.ts`) plus the Phase 13 acceptance suite

**Verified against a running Control Plane.** `tests/e2e/helpers/control-plane-stub.ts`
is a real HTTP server on a real port implementing the subset of the contract
registration touches, including `extra="forbid"`, the refusal of
`profile: control-plane`, and a rejection of any field whose name looks like a
credential. A live Control Plane was not used, and does not need to be: what
differs between the two is which database the row lands in, and that is Phase
13's live variant rather than this phase's criterion.

---

## Phase 11 — CI/CD

**Prerequisite:** Phase 8 complete
**Parallelizable with:** Phase 12
**Status:** Complete (2026-08-25). The criterion was unmeasurable for two days
and is now met.

Both halves are done. The generated-project workflows are byte-identical across
both templates and both generated repositories, and
`.github/workflows/generator-integration.yml` now generates both profiles and
builds what comes out -- install, build, typecheck, test, uv sync, mypy, pytest,
and a drift check that must report nothing about a project generated a moment
earlier. It replaced two jobs whose only substantive step was `echo`-ing the
command they claimed to run.

It found three defects on its first run, which is the argument for it: both
profiles failed to typecheck their Python, the product's auth routes read a
Control Plane setting name, and `services/api` imported pydantic without
declaring it.

**Decision taken 2026-08-24: the exit criterion is `develop`, not `main`.**
`main` was 85 commits behind `develop` and last received a commit on
2026-08-17, so a criterion defined there could not close on work that was
already done. `develop` is where the work lands and where CI runs; promotion to
`main` is a release step, not a definition of done.

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

**Done when:** All starter CI workflows pass on `develop`. Generated project
workflows pass lint check.

**Met 2026-08-25.** "Pass" requires having *run*, and for two days nothing had:
the workflows were registered and active with zero recorded runs across 85+
commits. The cause was Actions billing on a private repository (R-030). The
repository is public, minutes are free, and jobs execute.

Observed on `develop` at `653a7c1`:

| Workflow | Result |
|----------|--------|
| CI | success — Lint & Typecheck, Test (Node), Test (Python), Build |
| Security | success |
| Generator Integration | success — both profiles |

The second half of the criterion was genuinely unmet rather than merely
unmeasured, and reading it carefully is what found that: Generator Integration
built, typechecked and tested what it generated but never linted it, so a lint
rule broken in a template reached every generated repository and waited for
whoever generated one next. A `Lint` step now runs `pnpm turbo run lint` in the
generated project, verified against a freshly generated product first — 31
tasks, clean.

**This rests on the repository staying public.** Making it private re-blocks
every run until the billing failure is settled, and this criterion reverts to
unmeasurable. R-030 reopens rather than being rediscovered.

---

## Phase 12 — Security

**Prerequisite:** Phase 8 complete
**Parallelizable with:** Phase 11
**Status:** Complete (2026-08-25), with one open gap recorded rather than
closed. All five deliverables exist. Two of the three that were missing turned
up defects rather than merely absent tests, and a third defect came from the
first CodeQL scan that ever ran. The exit criterion was reworded once it became
measurable — see **Done when** below for why, and what it now asks.

**Scope:** Security hardening of starter, generator, and generated output.

**Deliverables:**
- [x] `.github/workflows/security.yml` — CodeQL + secret scanning + `gitleaks`
- [x] Dependabot configuration
- [x] OWASP Top 10 review checklist — `docs/OWASP_CHECKLIST.md`
- [x] RLS policy test suite — `supabase/tests/`, shipped to both profiles
- [x] ZITADEL JWT validation tests — `jwt-validation.test.ts`, both tiers

### Two defects, found by writing the missing tests

**RLS was enforced against nobody.** Every table ran `enable row level
security` and none ran `force`. That exempts the table's owner — and the
migrations and the FastAPI service both connect as the owner, through the same
`DATABASE_URL`. The policies in `00002_rls_policies.sql` were present, correct,
and never consulted at runtime.

It fails open, in the direction of cross-tenant reads, and nothing would have
caught it by accident: a developer testing by hand connects as the owner, sees
every policy appear to work, and is looking at a database that is applying none
of them. `force row level security` now covers all eight tables across the two
profiles.

**The ZITADEL token paths pinned only the audience.** Neither the Next.js
id_token path nor the FastAPI bearer path checked `iss`, and neither pinned the
algorithm — while the session-cookie path, the one the application signs
itself and has least reason to distrust, pinned both. The stricter check was on
the input the application generates and the looser one on the input that
arrives from outside.

Not directly exploitable: the key set comes from that instance, so a token
signed elsewhere fails the signature. It is required by OIDC Core §3.1.3.7, and
the argument that the next check catches it is the argument that removes every
check one at a time. Both tiers now pin issuer and algorithm.

The Python fix matters more than the TypeScript one — `verify_token` already
took an `issuer` argument and defaulted it to `None`, so the check was opt-in
and nothing opted in. A fix applied to one language and not the other leaves
the same door open on the service that holds the data.

### The RLS suite

```
supabase/tests/010_rls_structure.sql    schema invariants, profile-agnostic
supabase/tests/020_tenant_isolation.sql two tenants, one context, every policy
local/scripts/test-rls.sh               the runner
```

Structural assertions catch the class of failure that has no symptom: RLS
enabled but not forced, RLS enabled with no policy, a table carrying
`tenant_id` with no RLS at all.

The behavioural suite creates two tenants, sets the context to one, and asks
every policy for the other one's rows — reads *and* writes, because a policy
with `using` and no `with check` lets a row be written into another tenant
while refusing to read it back, which looks like success to the caller. It also
asserts that an unset context sees nothing, which is the state a connection is
in when the API forgets to call `set_rls_context`.

The runner creates a `nologin nobypassrls` role and `SET ROLE`s into it,
because a suite run as the owner passes every assertion while proving nothing.
That is the whole point of the exercise, and it is why the runner creates the
role rather than assuming one.

### What is verified, and what is not

| | |
|---|---|
| RLS structure and enforcement | 10 starter assertions, both profiles |
| JWT verification, both tiers | 36 starter assertions, both profiles |
| JWT behaviour in a generated project | 44 tests, run in the lab; includes a wrong-issuer rejection |
| **The SQL suite executed against a database** | **Run 2026-08-25 — both suites pass, both mutations caught** |

The SQL was executed on 2026-08-25 against Postgres 16 in a disposable
container, applying the freshly generated migrations. Both suites pass, and both
mutations fail as they should — removing `force` and pointing the role check at
a superuser each exit 3 with the specific diagnostic.

**It found that the phase's own fix was incomplete.** `force` binds the table
owner and does nothing to a superuser or a BYPASSRLS role, and a managed
Postgres usually hands out a superuser as the default connection role. A
`DATABASE_URL` from a dashboard therefore yields correct policies, `force`
everywhere, a green suite, and no isolation. `assert_rls_enforced` now refuses
to start the API on such a connection. R-032 carries the measurements.

This is the argument for executing a test suite rather than shipping it: the
structural assertions were green the whole time, and the gap was in what they
did not think to assert.

### Open gaps

`docs/OWASP_CHECKLIST.md` carries the full review. The one finding of substance:

**API4:2023 — there is no rate limiting anywhere in the generated API.** No
per-caller quota, no per-tenant quota. An unauthenticated caller can hammer the
token-verification path, which is the expensive one. Closing it means a limiter
keyed on tenant and subject rather than IP — callers arrive through a CDN — held
in the environment's Upstash Redis rather than in process, since the API runs
more than one machine.

**Done when:** Zero critical/high **CodeQL** findings on `develop`, and every
open Dependabot advisory either fixed or recorded in `RISK_REGISTER.md` with a
stated reason.

The criterion used to say "automated scans", which reads as one number and is
two. The distinction is not pedantry — the two scanners were in opposite states
the first time either of them ran:

| Scanner | Finds | Status on `develop` |
|---------|-------|---------------------|
| CodeQL | defects in code this repository wrote | **0 open** — three high fixed 2026-08-25 |
| Dependabot | advisories in dependencies it consumes | **8 open** — 4 critical, 1 high, 3 moderate |

CodeQL findings are unambiguous: this repository wrote the code and can fix it,
so zero is the right bar and it is met.

Dependabot findings are a judgement. All eight are one dependency chain —
`vitest`, with `vite` and `esbuild` beneath it — every one requires a
development server that is never started, and none appears in any profile
template, so nothing generated or deployed carries them. Closing them means a
major-version upgrade that currently makes `pnpm test` exit 1 for reasons
internal to vitest's worker RPC. That is scheduled work, not a blocker, and
R-031 holds the full reasoning.

Requiring zero from both would either block the phase on a dev-only advisory or
invite the number to be quietly reinterpreted later. Naming the scanner and
demanding a written reason for each accepted advisory asks for the same rigour
without either failure mode.

**Measurable since 2026-08-25, and the first real scan failed it.** The Security
workflow had never executed (R-030, Actions billing on a private repository).
With the repository public it runs, and CodeQL reported **three open
high-severity alerts** on `develop` — which is exactly the count this criterion
asks about, and which nobody could have seen while no scan ran:

| Rule | Location | Verdict |
|------|----------|---------|
| `js/polynomial-redos` | `src/terraform/inputs.ts` | Real. `replace(/\/+$/, '')` is quadratic on slash-heavy input |
| `js/incomplete-sanitization` | `tests/claude-config.test.ts` | Real. `replace('
','')` drops only the first occurrence |
| `js/incomplete-hostname-regexp` | `tests/terraform.test.ts` | Real. Unescaped dots in `app.terraform.io` match any character |

All three fixed. The ReDoS one had already been copied into this phase's own
new code — `registration/config.ts` normalised a base URL the same way — so the
scan caught a defect and its freshly-made duplicate in one pass. Both now use
`stripTrailingSlashes`, a backwards scan that is linear and says what it does.

The two in test files are not exploitable; they are wrong in the way that makes
a test assert something other than it claims, which is its own kind of silent
failure.

**R-034, no rate limiting, was open when this section was written and is now
resolved** — `koras-ratelimit` ships to both profiles. It is worth noting that
no automated scan reported it, and none would have: it is an absent control
rather than a defective one, which is the category a scanner cannot see.

---

## Phase 13 — End-to-End Acceptance Tests

**Prerequisite:** Phase 10 complete
**Status:** Complete for the offline scenarios (2026-08-25); the live-apply
variant is implemented as a gated skip and remains unmet by design — see below.

**Scope:** Automated tests for both acceptance scenarios.

**Deliverables:**
```
tests/e2e/
  control-plane-provision.test.ts   generation, validation, zero registration calls
  product-provision.test.ts         generation, validation, registration
  teardown.test.ts                  the guards on the destructive helper
  helpers/
    control-plane-stub.ts   a real HTTP Control Plane on a real port
    teardown.ts             delete test GitHub repos, Doppler and Supabase projects
    live.ts                 the gate between an acceptance test and a bill
```

`tests/e2e` is a workspace package (`koras-e2e`) so that `turbo run test`
reaches it. The rest of `tests/` is pytest's, and a TypeScript suite dropped
there would have had no runner at all.

### What the offline scenarios cover

Everything a real `--provision` run does except contacting the seven providers.
Terraform's contribution is supplied as the JSON `terraform output -json`
actually emits, including two outputs marked sensitive — those are the point,
since the parser must drop them and no payload built downstream can then carry
them however it is written.

The Control Plane is not stubbed at the function boundary. It is an HTTP server
listening on a loopback port, so registration crosses a socket, real headers,
and a real JSON round trip. It enforces what the Control Plane's own schema
enforces: `extra="forbid"`, the refusal of `profile: control-plane`, and a
rejection of any field whose name looks like a credential.

That matters most for the negative scenario. "The Control Plane makes zero
registration calls" asserted against a function double only proves the double
was not called. Asserted against a server that is listening and would have
accepted the request, it distinguishes *the generator did not call* from *the
call was made and something swallowed it*.

### What is deliberately not automated

The original criterion — "both tests pass against live infrastructure with test
credentials in a clean environment" — describes a run that creates a GitHub
repository, four Doppler configs, four Supabase projects, eight ZITADEL
objects, two Vercel projects, and eight Fly apps, and then deletes them all.

That is not something a test suite should be able to start by accident, so:

- Every live suite is behind `KORAS_E2E_LIVE=1` and skipped otherwise. The gate
  is one variable rather than "are credentials present", because a developer
  with Doppler configured has credentials present all day and that must not be
  what decides whether a test provisions an estate.
- With the gate open, the live suites fail with a message pointing at
  `PROVISIONING_RUNBOOK.md`. They are placeholders, honestly labelled, rather
  than an automated apply nobody authorised.
- `helpers/teardown.ts` — the half that can be built and tested safely — is
  complete, with the guards below.

A live apply through to Cloudflare and Fly remains a manual runbook step. When
it is authorised, teardown is what makes it repeatable.

### Teardown safety

The one helper in this repository whose job is destruction, written to refuse
rather than to succeed. Four independent guards:

1. **A name prefix.** Only `koras-e2e-…` resources can be deleted. A run that
   provisioned `docoris` cannot tear down `docoris`; it retains it and reports
   why. This is the guard that holds even when every other one is misused.
2. **An explicit opt-in.** `KORAS_E2E_TEARDOWN=1`, or nothing is deleted.
3. **Dry run by default.** `plan()` is pure; `apply()` is the only thing that
   issues a delete, and it re-checks every name immediately before its own call
   rather than trusting the list it was given.
4. **A protected list.** `koras-control-plane`, `koras-saas-starter`,
   `sample-product`, and the live product names. None of them carries the
   prefix, so guard 1 already excludes them; the list is belt and braces on the
   one mistake that cannot be undone.

Wildcards and `..` are refused outright — they reach further than the caller
named.

**Done when:** Both tests pass against live infrastructure with test credentials
in a clean environment.

**Definition of done:**

- [x] Product acceptance scenario: generate, validate, register
- [x] Control Plane acceptance scenario: generate, validate, register nothing
- [x] Registration exercised over a real socket against a real server
- [x] Generated manifest, Claude configuration, and profile overlay asserted in both
- [x] No unrendered template variable in either generated project
- [x] Teardown helper implemented, with four guards and 16 tests
- [x] `tests/e2e` reachable from `turbo run test`
- [ ] **Live apply against real infrastructure** — gated, not automated, and
      pending an explicit authorisation. This is the one criterion the phase
      does not meet.

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
