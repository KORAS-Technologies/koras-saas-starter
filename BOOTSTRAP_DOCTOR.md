# KORAS SaaS Starter — Bootstrap Doctor

## Purpose

`pnpm koras bootstrap:doctor` answers one question:

> Are all required KORAS bootstrap integrations configured and accessible?

It exists because provisioning fails late and expensively. `--provision`
contacts seven providers in one Terraform run; a token that expired last week
surfaces halfway through, after some resources already exist. The doctor moves
that discovery to a five-second read-only check.

The command is **read-only**. It creates, updates, and deletes nothing — no
repositories, projects, apps, DNS records, secrets, or state. It never runs
`terraform apply`, `destroy`, or `import`.

---

## Usage

```bash
doppler run --project koras-platform-bootstrap --config prod -- \
  pnpm koras bootstrap:doctor
```

Doppler is the sole secret authority, so credentials are injected into the
process rather than read from a file. Nothing is written to disk, and no `.env`
is created. If the required variables are already in the environment — a CI job,
an outer `doppler run` — the command uses them as they are; it never re-invokes
Doppler on top of an environment that already has what it needs.

---

## Output

Two states per row and nothing else:

```text
Koras Bootstrap Doctor

Doppler          ✓
GitHub           ✓
Supabase         ✓
ZITADEL DEV      ✓
ZITADEL TEST     ✓
ZITADEL STG      ✓
ZITADEL PROD     ✓
Vercel           ✓
Fly.io           ✓
Cloudflare       ✓
Terraform        ✓
Terraform state  ✓

READY FOR BOOTSTRAP
```

A failing run replaces `✓` with `✗` and appends the reason:

```text
Koras Bootstrap Doctor

Doppler          ✓
GitHub           ✓
Supabase         ✓
ZITADEL DEV      ✓
ZITADEL TEST     ✗
ZITADEL STG      ✓
ZITADEL PROD     ✓
Vercel           ✓
Fly.io           ✓
Cloudflare       ✓
Terraform        ✓
Terraform state  ✓

Failures:

ZITADEL TEST
Authentication failed (HTTP 401).
Check ZITADEL_TEST_DOMAIN and ZITADEL_TEST_SERVICE_ACCOUNT_KEY_JSON.

NOT READY FOR BOOTSTRAP
```

There is deliberately no WARN, no SKIP, no count, no environment matrix, and no
timing. A check that could not run because its credential is absent has not
passed, and a third state would let an operator talk themselves past it.
Successful checks say nothing beyond `✓` — a passing run should be boring.

**Exit codes:** `0` when every row passes, `1` when any row fails.

---

## What each row verifies

| Row | Verified |
|-----|----------|
| Doppler | `DOPPLER_TOKEN` reaches `koras-platform-bootstrap/prod`, and every required bootstrap key is present in the environment |
| GitHub | `GITHUB_TOKEN` authenticates and `TF_VAR_GITHUB_ORG` is readable |
| Supabase | `SUPABASE_ACCESS_TOKEN` authenticates, `TF_VAR_SUPABASE_ORG_ID` is visible, and all four `SUPABASE_DB_PASSWORD_*` exist |
| ZITADEL DEV/TEST/STG/PROD | Domain resolves, service-account JSON parses, an assertion signs, the JWT-bearer grant succeeds, and `GET /auth/v1/users/me` is accepted |
| Vercel | `VERCEL_API_TOKEN` authenticates and `TF_VAR_VERCEL_TEAM_ID` is readable |
| Fly.io | `FLY_API_TOKEN` authenticates and `TF_VAR_FLY_ORG_SLUG` is among its organizations |
| Cloudflare | `TF_VAR_CLOUDFLARE_ZONE_ID` is readable with `CLOUDFLARE_API_TOKEN`, and the zone matches `TF_VAR_PRIMARY_DOMAIN` |
| Terraform | Binary present, version satisfies the modules' `required_version`, HCP token present, and the module tree passes `init -backend=false` + `validate` |
| Terraform state | HCP token authenticates, the organization from `profiles/*/defaults.yaml` exists, and its workspaces are readable |

Each ZITADEL environment is a separate instance with its own domain and service
account, so each is checked independently — a working DEV credential says
nothing about PROD.

### What the GitHub check can and cannot prove

`GET /orgs/{org}` serves a *public* profile, so a 200 proves almost nothing —
a token with no access to the organization still gets one. The check therefore
requires the response to carry `members_can_create_repositories`, a field
GitHub returns only to a token with real organization visibility.

That is the limit of what a read-only check can establish. **No GitHub API
exposes a fine-grained token's repository permissions**, so the doctor cannot
prove the token may create branches or environments — only that it can see the
organization. Those permissions fail later, during `terraform apply`, one
resource at a time.

Configure them once, from what the module actually creates:

| Terraform resource | Fine-grained permission |
|---|---|
| `github_repository` | **Organization → Administration:** Read and write |
| `github_branch` (reads and writes git refs) | **Repository → Contents:** Read and write |
| `github_branch_default`, `github_branch_protection` | **Repository → Administration:** Read and write |
| `github_repository_environment` | **Repository → Environments:** Read and write |
| everything | **Repository → Metadata:** Read (mandatory, automatic) |

