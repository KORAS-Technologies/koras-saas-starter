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

# 5. Create the restricted database role, ONCE PER ENVIRONMENT. Keep both URLs.
#    Needs psql. On Windows use Git Bash explicitly -- see the note below.
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
- **Step 5 needs `psql`, and on Windows needs Git Bash.** Two separate traps
  that produce one message.

  `bash` typed at a PowerShell prompt resolves to `C:/WINDOWS/system32/bash.exe`
  — the **WSL** launcher, a different machine with its own filesystem and PATH.
  A tool installed on the Windows side is invisible to it, so the script reports
  `psql is not installed` whether or not it is. Run it explicitly:

  ```powershell
  & "C:/Program Files/Git/bin/bash.exe" local/scripts/create-app-role.sh "<url>"
  ```

  And install the client, which is not part of the estate prerequisites because
  nothing else needs it:

  ```powershell
  winget install -e --id PostgreSQL.PostgreSQL.17
  ```

  There is no client-only package on winget; the server installs with it and
  does not need to run.

  **The installer does not put `psql` on PATH.** It lands in
  `C:/Program Files/PostgreSQL/17/bin/psql.exe` and nothing points at it, so the
  script reports the same "psql is not installed" after a successful install as
  it did before one — which reads as the install having failed. Reopening the
  shell does not help; there is nothing new to pick up.

  For the current shell:

  ```powershell
  $env:PATH = "C:/Program Files/PostgreSQL/17/bin;$env:PATH"
  ```

  Or permanently, once:

  ```powershell
  [Environment]::SetEnvironmentVariable(
    "PATH",
    [Environment]::GetEnvironmentVariable("PATH", "User") + ";C:/Program Files/PostgreSQL/17/bin",
    "User")
  ```

  Git Bash inherits the Windows PATH, so this is what makes the script find it;
  no separate install is needed on the Git Bash side. Adjust `17` to the version
  you installed.

  `make` targets are unaffected by the Git Bash question — make resolves `bash`
  itself and finds Git Bash — but they are affected by this one: a `make` target
  calling a script that needs `psql` fails the same way until PATH includes it.

  **Run it once per environment**, with that environment's privileged Supabase
  URL. Four environments, four runs, four pairs of URLs. The script prints the
  restricted URL once and stores it nowhere.

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

### What steps 5 to 8 ask for

**Step 5 runs once per environment, not once.** Four Supabase projects, four
privileged URLs, four runs, four pairs of URLs out. The refs are in the
Terraform outputs:

```bash
terraform -chdir=../output/<product>/infrastructure/terraform output -json |
  python3 -c "import json,sys; [print(e, r) for e, r in sorted(json.load(sys.stdin)['supabase_project_refs']['value'].items())]"
```

The password for each is `SUPABASE_DB_PASSWORD_<ENV>` in
`koras-platform-bootstrap/prod` — the same value Terraform created the project
with. Supabase's pooled connection string looks like:

```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Each run prints the restricted URL **once** and stores it nowhere. Keep both:
the printed one becomes `DATABASE_URL`, the one you passed becomes
`DATABASE_ADMIN_URL`. Losing it costs a re-run, which rotates the credential —
that is the recovery path, not a failure.

**Step 7 prompts per environment.** For a product, 11 settings come from
Terraform and 13 are asked for — 11 of them unless `ai_gateway` is enabled,
which adds `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. For the Control Plane, 12
derived and 8 asked.

