# KORAS SaaS Starter — Provisioning Runbook

How to take a project from nothing to provisioned infrastructure, and what to
do when a step fails.

Every command here is run from the starter repository root. Credentials come
from Doppler and never touch disk: the CLIs re-run themselves under
`doppler run` when a step needs secrets and the environment does not already
carry them, so no wrapper has to be typed.

---

## 1. The command sequence

Provisioning is below; **tearing down is §5**, and applies only to projects
named `koras-e2e-...`.

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

# --- the apply is done; the project cannot deploy anything yet ---

cd ../output/<name>

# 5. Create the restricted database role, once per environment. Keep both URLs.
bash local/scripts/create-app-role.sh "<privileged database url>"

# 6. See what Doppler will be asked for. Writes nothing.
bash local/scripts/doppler-bootstrap.sh --dry-run

# 7. Populate dev, test and stg, then prod. Two targets, deliberately.
make doppler-bootstrap
make doppler-bootstrap-prod

# 8. Confirm every environment holds every setting. Names only, never values.
make doppler-check
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
- **Steps 5 to 8 are not optional, and provisioning does not do them.**
  Terraform creates the Doppler *project* and its four configs; it never writes
  a setting into them. It cannot: it does not know the Supabase password or the
  ZITADEL service token, and a value it could derive is still one it has no
  reason to write. So an apply that succeeds completely leaves every Doppler
  config empty, and the first sign is an empty Secrets tab rather than an error.
  This section stopped at step 4 until someone provisioned an estate and asked
  why nothing was there.
- **Step 5 comes before step 6 for a reason.** `doppler-bootstrap` prompts for
  `DATABASE_URL` and `DATABASE_ADMIN_URL`; both are outputs of
  `create-app-role.sh`. Run them the other way round and you are being asked for
  values that do not exist yet.
- **`make doppler-bootstrap` skips `prod` deliberately**, and
  `make doppler-bootstrap --environment prod` does not reach the script — make
  consumes the option and reads `prod` as a target name, so the default set runs
  and production is silently skipped. That is why step 7 is two commands.
  Anything else the script accepts — `--dry-run`, `--outputs`, `--overwrite` —
  has to be passed to the script directly.
- **Doppler is invoked for you.** Steps 0, 2, 3 and 4 need the bootstrap
  secrets, and so does `koras teardown` in §5, so each re-runs itself as
  `doppler run --project koras-platform-bootstrap --config prod -- <the same
  command>` and says so on stdout. **No command in this document should be typed
  with that wrapper.** Step 1 needs no credentials and is never wrapped. Wrapping by hand
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

### The application database role — once per environment

Row-level security does not apply to a superuser, and does not apply to a role
holding BYPASSRLS. `force row level security` binds the table *owner* and
neither of those. Supabase issues a privileged role as the default credential,
so a `DATABASE_URL` taken from its dashboard gives a service correct policies,
`force` on every table, a passing policy suite, and **no tenant isolation at
all**. See R-032.

So the privileged credential migrates and a restricted one serves:

| Doppler secret | Role | Used by |
|----------------|------|---------|
| `DATABASE_ADMIN_URL` | privileged | the deploy's `migrate` job, and nothing else |
| `DATABASE_URL` | `koras_app` | every service |

The names are that way round on purpose. A secret called `DATABASE_ADMIN_URL`
is visibly privileged; a plain `DATABASE_URL` that happens to be a superuser is
the trap this exists to remove. The default name gets the least privilege.

**Not `DATABASE_URL_MIGRATE`**, which is what this was called first.
`local/scripts/migrate.sh` already reads a variable named
`MIGRATE_DATABASE_URL` — the same words in a different order, referred to three
lines apart in the deploy workflow. The first person to read it asked whether
they were the same thing. They are not: `DATABASE_ADMIN_URL` is the Doppler
secret, `MIGRATE_DATABASE_URL` is how `migrate.sh` is pointed at a database, and
the workflow reads the first and passes the second.

For each of the four environments, once:

```bash
# 1. Create the role. Takes the privileged URL; prints the restricted one.
bash local/scripts/create-app-role.sh "<privileged database url>"

# 2. In Doppler, for that config:
#      DATABASE_ADMIN_URL = the privileged URL you just passed
#      DATABASE_URL       = the URL the script printed
```