The token's resource owner must be the organization itself, and an org owner
must approve it. A classic PAT with `repo` scope covers all of the above, if
organization policy permits one.

### Why Cloudflare does not gate on `/user/tokens/verify`

A token scoped to a single zone is a perfectly good credential yet cannot call
the account-level verify endpoint, so gating on it would fail a working setup.
The zone read is what Terraform actually does, so it is what decides — and when
it fails, Cloudflare's own error text is surfaced (`Invalid API Token (10000)`)
rather than a bare "rejected".

### Why the Terraform check uses a temporary directory

`project-bootstrap` declares provider aliases (`zitadel.dev` … `zitadel.prod`)
that its caller passes in, so validating it standalone fails with a missing
provider that is not actually missing. The check therefore assembles the
repository's own `infrastructure/terraform/templates/*.tpl` over a copy of the
modules tree in a temp directory and validates that — the same shape a
generated project gets. It also means `init` leaves no `.terraform/` or
`.terraform.lock.hcl` behind in the working tree.

### Why "Terraform state" does not read a state file

The starter has no bootstrap state. Every workspace is created per generated
project (`backend.tf` pins `workspaces { name = "<slug>" }`), so nothing exists
before the first project. What the row verifies instead is the condition that
actually blocks a bootstrap: the HCP token authenticates, the organization
exists, and workspaces under it are readable. A failure here means
`terraform init` will fail for every project.

---

## Required secrets

The doctor does not maintain its own list. It reads the Terraform input
registry in
[`generators/create-koras-app/src/terraform/inputs.ts`](generators/create-koras-app/src/terraform/inputs.ts)
— the same list `--provision` preflights against — so the doctor cannot drift
from what a bootstrap actually needs. Adding a credential there adds it here.

Doppler secret names allow only `[A-Z0-9_]`, while Terraform matches
`TF_VAR_<name>` case-sensitively. Both spellings are accepted: the uppercase
alias is collapsed onto the canonical name once, at the start of the run.

```text
CLOUDFLARE_API_TOKEN            TF_VAR_CLOUDFLARE_ZONE_ID
DOPPLER_TOKEN                   TF_VAR_FLY_ORG_SLUG
FLY_API_TOKEN                   TF_VAR_GITHUB_ORG
GITHUB_TOKEN                    TF_VAR_PRIMARY_DOMAIN
SUPABASE_ACCESS_TOKEN           TF_VAR_SUPABASE_ORG_ID
VERCEL_API_TOKEN                TF_VAR_VERCEL_TEAM_ID
TF_TOKEN_APP_TERRAFORM_IO

SUPABASE_DB_PASSWORD_{DEV,TEST,STG,PROD}
ZITADEL_{DEV,TEST,STG,PROD}_DOMAIN
ZITADEL_{DEV,TEST,STG,PROD}_SERVICE_ACCOUNT_KEY_JSON
```

---

## Secret handling

No value is ever printed. Only key *names* appear in output.

Every failure string passes through a redactor before it reaches the terminal,
because a raw provider error is the most likely way a credential escapes — an
API echoing a token back in a 401 body, a CLI writing one into stderr. Two
layers, since either alone leaks:

- **Value-based** — the actual values of environment variables whose names
  match `TOKEN`, `PASSWORD`, `SECRET`, `PRIVATE_KEY`, `API_KEY`,
  `SERVICE_ACCOUNT`, `CREDENTIAL`, `AUTHORIZATION`, `JWT`, or `COOKIE` are
  replaced wherever they appear. Longest first, so a short secret contained in
  a longer one cannot leave the remainder visible.
- **Pattern-based** — anything *shaped* like a credential is replaced even if
  it never came from this environment: PEM private keys, JWTs, `Authorization`
  headers, `KEY=value` assignments with a sensitive name, credential fields in
  a JSON body, and recognisable provider token prefixes.

ZITADEL service-account JSON is parsed in memory and never written to disk. The
signed assertion and the access token it returns exist only for the duration of
the check.

---

## Architecture

```text
tooling/koras-cli/
  bin/koras.js              shim onto dist/
  src/cli/index.ts          command dispatch
  src/doctor/
    types.ts                DoctorResult { passed, error? }
    env.ts                  reads the shared credential registry
    http.ts                 read-only requests, with timeouts
    redact.ts               secret redaction
    report.ts               rows, marks, verdict, exit code
    run.ts                  check order and execution
    checks/                 one module per integration
```

Every check returns `{ passed, error? }`. There is no status framework beyond
that, because there are only two outcomes.

Checks run concurrently — they are independent reads against different
providers, and a serial run would make a healthy estate wait on the slowest.
Display order is fixed regardless. An unexpected throw inside one check becomes
a failed row rather than a crash: one broken provider must not cost the
operator the other eleven answers.

Network access and process execution are both injected, so the test suite
reaches no real system and needs no credentials.

---

## Tests

```bash
pnpm --filter koras-cli test
```

Covers: all checks passing; each integration failing individually; a missing
Supabase database password; invalid and incomplete ZITADEL service-account
JSON; ZITADEL authentication rejected; an unreachable instance; Terraform
validation failure; an unsupported Terraform version; Terraform state failure;
every row still reported when nothing is configured; an unexpected throw
becoming a failed row; exit codes in both directions; exact output format; and
both redaction layers, including a provider echoing a live token back.
