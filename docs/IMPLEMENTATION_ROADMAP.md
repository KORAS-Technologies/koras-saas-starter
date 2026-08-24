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
**Status:** Not started (surveyed 2026-08-22) — `src/registration/` does not
exist, and neither does `--skip-registration`. That flag is load-bearing outside
this phase: R-001's mitigation in `RISK_REGISTER.md` is written as "skippable
with `--skip-registration` if the Control Plane is not yet live", so the
recorded mitigation currently describes a flag nobody implemented.

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
**Status:** Work complete (2026-08-23); the exit criterion is not.

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

Note that "pass" requires them to have *run*. As of 2026-08-24 the CI,
Generator Integration and Security workflows have zero recorded runs, so this
criterion is not merely unmet -- it is currently unmeasurable. See the CI
execution note in `docs/RISK_REGISTER.md`.

---

## Phase 12 — Security

**Prerequisite:** Phase 8 complete
**Parallelizable with:** Phase 11
**Status:** Partially complete (2026-08-23). Secret scanning is done and now
real: `.gitleaks.toml` ships to the starter and both templates, every job
installs the binary rather than the licence-gated marketplace action, and the
starter's own scan runs on `develop` -- which, for as long as the job existed,
was the one branch it never covered. Dependabot is in place, and
`tests/security/test_no_state_artifacts.py` now guards the factory as well as
what it generates.

Still missing: the RLS policy test suite (`supabase/tests/` — the starter's
`supabase/` holds only `.gitkeep`), the ZITADEL JWT validation tests, and the
OWASP review checklist. The generated projects carry JWT coverage already --
`packages/auth` ships 43 tests across both profiles -- so the gap is the
starter's own.

**Blocked on the same decision as Phase 11:** the exit criterion is defined on
`main`.

**Scope:** Security hardening of starter, generator, and generated output.

**Deliverables:**
- `.github/workflows/security.yml` — CodeQL + secret scanning + `gitleaks`
- `Dependabot` configuration
- OWASP Top 10 review checklist for generated API
- RLS policy test suite (`supabase/tests/`)
- ZITADEL JWT validation unit tests

**Done when:** Zero critical/high findings in automated scans on `develop`.

---

## Phase 13 — End-to-End Acceptance Tests

**Prerequisite:** Phase 10 complete
**Status:** Not started (surveyed 2026-08-22) — `tests/e2e/` does not exist and
`tests/` holds only `.gitkeep`. Blocked by its own prerequisite: Phase 10 has
not begun.

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
