# KORAS SaaS Starter — Product Generator Plan

## Purpose

This document specifies the design of the `create-koras-app` CLI generator:
its commands, argument model, interactive mode, generation engine, safety
constraints, and test coverage expectations.

---

## 1. Binary

The generator is a TypeScript CLI published as part of the `koras-saas-starter`
monorepo at:

```
generators/create-koras-app/
```

Installed and invoked via pnpm:

```
pnpm create-koras-app [project] [options]
```

---

## 2. Commands

### Non-interactive (CI/automation)

```bash
# Generate source only, no provisioning
pnpm create-koras-app docoris --profile product --output-dir ../output

# Generate + provision infrastructure (requires explicit approval)
pnpm create-koras-app docoris --profile product --provision --output-dir ../output

# Dry run — print what would be generated without writing files
pnpm create-koras-app docoris --profile product --dry-run --output-dir ../output

# Control Plane generation
pnpm create-koras-app koras-control-plane --profile control-plane --output-dir ../output

# Control Plane with provisioning
pnpm create-koras-app koras-control-plane --profile control-plane --provision --output-dir ../output
```

`--output-dir` is effectively required: generating with no output directory
would write a full project into the starter repository, which is refused.

No `doppler run` wrapper is needed. `--provision` and `--provision-only` need
the bootstrap secrets, so the CLI re-runs itself under `doppler run` at the
location the profile declares (`infrastructure.doppler_project` /
`doppler_config`), and says so before it does. Plain generation needs no
credentials and is never wrapped.

### Utility

```bash
pnpm create-koras-app --help
pnpm create-koras-app --list-profiles
```

### Interactive (no arguments)

```bash
pnpm create-koras-app
```

Prompts:

```
? Project name:   docoris
? Project slug:   docoris
? Project profile:
  ❯ product
    control-plane
```

Profile is NEVER inferred from project name. The operator must choose explicitly.

---

## 3. Argument Reference

| Argument / Flag     | Required    | Description                                         |
|---------------------|-------------|-----------------------------------------------------|
| `project`           | Positional  | Project name (becomes directory name + slug base)   |
| `--profile`         | Required    | `product` or `control-plane`                        |
| `--with`            | Optional    | Enable optional components (comma-separated manifest keys) |
| `--without`         | Optional    | Disable optional components (comma-separated manifest keys) |
| `--provision`       | Optional    | Run Terraform bootstrap after generation            |
| `--dry-run`         | Optional    | Print generation plan without writing files         |
| `--output-dir`      | Optional    | Parent directory for generated project (default: cwd) |
| `--no-interactive`  | Optional    | Disable interactive prompts; error if required args missing |
| `--help`            | Optional    | Print help and exit                                 |
| `--list-profiles`   | Optional    | List available profiles and exit                    |

---

## 4. Generation Engine

### Context assembly

Before rendering any file, the generator assembles a `GenerationContext`:

```typescript
interface GenerationContext {
  projectName: string;      // "Docoris"
  projectSlug: string;      // "docoris"
  profile: ProfileManifest; // loaded from profiles/<name>/manifest.yaml
  defaults: ProfileDefaults; // loaded from profiles/<name>/defaults.yaml
  selections: ComponentSelections; // which optional components are enabled
  outputDir: string;
  dryRun: boolean;
  provision: boolean;
}
```

### Template rendering

