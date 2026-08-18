# KORAS SaaS Starter — Provisioning Runbook

How to take a project from nothing to provisioned infrastructure, and what to
do when a step fails.

Every command here is run from the starter repository root, under `doppler run`
so that credentials reach the process without ever touching disk.

---

## 1. The command sequence

```bash
# 0. Confirm the estate is ready. Read-only; creates nothing.
doppler run --project koras-platform-bootstrap --config prod -- \
  pnpm koras bootstrap:doctor

# 1. Generate the project. No infrastructure is touched.
pnpm create-koras-app <name> --profile <product|control-plane> --output-dir ../output

# 2. Plan. Writes the project, stops after `terraform plan`.
doppler run --project koras-platform-bootstrap --config prod -- \
  pnpm create-koras-app <name> --profile <profile> --provision --dry-run --output-dir ../output

# 3. Apply. Requires typing `yes` in full — `y` and `Y` are refusals.
doppler run --project koras-platform-bootstrap --config prod -- \
  pnpm create-koras-app <name> --profile <profile> --provision --output-dir ../output

# 4. Retry after a partial failure. Skips generation, keeps existing state.
doppler run --project koras-platform-bootstrap --config prod -- \
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

---

## 2. Estate prerequisites

These are properties of the KORAS accounts, not of any one project. Get them
right once.

### Doppler

Project `koras-platform-bootstrap`, config `prod`, holding every key listed in
BOOTSTRAP_DOCTOR.md. Doppler is the sole secret authority: nothing is committed,
and no `.env` participates in provisioning.

No Doppler scope is configured for this repository, so `--project` and
`--config` must be passed explicitly. `doppler setup` would remove the need.

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
| `Terraform cannot run — N required inputs missing` | Not running under `doppler run` | Wrap the command; the message now says which case applies |
| `uv sync`: workspace member is missing a `pyproject.toml` | Fixed — every service now ships one | Regenerate |
| `unmet peer react@…` from `next` | Fixed — Next is a range compatible with React 19 | Regenerate |
| `Bind for 0.0.0.0:54322 failed: port is already allocated` | Another stack holds the port — a second KORAS project, or a Supabase CLI stack | Stop the other stack; generated projects use fixed host ports, so only one runs at a time |

### The generated project owns its own modules

`infrastructure/terraform/modules/` is copied into every generated project, so
fixing a module in the starter does **not** fix a project already on disk.
Either regenerate, or copy the changed module across — `--provision-only` reads
the project on disk.

---

## 4. What provisioning creates

Per project, for the product profile with default components:

```text
GitHub     1 repository, 4 branches, 1 default branch, 4 protections, 4 environments
Doppler    1 project, 4 configs
Supabase   4 projects (one per environment)
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
