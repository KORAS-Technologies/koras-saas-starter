# KORAS SaaS Starter — Provisioning Runbook

How to take a project from nothing to provisioned infrastructure, and what to
do when a step fails.

Every command here is run from the starter repository root. Credentials come
from Doppler and never touch disk: the CLIs re-run themselves under
`doppler run` when a step needs secrets and the environment does not already
carry them, so no wrapper has to be typed.

---

## 1. The command sequence

```bash
# 0. Confirm the estate is ready. Read-only; creates nothing.
pnpm koras bootstrap:doctor

# 1. Generate the project. No infrastructure is touched.
pnpm create-koras-app <name> --profile <product|control-plane> --output-dir ../output

# 2. Plan. Writes the project, stops after `terraform plan`.
pnpm create-koras-app <name> --profile <profile> --provision --dry-run --output-dir ../output

# 3. Apply. Requires typing `yes` in full — `y` and `Y` are refusals.
pnpm create-koras-app <name> --profile <profile> --provision --output-dir ../output

# 4. Retry after a partial failure. Skips generation, keeps existing state.
pnpm create-koras-app <name> --profile <profile> --provision-only --output-dir ../output
```

Notes that matter:

- **`--output-dir` is effectively required.** Generating with no output
  directory would write a full project into the starter repository, so that is
  refused.
- **`--provision --dry-run` writes the project to disk.** Terraform can only
  plan a configuration that exists; the dry run applies to the infrastructure,
  not the files.
- **Step 3 refuses to overwrite an existing directory.** After a failed run the
  project is already on disk, which is why step 4 exists — it is the normal
  path, not an exception.
- **Never skip step 0.** Every failure in the table below was found *during*
  an apply, after other providers had already created real resources.
- **Doppler is invoked for you.** Steps 0, 2, 3, and 4 need the bootstrap
  secrets, so each re-runs itself as `doppler run --project
  koras-platform-bootstrap --config prod -- <the same command>` and says so on
  stdout. Step 1 needs no credentials and is never wrapped. Wrapping by hand
  still works and is not applied twice; `DOPPLER_PROJECT` and `DOPPLER_CONFIG`
  override the location for a one-off run.

---

## 2. Estate prerequisites

These are properties of the KORAS accounts, not of any one project. Get them
right once.

### Doppler

Project `koras-platform-bootstrap`, config `prod`, holding every key listed in
BOOTSTRAP_DOCTOR.md. Doppler is the sole secret authority: nothing is committed,
and no `.env` participates in provisioning.

No Doppler scope is configured for this repository, which is why every
invocation — the CLIs' own and any you type — passes `--project` and `--config`
explicitly. A bare `doppler run` here fails with "You must specify a project".
`doppler setup --project koras-platform-bootstrap --config prod` binds the
scope per directory if you would rather not repeat the flags in ad-hoc commands.

Two of those keys are read after Terraform rather than by it, and only on a
product run:

| Key | Purpose |
|-----|---------|
| `KORAS_CONTROL_PLANE_URL` | Where the Control Plane is, e.g. `https://control-plane.koras.io` |
| `KORAS_CONTROL_PLANE_TOKEN` | Bearer token the Control Plane issues to the factory |

Neither is required. Absent a URL, a product is provisioned and simply not
registered, which is the documented bootstrap order for the first project in a
new estate (R-001) and exits 0. Present a URL without a token, provisioning
still succeeds but registration fails as a misconfiguration — set both or
neither.

`--control-plane-url` overrides the URL for one run; the token has no flag, and
is not to be passed on a command line.

### GitHub

A fine-grained token whose **resource owner is the organization** — this cannot
be changed after creation — approved by an org owner, with:

| Scope | Permission | Needed for |
|---|---|---|
| Organization | Administration: Read and write | creating the repository |
| Repository | Administration: Read and write | default branch, branch protection |
| Repository | Contents: Read and write | creating the four branches |
| Repository | Environments: Read and write | the four deployment environments |
| Repository | Metadata: Read | mandatory, automatic |