The script is idempotent: re-running rotates the credential and re-applies the
grants, which is also how to recover from a lost one. It prints the value once
and writes it nowhere.

**Until this is done, deploys fail.** `check-rls-connection.sh` runs in the
`migrate` job, which `services` depends on, so an environment still serving from
the privileged role cannot deploy. That is deliberate — the alternative is a
warning nobody actions, and the thing being warned about is a cross-tenant read.

**`DATABASE_ADMIN_URL` is in `secrets.manifest` but not in
`.env.local.example`.** No service reads it, so it is not part of the local
contract — but a deployed environment does need it, and that is the question
the manifest answers. `doppler-check.sh` therefore demands it in the settings
preflight, before anything is migrated or deployed.

It was left out of the manifest at first, on the reasoning that a setting no
service reads is not a service setting. That was the wrong test: the file's own
header says it records "whether a deployed environment needs it". Omitting it
meant nothing asked for the value until the migrate step, halfway through a
deploy — and the gap was found by someone reading their Doppler config and not
finding the secret the runbook told them to set.

**If Supabase refuses to create the role**, its `postgres` credential is
restricted more than stock Postgres. Create `koras_app` through the Supabase
console or API, then re-run the script — it finds an existing role and applies
the grants rather than trying to create one.

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

**Set `org_id` on every ZITADEL instance, not just the ambiguous ones.** The
module can discover the organization when an instance holds exactly one, and
that fallback is a live API call per instance made on every plan. An instance
that is asleep, restarting, or behind a gateway returning 503 fails the plan for
the whole estate — including the three environments that were fine — on a lookup
whose only purpose is to name organizations in an error message. Naming the org
skips the call entirely.

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
| `/bin/bash: terraform: command not found` and `/mnt/c/...: exec: node: not found` | A `bash -c '...'` command was run from PowerShell, where `bash` is WSL's bash — a different machine with a different PATH. The `/mnt/c/` prefix is the tell | §5 no longer wraps anything in `bash -c`; its commands are the same in both shells. If you are running an older copy of a command, use the current one |
| Vercel `internal_server_error - An unexpected internal error occurred` on *some* projects | Vercel's own 500, not the configuration. Eight projects are created at once and a few can fail under that concurrency; the ones that fail differ only by which they were | Re-run the apply; Terraform creates only what is missing. Seen 2026-08-27: six of eight succeeded, `web-stg` and `admin-stg` failed, and one retry created both with no change to the configuration. Confirmed transient |
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

## 5. Tearing down an acceptance run

Only for products named `koras-e2e-...`. Every guard in `koras teardown` refuses
anything else by name, and a real estate is refused even with deletion enabled.

### Before you start

Three things, none of which the command checks for you:

1. **You are in the starter.** Every command below runs from
   `C:\repos\Projects\koras-saas-starter`. The generated project lives beside
   it, at `../output/<product>/`, and you never `cd` into it.
2. **The project is named `koras-e2e-something`.** The guards refuse every other
   name, deletion enabled or not. This is the safety mechanism, not a
   convention.
3. **`ZITADEL_SERVICE_TOKEN` is set in the bootstrap Doppler project.** If it is
   missing, ZITADEL is *skipped* rather than failed — the run finishes, says so
   once at the top, and looks successful while the projects are still there.

### Step 1 — see what exists, delete nothing

**Run from the starter**, `C:\repos\Projects\koras-saas-starter`. Identical in
Git Bash and PowerShell:

```bash
pnpm koras teardown <product> --product-path ../output/<product>
```

**No `doppler run` wrapper.** Teardown fetches its own credentials by
re-running itself under `doppler run --project koras-platform-bootstrap --config
prod`, exactly as `bootstrap:doctor` does, and says so on stdout when it happens.
An outer wrapper is detected rather than nested, so one typed by hand still
works — it is just never necessary. This was the last command in the repository
still asking for one.

`--product-path` takes the **generated product**, not its Terraform directory.
Teardown appends `infrastructure/terraform` itself and runs
`terraform output -json` there. That is not only about typing: the outputs
include the values of outputs marked sensitive, so they must not reach disk —
and must not reach *stdin* either, which is why they are no longer piped in. See
step 2.