| Prompt | Where the value comes from |
|--------|----------------------------|
| `DATABASE_URL` | printed by step 5 — the `koras_app` role |
| `DATABASE_ADMIN_URL` | the privileged URL you passed to step 5 |
| `ZITADEL_CLIENT_SECRET` | that environment's ZITADEL console → the project → its OIDC application. ZITADEL shows it once |
| `ZITADEL_SERVICE_TOKEN` | Control Plane only. A PAT on a machine user in that instance |
| `SESSION_SECRET` | `openssl rand -base64 48`. **Different in every environment** — one shared key makes a development cookie a production cookie |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | **Empty is valid and is the right answer until a collector exists.** Empty means no exporter, not no tracing: spans are still created and context still propagates |
| `OTEL_EXPORTER_OTLP_HEADERS` | Empty unless a hosted collector needs auth, then `authorization=Basic <base64>` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` for a managed collector, `grpc` otherwise. Not inferable — the local collector is an `http://` URL that speaks gRPC |
| `OTEL_SERVICE_NAME` | the product slug |
| `KORAS_CONTROL_PLANE_TOKEN` | **not** issued by the Control Plane, whatever this row said before 2026-08-30: nothing mints a per-product credential (F2b). It is a ZITADEL token for the estate-wide `registrar` service user, and it lasts twelve hours. The generator prefers `KORAS_CONTROL_PLANE_KEY_JSON` and mints per call (F2a). Empty is correct here: the deploy-time job that would read it is off by default |
| `KORAS_CONTROL_PLANE_URL` | the Control Plane's address. Empty if there is none. It cannot be derived: the Control Plane is a separate estate with its own state |
| `STORAGE_BUCKET` | a name you pick. The storage module provisions no buckets, so there is nothing to derive it from |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | only when `ai_gateway` is enabled |

**An empty answer is not recorded.** Pressing enter prints `skipped, still
missing`, writes nothing, and marks the run failed; the script then hands off to
`doppler-check.sh`, which reports it as absent. This sentence used to claim the
opposite — that empty counted as answered — and it was wrong in a way that
matters, because four of the settings above are *legitimately* empty and the
prompt cannot express that.

Until that is fixed (F5a), set those four directly, which does record an empty
value:

```bash
printf '' | doppler secrets set OTEL_EXPORTER_OTLP_ENDPOINT \
  --project <product> --config <environment> --no-interactive
```

`doppler-check` reads names and never values, so an empty-valued secret passes
it. That is the same guarantee as before; only the way to arrive at one has
changed.

Values are read with `read -rs` and piped to `doppler secrets set` on stdin, so
none reaches `ps` output or shell history. Already-set values are skipped unless
`--overwrite`. A value that appears in a committed Terraform artifact is
**refused**: it has been published, and storing it would record a burned
credential as live. Rotate and paste the new one.

**On Windows**, `make` resolves `bash` itself and finds Git Bash, so steps 7 and
8 work from PowerShell unchanged. Step 5 and the `--dry-run` in step 6 are typed
as `bash ...` and need the explicit path — see the note above.

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
| `KORAS_CONTROL_PLANE_TOKEN` | ZITADEL token for a service user in the Control Plane's instance. **Not issued by the Control Plane** — it has no endpoint that mints one, and nothing provisions this. See NEW_PRODUCT_WALKTHROUGH.md §A.2 |

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

Four ZITADEL keys per environment, three of which the doctor does not check:

| Key | Read by | Checked by the doctor |
|-----|---------|-----------------------|
| `ZITADEL_<ENV>_DOMAIN` | Terraform | yes |
| `ZITADEL_<ENV>_SERVICE_ACCOUNT_KEY_JSON` | Terraform — a JWT profile | yes |
| `ZITADEL_<ENV>_ORG_ID` | Terraform, when set | no — optional |
| `ZITADEL_<ENV>_SERVICE_TOKEN` | `koras teardown` — a machine-user PAT | no |

The last two are easy to confuse with the second and are neither: the org id is
not a credential, and the service token is a *personal access token* rather than
a JWT profile. Teardown does not exchange the profile, which is why it needs its
own credential; §5 covers what it is for.

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
| `psql is not installed` after installing PostgreSQL | The installer does not add it to PATH. It is at `C:/Program Files/PostgreSQL/<v>/bin/psql.exe` and nothing points there, so the message is identical before and after a successful install | Prepend that directory to `PATH` — see §1 step 5. Reopening the shell does not help; there is nothing new to pick up |
| A `local/scripts/*.sh` reports a tool "is not installed" that plainly is | On Windows, `bash` from PowerShell resolves to `C:/WINDOWS/system32/bash.exe` — the **WSL** launcher, a separate Linux filesystem that cannot see a winget or Scoop install on the Windows side | Run it under Git Bash: `& "C:/Program Files/Git/bin/bash.exe" <script>`. `make` targets are unaffected — make resolves `bash` itself and finds Git Bash |
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