A classic PAT with `repo` scope covers all of these, where org policy allows one.

### Vercel

The **Vercel GitHub App must be installed on the organization**, not only on the
personal account that connected it. Vercel imports every project from a GitHub
repository; without this it reports `repo_not_found` for a repository that
plainly exists.

### HCP Terraform

The workspace's execution mode must be **Local**. Remote execution runs
Terraform on HCP servers, where Doppler-injected credentials do not exist, and
forbids `plan -out` — which the approval gate depends on, so that the plan an
operator approves is exactly the plan that applies. Set the organization default
to Local as well.

### Cloudflare

A token with **Zone:Read** and **DNS:Edit** on the zone named by
`TF_VAR_CLOUDFLARE_ZONE_ID`, which must be the *Zone* ID from the zone's
Overview page — not the Account ID. `enable_waf` defaults to false because the
OWASP Core Ruleset requires a Pro plan.

### Supabase, Fly.io, ZITADEL

Organization identifiers, four database passwords, and one domain plus one
service-account key per ZITADEL instance. All are listed in
BOOTSTRAP_DOCTOR.md and validated by the doctor.

---

## 3. When it fails

Terraform state holds everything created so far, so a retry continues rather
than restarting. Fix the cause, then run step 4.

| Symptom | Cause | Fix |
|---|---|---|
| `403 Resource not accessible by personal access token` on `POST /orgs/{org}/repos` | Token has no access to the organization | Reissue with the org as resource owner; org Administration: RW |
| `403` on `GET /repos/{org}/{repo}/git/ref/heads/main` | Token lacks repository **Contents** | Add Contents: Read and write |
| `403` creating `github_repository_environment` | Token lacks repository **Environments** | Add Environments: Read and write |
| Vercel `repo_not_found` for a repository that exists | Vercel GitHub App not installed on the org | Install it for the organization |
| `Invalid Attribute Value Match` on a Vercel or Fly name | Fixed — component keys are hyphenated in the modules | Update the generated project's `modules/` copy, or regenerate |
| `pipefail: invalid option name` from `make` | Fixed — shell scripts are pinned to LF | Regenerate, or convert CRLF to LF in place |
| Workspace runs in `remote` execution mode | HCP default | Workspace → Settings → General → Execution Mode → Local |
| `Terraform cannot run — N required inputs missing` | Doppler ran but returned nothing — wrong config, expired token, or no access | The message names every missing input. Confirm with `doppler secrets --project koras-platform-bootstrap --config prod` |
| `Doppler Error: You must specify a project` | A bare `doppler run` in a directory with no Doppler scope | The documented commands always pass `--project` and `--config`; pass them for ad-hoc commands too, or run `doppler setup` once |
| `uv sync`: workspace member is missing a `pyproject.toml` | Fixed — every service now ships one | Regenerate |
| `unmet peer react@…` from `next` | Fixed — Next is a range compatible with React 19 | Regenerate |
| `Bind for 0.0.0.0:<port> failed: port is already allocated` | A container elsewhere holds the port — a second KORAS project, or a Supabase CLI stack | Fixed — host ports are resolved per machine. On an existing project run `make ports`, then `make dev` |
| `bind: An attempt was made to access a socket in a way forbidden by its access permissions` | A Windows kernel reservation, not a listener: `http.sys` (IIS on 80, SSRS on 8082) or a WinNAT exclusion range | Same fix. `netsh http show urlacl` names the owner; `netsh interface ipv4 show excludedportrange protocol=tcp` lists the reserved ranges |
| `EADDRINUSE :::3000` from `next dev` | Another project's dev server holds the port | Fixed — app ports resolve through `local/.env` too. `make ports` re-resolves |
| `Error acquiring the state lock` | A plan or apply was killed before it could release the workspace | The command now prints the exact `terraform force-unlock` line. For `backend "remote"` the lock ID is `<org>/<workspace>` — **not** the UUID under `Lock Info:` |
| `turbo run build` fails across many packages at once with `VirtualAlloc failed`, `STATUS_DLL_INIT_FAILED`, zone-allocation failures, or "out of memory" at a heap of a few MB | Not a build error. Turbo runs roughly one task per core and each `tsc` reserves hundreds of MB of commit; on a machine already running a local stack the Windows **commit limit** is exhausted and the tasks fail together, each reporting whichever allocation lost | `make build` caps this via `BUILD_CONCURRENCY` (default 4); lower it, or run `pnpm turbo run build --concurrency=2`. Check headroom with `Get-CimInstance Win32_OperatingSystem` — commit in use versus limit, not free RAM. Stopping an unused `docker compose` stack and `wsl --shutdown` both free a lot |
| A `local/scripts/*.sh` reports a tool "is not installed" that plainly is | On Windows, `bash` from PowerShell resolves to `C:\WINDOWS\system32ash.exe` — the **WSL** launcher, a separate Linux filesystem that cannot see a winget or Scoop install on the Windows side | Run it under Git Bash: `& "C:/Program Files/Git/bin/bash.exe" <script>`. `make` targets are unaffected — make resolves `bash` itself and finds Git Bash |
| `spawn pnpm ENOENT` during git initialisation | Fixed — `pnpm` is a `.cmd` shim on Windows, which needs a shell | Update the starter and rebuild: `pnpm --filter create-koras-app build` |