- Templates use [Handlebars](https://handlebarsjs.com/) (or equivalent)
- Template variables: `{{projectName}}`, `{{projectSlug}}`, `{{profile}}`, etc.
- Conditional blocks driven by `selections`, never by inline profile checks
- Every file in `profiles/<profile>/template/` is either copied verbatim or
  rendered if it ends in `.hbs`

### File writer

The writer enforces:
1. Check if output directory already exists → abort with error
2. Check each file path — never silently overwrite
3. In dry-run mode: print file list, write nothing
4. In normal mode: write atomically (temp file + rename)

---

## 5. Interactive Component Selection

When running interactively with `--profile product`, optional components are
offered as multi-select prompts:

```
? Select optional applications:
  ◉ admin
  ◉ marketing

? Select optional services:
  ◯ worker
  ◯ scheduler
  ◉ ai-gateway

? Select optional capabilities:
  ◉ billing
  ◉ custom domains
  ◉ white labeling
```

With `--profile control-plane`, all required components are included and no
optional component prompts appear (worker and scheduler are always required
for control-plane).

---

## 6. Slug Validation Rules

```
- 2–50 characters
- Lowercase letters, digits, hyphens only
- Must begin with a letter
- Must end with a letter or digit
- No consecutive hyphens
- Not a reserved word: koras, api, admin, www, mail, auth, ...
```

If `project` is provided but `slug` is not prompted, slug is derived from
`project` by lowercasing and replacing non-alphanumeric characters with hyphens,
then validated. If derived slug fails validation, the operator is prompted to
provide one manually.

---

## 7. Conflict Detection

Before writing a single file:

1. **Local directory** — if `<output-dir>/<project>` exists, abort.
2. **GitHub repository** — if `--provision` is requested, check whether
   `<github-org>/<project>` already exists via the GitHub API. Abort if found.
3. **Terraform state** — if `--provision`, check whether Terraform state for
   this project already exists in the configured backend. Abort if found.

All conflict errors must:
- Name the exact resource that conflicts
- Explain how to resolve it
- Never silently continue

---

## 8. Provisioning Flow

When `--provision` is passed:

```
1. Generate source files
2. Validate all inputs
3. Run: terraform init
4. Run: terraform plan
5. Display plan output to operator
6. Prompt: "Apply infrastructure changes? [yes/no]"
7. If yes: terraform apply
8. If no: exit 0 with message "Provisioning cancelled."
9. Extract Terraform outputs (infrastructure references)
10. If profile=product: POST to Control Plane registration endpoint
11. Print summary of all created resources
```

`--provision` combined with `--dry-run` runs steps 1–5 and exits. No apply.
No registration.

---

## 9. Dry-Run Output Format

```
KORAS Generator — Dry Run
Profile:  product
Project:  docoris
Slug:     docoris
Output:   /repos/docoris
Apps:     web, admin
Services: api, worker
Register: yes
Manifest: docoris/.koras/project.yaml

FILES TO CREATE (47 files):
  docoris/.github/workflows/ci.yml
  docoris/.gitignore
  docoris/.koras/project.yaml
  docoris/CLAUDE.md
  docoris/Makefile
  ...

TERRAFORM PLAN (--provision requested):
  [terraform plan output here]

No files were written. Remove --dry-run to proceed.
```

---

## 10. Error Messages

All errors must be:
- Specific about what went wrong
- Actionable — tell the operator exactly how to fix it

Examples:

```
ERROR: Directory already exists: /repos/docoris
  Remove the directory or choose a different project name.

ERROR: Invalid slug "my_project"
  Slugs may only contain lowercase letters, digits, and hyphens.
  Suggestion: my-project

ERROR: Unknown profile "saas"
  Available profiles: product, control-plane
  Run: pnpm create-koras-app --list-profiles

ERROR: GitHub repository already exists: koras-org/docoris
  Delete the repository or choose a different project name.

ERROR: --profile is required in non-interactive mode.
  Example: pnpm create-koras-app docoris --profile product
```

---

## 11. `--list-profiles` Output

```
Available profiles:

  product         Standard KORAS SaaS product
                  Applications: web (required), admin (optional), marketing (optional)
                  Services:     api (required), worker, scheduler, ai-gateway (optional)
                  Registers with Control Plane: yes

  control-plane   KORAS Control Plane — platform provisioning authority
                  Applications: admin/platform (required), portal (required)
                  Services:     api, worker, scheduler (all required)
                  Registers with Control Plane: no
```

---

## 12. `--help` Output

```
create-koras-app — KORAS Application Factory

USAGE:
  pnpm create-koras-app [project] [options]

ARGUMENTS:
  project                    Project name

OPTIONS:
  --profile <profile>        Generator profile (required in non-interactive mode)
  --with <components>        Enable optional components (comma-separated)
  --without <components>     Disable optional components (comma-separated)
  --provision                Provision infrastructure via Terraform
  --dry-run                  Preview generation without writing files
  --output-dir <path>        Output parent directory (default: current directory)
  --no-interactive           Disable interactive prompts
  --list-profiles            List available profiles and exit
  --help                     Show this help message

EXAMPLES:
  pnpm create-koras-app
  pnpm create-koras-app docoris --profile product
  pnpm create-koras-app docoris --profile product --provision
  pnpm create-koras-app docoris --profile product --dry-run
  pnpm create-koras-app docoris --profile product --with marketing,ai_gateway
  pnpm create-koras-app koras-control-plane --profile control-plane
  pnpm create-koras-app koras-control-plane --profile control-plane --provision
```

---

## 13. Generator Source Layout

```
generators/create-koras-app/
├── src/
│   ├── cli/
│   │   ├── index.ts          entrypoint, arg parsing
│   │   ├── args.ts           argument definitions and validation
│   │   └── interactive.ts    prompts (inquirer / clack)
│   │
│   ├── profiles/
│   │   ├── loader.ts         reads and parses manifest.yaml + defaults.yaml
│   │   ├── validator.ts      validates manifest structure against schema
│   │   └── types.ts          ProfileManifest, ProfileDefaults, ComponentSelections
│   │
│   ├── generation/
│   │   ├── engine.ts         template renderer (Handlebars)
│   │   ├── context.ts        GenerationContext builder
│   │   ├── project-manifest.ts  builds/validates/serializes .koras/project.yaml
│   │   └── writer.ts         safe atomic file writer
│   │
│   ├── validation/
│   │   ├── slug.ts           slug format validation
│   │   ├── profile.ts        profile name validation
│   │   ├── generated-project.ts  post-write check of .koras/project.yaml
│   │   └── conflicts.ts      directory, GitHub, Terraform conflict checks
│   │
│   ├── terraform/
│   │   ├── runner.ts         terraform init/plan/apply orchestration
│   │   ├── inputs.ts         variable assembly from GenerationContext
│   │   ├── outputs.ts        post-apply reference extraction
│   │   └── approval.ts       human confirmation prompt
│   │
│   └── registration/
│       ├── client.ts         HTTP POST to Control Plane
│       ├── contract.ts       registration payload types
│       └── guard.ts          profile check — skip if control-plane
│
├── bin/
│   └── create-koras-app.js   CLI binary (compiled)
│
├── tests/
│   ├── cli.test.ts
│   ├── generation.test.ts
│   ├── validation.test.ts
│   ├── profile-loader.test.ts
│   └── registration.test.ts
│
├── package.json
└── tsconfig.json
```

---

## 14. Test Cases

All generator tests must run without external services (mocked Terraform,
mocked GitHub API, mocked Control Plane).

### Profile loading
- Profile `product` loads correctly
- Profile `control-plane` loads correctly
- Unknown profile name returns validation error

### Generation — product
- `apps/web` is generated
- `apps/admin` is generated when selected
- `apps/admin` is absent when not selected
- `services/ai-gateway` is generated when selected
- `services/ai-gateway` is absent when not selected
- Registration payload is generated
- Control Plane client package is included

### Generation — control-plane
- `apps/admin` (platform-admin variant) is generated
- `apps/portal` is generated
- `apps/web` is absent
- `apps/marketing` is absent
- `services/ai-gateway` is absent
- No registration payload is generated
- No Control Plane client dependency is present

### Naming conventions
- Doppler project names: `<slug>-dev`, `<slug>-test`, `<slug>-stg`, `<slug>-prod`
- Supabase project names: `<slug>-dev`, `<slug>-test`, `<slug>-stg`, `<slug>-prod`
- ZITADEL project name: `<slug>` (no env suffix)
- Fly app names: `<slug>-api-dev`, `<slug>-api-test`, etc.

### Safety
- Existing directory causes abort
- Dry-run writes no files
- `--provision` without approval exits cleanly
- No secret values appear in registration payload

### CLI
- `--help` outputs help text and exits 0
- `--list-profiles` lists both profiles and exits 0
- Missing `--profile` in `--no-interactive` mode produces actionable error

---

## 15. Generated Project Manifest — `.koras/project.yaml`

Every generated repository, whatever its profile, contains a machine-readable
KORAS project manifest at exactly:

```
.koras/project.yaml
```

The generator creates the `.koras/` directory itself. The path is canonical:
the manifest is never written under `config/`, `docs/`, or `infrastructure/`.

### Purpose

The manifest is the authoritative answer to *what is this repository, and what
produced it*. Before it existed, the only machine-readable identity in a
generated project was `infrastructure/terraform/terraform.tfvars` — a
provisioning input, not an identity record.

It is a stable KORAS platform contract, consumed by:

```
pnpm koras doctor
pnpm koras bootstrap:doctor   implemented — see BOOTSTRAP_DOCTOR.md
pnpm koras upgrade
pnpm koras diff-starter
pnpm koras project:info
```

and by Control Plane registration tooling, which gates on `project.profile`
before running platform-only work.

`bootstrap:doctor` is the one that exists today. It checks the estate rather
than a generated project, so it does not read this manifest yet; the remaining
commands will.

It holds **references only** — never secrets, credentials, or endpoints. It is
safe to commit, and the generated `.gitignore` deliberately does not exclude it.

### Fields

| Field | Source |
|-------|--------|
| `schema_version` | Fixed at `1`. Only changes with a manifest migration design. |
| `project.name` | Project name as supplied to the CLI |
| `project.slug` | Normalized, machine-safe slug (see §6) |
| `project.profile` | `product` or `control-plane` |
| `generator.name` | Always `create-koras-app` |
| `generator.starter_version` | Root `package.json` `version` of the starter |
| `generator.profile_version` | `version` in the selected `profiles/<profile>/manifest.yaml` |

Field order is fixed — `schema_version`, `project`, `generator` — and
serialization is deterministic: the same generation context always produces a
byte-identical file.

### Versioning

`starter_version` and `profile_version` are independent and both semver:

```
starter_version = version of KORAS SaaS Starter   (root package.json)
profile_version = version of the selected profile (profiles/<p>/manifest.yaml)
```

A starter bug fix raises `starter_version` without touching profile behaviour.
A breaking change to a profile's generated structure raises that profile's
`profile_version`. Neither is hard-coded in generator logic; both are resolved
from metadata at generation time, and generation **fails** rather than emitting
a placeholder such as `unknown`, `latest`, or `TBD`.

### Example — product

```bash
pnpm create-koras-app docoris --profile product
```

```yaml
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

Non-interactive generation takes the project name verbatim and derives the slug
from it, so `docoris` yields `name: docoris`. Interactive mode is where a
display name and slug diverge (`Docoris` / `docoris`); the slug is always
normalized.

### Example — control-plane

```bash
pnpm create-koras-app koras-control-plane --profile control-plane
```

```yaml
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

### Generation order and validation

The manifest is built after the repository structure and written as part of the
same generation transaction:

```
parse args → resolve name/slug → resolve profile → load profile manifest
  → resolve starter version → resolve profile version → validate configuration
  → generate repository structure → generate .koras/project.yaml
  → validate generated repository → complete
```

Two validation layers apply:

1. **On write** — `KorasProjectManifestSchema` (Zod) rejects an unsupported
   `schema_version`, an empty name or slug, an unknown profile, a wrong
   generator name, or a non-semver version. An unsupported profile reaching the
   generation layer is an error, never a written manifest.
2. **After write** — the generated project is re-validated by reading the file
   back from disk: it must exist, parse as YAML, carry a supported schema
   version and both versions, and record the profile and slug that were
   actually requested. Generation fails, and nothing is provisioned, if it does
   not. Reading back from disk rather than trusting memory is the point: it
   proves that what downstream tooling will read is correct.

The profile check matters most for the Control Plane. A `--profile
control-plane` run that produced `profile: product` would let later tooling run
product provisioning against the platform authority, so it is covered by a
regression test.

### Future compatibility

`schema_version: 1` is not to be changed without an explicit migration design.
Fields such as `environments`, `features`, and `infrastructure` may be added in
future schema versions; they are deliberately absent now.