This is a dry run. Not because of a flag you passed, but because
`KORAS_E2E_TEARDOWN` is unset, which is the default — you have to go out of your
way to delete.

**Read the list before going further.** Two things: the count looks like a whole
estate rather than part of one, and nothing is skipped for a missing credential.
A skip is not a warning you can carry forward; it is a provider that will still
exist afterwards.

### Step 2 — delete

The same command with `KORAS_E2E_TEARDOWN=1`.

Git Bash:

```bash
KORAS_E2E_TEARDOWN=1 pnpm koras teardown <product> --product-path ../output/<product>
```

PowerShell — `VAR=1 cmd` is not PowerShell syntax; set it on `$env:` first, and
clear it afterwards so the next dry run is still a dry run:

```powershell
$env:KORAS_E2E_TEARDOWN = "1"
pnpm koras teardown <product> --product-path ../output/<product>
Remove-Item Env:\KORAS_E2E_TEARDOWN
```

It stops and asks you to type the project name. Not `yes` — the name. Anything
else cancels, and there is no `--yes` or `--force` to get past it.

**Do not pipe the outputs in.** This section used to say to, and the command it
gave could not delete anything:

```bash
# the old form -- prints the prompt, then answers it with nothing
terraform -chdir=... output -json | pnpm koras teardown <product> -
```

The JSON arrives on stdin and is read to end-of-file. The prompt then reads the
same stdin, gets the empty string, and cancels. It looked like the command
ignoring the operator. Piping is refused outright when deletion is enabled, with
a message pointing here; `-` still lists, and still suits a script that already
holds the JSON.

One trap if you are assembling a command by hand:
`KORAS_E2E_TEARDOWN=1 terraform ... | pnpm koras ...` sets the variable on
**terraform**, not on teardown — in a pipeline the prefix applies to the first
command only.

### Step 3 — check the consoles yourself, this once

Teardown treats **404 as success**, because a resource that is already gone
satisfies the request and re-running after a partial teardown has to work. The
cost is that "I deleted it" and "it was never there" print the same.

That is fine once the path is proven. It is not fine the first time, because no
deleter here has ever run against a real API — only against a test double. So on
the first live run, open each console and look:

| Provider | What to look for |
|----------|------------------|
| GitHub | the repository is gone |
| Supabase | four projects gone — these bill |
| Upstash | four databases gone — these bill |
| Vercel | the projects are gone |
| Fly.io | the apps are gone |
| Doppler | the project, and its configs with it |
| ZITADEL | the project in **each** instance's console |

ZITADEL is the one to check hardest. Its delete is the newest, and a wrong
organization answers 404 — which reads as success.

### Step 4 — the three things teardown never touches

Four ZITADEL projects, the workspace, and the directory:

```bash
# 1. The four ZITADEL projects, one per instance console. Teardown reports them
#    as skipped for a missing credential -- see the note below and R-036.
# 2. The HCP Terraform workspace, at app.terraform.io. Delete it by hand.
# 3. The generated directory, which is yours:
rm -rf ../output/<product>
```

PowerShell for the last one:

```powershell
Remove-Item -Recurse -Force ../output/<product>
```

### If a step fails

A failure does not stop the rest, and each resource reports its own outcome.
Re-run the same command: an already-deleted resource answers 404, which counts
as success, so a second run finishes what a partial one started.

A resource that fails repeatedly is deleted from its provider's console. The
inventory comes from Terraform's outputs, so the names and ids in the report are
the ones the provider knows it by.

### The two rules worth not forgetting

**Never write the outputs to a file.** `terraform output -json` includes the
values of outputs marked sensitive, so the file it writes holds live credentials
— Upstash URLs with their passwords, ZITADEL client secrets. One was committed
to this public repository on 2026-08-26 and had to be rotated by destroying the
resources it belonged to. R-041.

`--product-path` is how that is avoided now: teardown runs `terraform output
-json` itself and keeps the result in memory. An earlier version of this section
said to pipe instead, which also kept it off disk and had a second problem — the
JSON took stdin, so the confirmation prompt had nothing to read. Piping is
refused for deletion; a file is accepted and remains a bad idea.

**Credentials come from Doppler, and teardown fetches them itself.** It re-execs
under `doppler run --project koras-platform-bootstrap --config prod` the way
`--provision` and `bootstrap:doctor` do, and says so on stdout. **Do not type
that wrapper.** An outer one is detected rather than nested, so one typed by
hand is harmless — it is simply never needed, and every command in this section
is written without it.