### The generated project owns its own modules

`infrastructure/terraform/modules/` is copied into every generated project, so
fixing a module in the starter does **not** fix a project already on disk.
That is deliberate — it is what makes `--provision-only` reproducible, since the
plan reflects the code in the project rather than whatever the starter contains
today. The cost is that a stale copy plans perfectly happily and fails at apply.

To see what has diverged before changing anything — read-only, exits 1 on
differences, so CI can gate on it:

```bash
pnpm create-koras-app <name> --profile <profile> --check-drift --output-dir ../output
```

Add `--all` to also list workflows, `local/`, the Makefile and the other
generator-owned files that differ. Those are reported separately and never
change the exit code — a healthy project edits them, and a replaced stub looks
the same as a missing fix.

It compares the components recorded in `.koras/project.yaml` against
`terraform.tfvars`, and the generator-owned root Terraform config against a
fresh render. A component key is a Terraform `for_each` key, so a rename applied
to one record and not the other plans a destroy rather than a rename — which is
the failure this exists to catch before a plan runs.

`--refresh-modules` re-copies exactly those directories and nothing else:

```bash
# See what would change; writes nothing.
pnpm create-koras-app <name> --profile <profile> --refresh-modules --dry-run --output-dir ../output

# Refresh, then plan and apply against the refreshed copy.
pnpm create-koras-app <name> --profile <profile> --refresh-modules --provision-only --output-dir ../output
```

It names every file it replaces, is a no-op when the copies already match, and
does not imply `--provision` on its own — refreshing source files should not
quietly become an infrastructure run. Only paths the profile declares as shared
assets are touched, so nothing you edited inside your own project is at risk.

---

## 4. What provisioning creates

Per project, for the product profile with default components:

```text
GitHub     1 repository, 4 branches, 1 default branch, 4 protections, 4 environments
Doppler    1 project, 4 configs
Supabase   4 projects (one per environment)
Upstash    4 Redis databases (one per environment; prevent_destroy is set)
ZITADEL    4 projects, 4 OIDC applications (no environment suffix — the instance is the environment)
Vercel     1 project per enabled application
Fly.io     1 app per enabled service per environment
Cloudflare 0 by default — WAF off, DNS deferred
```

The control-plane profile differs only in its component set: two applications
(`platform_admin`, `portal`), three services, and no AI Gateway.

---

## 5. Related documents

| Document | Purpose |
|---|---|
| `BOOTSTRAP_DOCTOR.md` | What each doctor check verifies, and what it cannot |
| `PRODUCT_GENERATOR_PLAN.md` | Generator CLI design, flags, project manifest |
| `INFRASTRUCTURE_PLAN.md` | Terraform module strategy |
| `ENVIRONMENT_STRATEGY.md` | Branch ↔ environment mapping |