Four things, none of which the command checks for you:

1. **You are in the starter.** Every command below runs from
   `C:\repos\Projects\koras-saas-starter`. The generated project lives beside
   it, at `../output/<product>/`, and you never `cd` into it.
2. **The project is named `koras-e2e-something`.** The guards refuse every other
   name, deletion enabled or not. This is the safety mechanism, not a
   convention.
3. **The credentials exist in `koras-platform-bootstrap/prod`.** A missing one
   is *skipped*, not failed — the run finishes, names it once at the top, and
   looks successful while that provider's resources are still there. Eight
   providers, and the two easiest to forget are the newest:
   `ZITADEL_{DEV,TEST,STG,PROD}_SERVICE_TOKEN`, one per instance, and
   `TF_TOKEN_APP_TERRAFORM_IO` for the workspace.
4. **The project directory still exists.** Teardown reads the HCP organization
   from its `backend.tf`. Delete the directory after teardown, not before, or
   the workspace outlives it — see steps 4 and 6.

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

Eight kinds are possible, and a product with `web`, `admin`, `api` and `worker`
produces all of them:

| Kind | Typical count |
|------|---------------|
| `cloudflare-record` | 8 — deleted first; a DNS record pointing at nothing is the one leftover a stranger sees |
| `fly-app` | 8 |
| `vercel-project` | 8 |
| `upstash-database` | 4 |
| `supabase-project` | 4 |
| `zitadel-project` | 4 |
| `doppler-project` | 1 |
| `github-repository` | 1 |
| `terraform-workspace` | 1 — deleted last; it is the record of what the rest were |

**A kind absent from the list is the failure mode to look for**, and it does not
announce itself: the count counts what the inventory holds, so a provider it was
never told about is missing from both. That is how eight DNS records and four
Upstash databases each survived a run reporting nothing retained — see R-040 and
R-036. Teardown warns explicitly when the outputs carry no
`cloudflare_record_ids`, which is the one case still possible on an older
project.

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

**It verifies itself when it finishes.** After the deletes, it asks each
provider whether the resource is still there and prints one line each, then a
total. This is the shape, from a real run of the same check against a single
resource that had *not* been deleted:

```
Verified 1 resource(s) — nothing was deleted here.

  ALIVE    terraform-workspace  koras-e2e-user  (HTTP 200)

  0 gone, 1 still there, 0 unknown.
```

A full estate prints thirty such lines, one per resource in step 1's list.
Exit 1 if anything is `alive` or `unknown`.

That is not the same as reading the delete output. Teardown counts 404 as
success — a resource already gone satisfies the request, and re-running after a
partial teardown has to work — so *deleted* and *never found* print identically,
and a delete aimed at the wrong ZITADEL instance or Cloudflare zone produces the
second while looking like the first. The check probes the URL each deleter used
rather than one it rebuilt: the deleters are run against a fetch that records
and sends nothing, and the recorded URL is issued as a `GET`.

**`unknown` is not `gone`.** The provider did not say the resource was absent —
it refused, it failed, or it was never asked because a credential is missing.
Supabase answers `400 "Resource has been removed"` for a deleted project, which
is genuinely neither. Check those by hand.

**Why it runs here and not as a second command.** Terraform has already run,
once, before anything was deleted; everything after that is HTTP. A separate
verification would re-read the outputs, and `terraform output` against a
`remote` backend **creates the workspace when it is missing** — putting back the
one resource teardown deletes last, and then reporting it alive. Observed: two
workspaces before a run, three after, the new one stamped "a few seconds ago".

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

### Step 3 — DNS records, only for a product generated before 2026-08-27

Skip this if the product was generated from a starter that exports
`cloudflare_record_ids`; teardown deletes the records with everything else, and
step 1 lists them under `cloudflare-record`. If it does not list them, its
`main.tf` predates that output and the records are invisible to it — the
inventory cannot delete what it was never told about, and the count says nothing
because it counts the same set. R-036.

PowerShell, and **not** `bash -c`: `bash` here is WSL's, which does not inherit
the environment `doppler run` injects, so every variable arrives empty and the
API answers with `result: null`. That reads as `'NoneType' object is not
iterable` from whatever parses it.