It reads `GITHUB_TOKEN`, `DOPPLER_TOKEN`, `SUPABASE_ACCESS_TOKEN`,
`UPSTASH_EMAIL`, `UPSTASH_API_KEY`, `VERCEL_API_TOKEN`, `VERCEL_TEAM_ID` and
`FLY_API_TOKEN`, each also accepted under its `TF_VAR_` spelling — the estate
stores Upstash's two that way, and reading only the bare name is how four
billing databases were once reported as skipped.

**ZITADEL needs four, one per instance**, in `koras-platform-bootstrap/prod`
alongside the `ZITADEL_<ENV>_DOMAIN` and `ZITADEL_<ENV>_ORG_ID` they sit beside:

| Key | Instance |
|-----|----------|
| `ZITADEL_DEV_SERVICE_TOKEN` | the dev instance |
| `ZITADEL_TEST_SERVICE_TOKEN` | the test instance |
| `ZITADEL_STG_SERVICE_TOKEN` | the stg instance |
| `ZITADEL_PROD_SERVICE_TOKEN` | the prod instance |

Each is a **personal access token on a machine user in that instance**, created
in its console. Not `ZITADEL_<ENV>_SERVICE_ACCOUNT_KEY_JSON`, which is a JWT
profile and a different credential — teardown does not exchange it.

One token per instance is not bureaucracy. dev, test, stg and prod are four
separate ZITADEL servers, so a dev token used against stg authenticates fine,
fails to find the project, and returns **404** — which teardown reads as
"already gone". Teardown therefore refuses a project whose instance it has no
token for, naming the key, rather than reaching for another one.

`koras-control-plane` already keeps a `ZITADEL_SERVICE_TOKEN` per environment
config for its own provisioning. These are the same kind of credential and may
be the same machine users; they live here because teardown runs under the
bootstrap project, which has one config rather than four, so the environment has
to be in the key name.

A bare `ZITADEL_SERVICE_TOKEN` is accepted as a fallback for every environment.
That is right for a single-instance estate and wrong for this one.

A missing credential is named once, at the top, and its resources are skipped
rather than failed. A skip is a provider that will still exist afterwards.

### What it does not delete

| Left behind | Why | Where |
|-------------|-----|-------|
| HCP Terraform workspace | Holds the state of what was just deleted. Terraform is never invoked by teardown, so nothing removes it | app.terraform.io, workspace `<product>` |
| The generated directory | It is yours, on your disk | `rm -rf ../output/<product>` |

**ZITADEL projects, in practice, are still deleted by hand.** The deleter
exists and works, and it needs a personal access token on a machine user, set as
`ZITADEL_SERVICE_TOKEN`. Provisioning does not issue one: the estate holds
`ZITADEL_<ENV>_SERVICE_ACCOUNT_KEY_JSON`, which is a JWT profile, and teardown
does not exchange it. Each environment is also a separate instance, so one token
would not reach all four in any case.

Until a PAT exists per instance, the four projects are reported as skipped for a
missing credential and removed from each instance's console. That is a real gap,
not a formality — see R-036.

The genuine difficulty was never authentication. ZITADEL projects belong to an
organization, and its management API acts in the organization of whoever holds
the token — so in an instance with more than one, a delete aimed at the wrong
org answers **404**, which teardown reads as "already gone" and counts as
success. Teardown therefore sends the organization explicitly, taken from the
`zitadel_resolved_org_ids` output rather than assumed.

Anything without a deleter is reported as `skipped` with its reason on every
run rather than omitted, because an inventory that quietly leaves out a provider
reports a complete teardown while resources stay alive. That happened to
Upstash, which was absent from the inventory entirely until R-040.

---

## 6. Related documents

| Document | Purpose |
|---|---|
| `BOOTSTRAP_DOCTOR.md` | What each doctor check verifies, and what it cannot |
| `PRODUCT_GENERATOR_PLAN.md` | Generator CLI design, flags, project manifest |
| `INFRASTRUCTURE_PLAN.md` | Terraform module strategy |
| `ENVIRONMENT_STRATEGY.md` | Branch ↔ environment mapping |