```powershell
$z = doppler secrets get TF_VAR_CLOUDFLARE_ZONE_ID --plain `
       --project koras-platform-bootstrap --config prod
$t = doppler secrets get CLOUDFLARE_API_TOKEN --plain `
       --project koras-platform-bootstrap --config prod

# List first. Read-only.
$api = "https://api.cloudflare.com/client/v4/zones/$z/dns_records"
$doomed = (Invoke-RestMethod -Uri "${api}?per_page=200" `
             -Headers @{ Authorization = "Bearer $t" }).result |
          Where-Object { $_.name -like "*<product>*" }
$doomed | Select-Object id, type, name | Format-Table -AutoSize

# Then delete what was listed, and nothing else.
foreach ($r in $doomed) {
  Invoke-RestMethod -Method Delete -Uri "$api/$($r.id)" `
    -Headers @{ Authorization = "Bearer $t" } | Out-Null
  "deleted $($r.name)"
}
```

The filter is the guard. `koras teardown` refuses a name that is not
`koras-e2e-...`; this loop has no such protection, so the `-like` pattern is the
only thing standing between it and a record somebody needs. Read the list before
running the second half.

### Step 4 — anything teardown left behind

One thing, and it is not a provider.

**The HCP Terraform workspace is deleted for you now.** It was on this list
because teardown never invokes Terraform, so nothing removed it — and it holds
the state of the estate that was just deleted. It is addressed by organization
and name through the HCP API, using `TF_TOKEN_APP_TERRAFORM_IO`; the
organization is read from the project's own `backend.tf`, which is the only
record of it left by then. It is deleted **last**, after everything it recorded,
so a run that fails halfway can be finished while the state still describes the
estate.

That also means **the workspace survives if you delete the project directory
first**. There is nothing left to read the organization from, and the inventory
drops it rather than guessing. Delete the directory after teardown, not before.
To remove a workspace whose project is already gone:

```powershell
$t = doppler secrets get TF_TOKEN_APP_TERRAFORM_IO --plain `
       --project koras-platform-bootstrap --config prod
Invoke-RestMethod -Method Delete `
  -Uri "https://app.terraform.io/api/v2/organizations/<org>/workspaces/<product>" `
  -Headers @{ Authorization = "Bearer $t" }
```

The generated directory is dealt with in step 6, after verifying — see below.

### Step 5 — `--verify` on its own, and when not to use it

Step 2 already verified what it deleted. This flag runs the same check without
deleting anything:

```powershell
pnpm koras teardown <product> --product-path ../output/<product> --verify
```

**It refuses after a completed teardown**, rather than warning and proceeding.
Reading the Terraform outputs would create the workspace — that is what a
`remote` backend does with one it cannot find — so every teardown command now
asks HCP over HTTP first, and stops if the workspace is already gone:

```
The HCP workspace koras/koras-e2e-user does not exist.

Nothing to do. Reading the Terraform outputs would create it --
that is what a `remote` backend does with a workspace it cannot
find -- so this stops instead, and the estate stays torn down.
```

Exit 0. Nothing is wrong; there is nothing left to look at.

A warning came first and was not enough: it printed, Terraform ran, the
workspace was re-created anyway, and the command exited 1 for a resource it had
just made. The guard applies to the dry run too — step 1 after a completed
teardown would have re-created it just as readily.

It is for an estate that still exists: checking a partial teardown before
re-running one, or confirming what a dry run listed is really there.

#### What it can and cannot catch

It asks only about resources the inventory knows. It catches a delete that
failed or went to the wrong instance. It cannot catch a provider nobody told it
about — Cloudflare was missing from the inventory for months, so no amount of
verifying would have mentioned it.

For that, read the *shape* of step 1's list against the table there, and read
what `terraform plan` proposes to recreate: that covers everything the
configuration declares, rather than everything teardown happens to know.

**Done once by hand, on 2026-08-27**, against a product estate of 82 resources:
thirty planned, thirty deleted, and each provider asked directly. It was still
not complete — eight DNS records survived, found only when the next apply
refused to create a record that already existed. `30 deletable, 0 retained`
counts what the inventory holds, which is the one thing that cannot reveal a
provider it omits.

### Step 6 — remove the directory, and do not re-plan

Last, because everything above needs it: the inventory, the HCP organization in
`backend.tf`, and anything `--verify` reads all come out of this directory.

```powershell
Remove-Item -Recurse -Force ../output/<product>
```

```bash
rm -rf ../output/<product>
```

After a teardown, the Terraform state describes an estate that no longer exists.
Running `--provision-only` in that directory does not start again cleanly: it
refreshes first, and three providers treat a deleted resource as an error rather
than as absence.

```
Error: Could not find App "koras-e2e-shop-api-dev"
Error: Unable to read project, got status 400: {"message":"Resource has been removed"}
Error: Get Redis Database failed, status code: 404 response: "database not found"
```

Fly, Supabase and Upstash each fail the plan on that. GitHub, Vercel, ZITADEL
and Doppler are gentler — they drop the resource from state and propose to
recreate it, which is why the same run reports `Plan: 82 to add` beside the
errors.

Nothing is wrong. Read it as confirmation: those messages *are* the providers
saying the resources are gone. The state is spent, and the remedy is to discard
it rather than repair it — the workspace goes in step 4 and the directory in
step 6. A new acceptance run generates a new project with a new workspace.

Note the same trap as step 5, from the other direction: any Terraform command
run in this directory against a `remote` backend re-creates the workspace if it
is missing. Removing the directory is what closes that door.

Worth being deliberate about, because `--provision-only` on a torn-down estate
is one keystroke from **recreating all 82 resources and their bills.**

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
| The generated directory | It is yours, on your disk | `rm -rf ../output/<product>` |
| DNS records, for a product generated before 2026-08-27 | Its `main.tf` predates the `cloudflare_record_ids` output, so the inventory cannot see them. Teardown says so rather than leaving it to the count | Step 3 above |
| The HCP workspace, **if the directory was deleted first** | Its organization is read from `backend.tf`; with the project gone there is nothing to read | Step 4 above |
| DNS records, for a product generated before 2026-08-27 | Its `main.tf` predates the `cloudflare_record_ids` output, so the inventory cannot see them | Step 3 above |

**ZITADEL projects were on this list and are not any more.** The deleter needs
a personal access token on a machine user in that instance, and provisioning
issues none: what the estate holds is
`ZITADEL_<ENV>_SERVICE_ACCOUNT_KEY_JSON`, a JWT profile, which teardown does not
exchange. Four instances also cannot share one token. So four were created —
`ZITADEL_{DEV,TEST,STG,PROD}_SERVICE_TOKEN` — and the deleter picks the one
matching each project's environment, refusing by name rather than reaching for
another instance's. A token from the wrong server authenticates, does not find
the project, and answers 404, which teardown reads as already gone.

If one of the four is missing, that instance's project is reported as skipped
and has to come out of its console by hand — which is a credential to add, not a
deleter to write.

The genuine difficulty was never authentication. ZITADEL projects belong to an
organization, and its management API acts in the organization of whoever holds
the token — so in an instance with more than one, a delete aimed at the wrong
org answers **404**, which teardown reads as "already gone" and counts as
success. Teardown therefore sends the organization explicitly, taken from the
`zitadel_resolved_org_ids` output rather than assumed.

Anything without a deleter is reported as `skipped` with its reason on every
run rather than omitted, because an inventory that quietly leaves out a provider
reports a complete teardown while resources stay alive. `UNIMPLEMENTED_KINDS` is
empty today and kept for exactly that: a kind with no deleter and no entry is
one the command can neither delete nor mention.

It has happened twice. Upstash was absent from the inventory until R-040, and
Cloudflare until R-036 — four billing databases and eight DNS records, each
outliving a run that reported nothing retained.

---

## 6. Related documents

| Document | Purpose |
|---|---|
| `BOOTSTRAP_DOCTOR.md` | What each doctor check verifies, and what it cannot |
| `PRODUCT_GENERATOR_PLAN.md` | Generator CLI design, flags, project manifest |
| `INFRASTRUCTURE_PLAN.md` | Terraform module strategy |
| `ENVIRONMENT_STRATEGY.md` | Branch ↔ environment mapping |
