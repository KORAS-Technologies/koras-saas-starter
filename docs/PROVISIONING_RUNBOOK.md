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

# 5. Create the role the services connect as -- ONCE PER ENVIRONMENT, so four
#    times. In: that environment's privileged Supabase URL. Out: a restricted
#    one, printed once and stored nowhere.
#
#    Keep both. The one you passed in becomes DATABASE_ADMIN_URL (migrations,
#    CI only); the one printed becomes DATABASE_URL (every service). Step 7
#    asks for both, which is why this comes first.
#
#    Why it exists: RLS does not apply to a superuser, and Supabase issues one
#    as its default credential -- so services using the dashboard URL get
#    correct policies and no isolation at all. See R-032, and "What steps 5
#    to 8 ask for" below for where the privileged URL comes from.
#
#    Needs psql. On Windows use Git Bash explicitly -- see the note below.
bash local/scripts/create-app-role.sh "<privileged database url>"

# 6. See what Doppler will be asked for. Writes nothing.
bash local/scripts/doppler-bootstrap.sh --dry-run

# 7. Populate dev, test and stg, then prod. Two targets, deliberately.
make doppler-bootstrap
make doppler-bootstrap-prod

# 8. Confirm every environment holds every setting. Names only, never values.
make doppler-check

# --- back in the starter ---

# 9. Create this product's prices at the payment provider and write their
#    references onto its plans in the Control Plane.
#
#    NEEDS TWO CREDENTIALS, set up once each -- see "Secrets for step 9" below.
#    Do that first; without them this refuses and names which is missing.
#
#    ../output/<name>/.koras/billing-catalogue.yaml already holds the platform
#    standard. Read it and change what differs; a product that wants the
#    standard changes nothing.
#
#    After 1-8, and that is a dependency rather than an ordering preference:
#    registration (step 3) creates the plans this writes onto.
#
#    Changes no infrastructure. Never deletes a price, archives one or edits an
#    amount. Running it twice is free -- the second run finds every price
#    already there and writes nothing.

# Prints every amount and lookup key, sends nothing:
pnpm create-koras-app <name> --profile product --provision-billing --dry-run --output-dir ../output

# Creates them:
pnpm create-koras-app <name> --profile product --provision-billing --output-dir ../output
```

Notes that matter:

- **Step 9 for a product that already exists needs one step in front of it.**
  The file it reads is generator-written, and a product registered before the
  catalogue existed has none. See **Provisioning the catalogue for a product
  that already exists** below.
- **Step 9 needs two credentials, set up in different ways.** The payment
  provider's key goes in Doppler once; your own staff token is exported per
  run and is never stored. **There is no service account for this and one
  cannot be created** — a platform role requires a second factor and a
  machine identity has none. See **Secrets for step 9** below, which has
  the commands.
- **Step 9 refuses a live provider key anywhere but production**, and a test
  key against production, both before it makes a single call. The first would
  create real, chargeable prices while somebody believed they were rehearsing
  -- and nothing later in the run would notice, because the calls succeed and
  the ids look the same. The second produces a catalogue that cannot take a
  payment, discovered at the first customer's checkout.
- **Step 9 refuses a plan code the Control Plane does not hold.** It would
  otherwise be created: the endpoint upserts, so a typo becomes a real, priced
  tier that grants nothing and looks like a tier somebody meant to add. Every
  unknown code in the file is reported in one run, because finding the second
  typo after correcting the first is three runs against a payment account.

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

**Step 7 prompts per environment.** For a product without `ai_gateway`, 12
settings come from Terraform and **9** are asked for. Enabling `ai_gateway` adds
one derived setting (`AI_GATEWAY_URL`) and **three** asked-for ones —
`LITELLM_MASTER_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` — making 13 and 12,
plus the optional `GEMINI_API_KEY` and `OPENROUTER_API_KEY`. For the Control
Plane, 12 derived and 8 asked.

Do not trust those numbers against a manifest you have in front of you — count
it, because the manifest is the authority and this document is not:

```bash
# From the generated project. `supplied` is what step 7 will ask you for.
grep -v '^#' local/config/secrets.manifest | awk 'NF {print $2}' | sort | uniq -c
```

This paragraph claimed "11 derived and 13 asked" until 2026-09-17, and the table
below was missing four of the settings the script actually prompts for —
`LITELLM_MASTER_KEY`, `ZITADEL_PLATFORM_CALLER_SUB`, `STORAGE_ACCESS_KEY` and
`STORAGE_SECRET_KEY`. Three of those four are prompted for **every** product,
which is why the count command is here rather than a promise to keep the list
current.

### Gather the values before you start

The prompts come in one pass per environment, and **an empty answer is not
recorded** — it prints `skipped, still missing` and marks the run failed. So
collect everything first. Four environments, four passes; the checklist at the
end of this section is what to fill in.

Six groups, ordered so that each one's tab is open before you need it.

**1 — Already in hand, from step 5.** Two per environment, and this is the whole
reason step 5 comes first.

| Setting | Value |
|---|---|
| `DATABASE_URL` | the restricted URL `create-app-role.sh` printed |
| `DATABASE_ADMIN_URL` | the privileged Supabase URL you passed it |

**2 — You generate.** Nobody issues these. A different value in every
environment, both times.

| Setting | How |
|---|---|
| `SESSION_SECRET` | `openssl rand -base64 48`. At least 32 characters. One shared key makes a development cookie a production cookie |
| `LITELLM_MASTER_KEY` | `echo "sk-$(openssl rand -hex 32)"`. Only with `ai_gateway`. See below — empty is open, not off |

**3 — You choose.** Neither is derivable, because neither names a resource
Terraform created.

| Setting | What to answer |
|---|---|
| `OTEL_SERVICE_NAME` | the product slug |
| `STORAGE_BUCKET` | a bucket name you pick. The storage module provisions **no buckets**, so there is nothing to derive it from — and nothing creates the bucket either. Create it in Supabase Storage yourself |

**4 — Supabase dashboard**, per environment, per project.

| Setting | Where |
|---|---|
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | that project → **Storage → S3 access keys** → create a pair. The API signs upload and download URLs with it and nothing else ever holds it. Locally these are MinIO's root pair, which is why a developer machine works while a deployed environment does not |
| the **Description** field on that dialog | a label only — it appears in no key and no setting, and exists so you can tell pairs apart when one is rotated or revoked. Name it `<product>-<env>-api`, matching the `<component>-<env>` shape used for Fly apps and Vercel projects: `docoris-dev-api`. One pair per environment, never shared between them |

Supabase says it plainly on that dialog, and it is worth reading twice: an S3 access key gives **full access to every bucket and bypasses every RLS policy**. That is the storage half of R-032. Row-level security protects rows, not blobs, so for files the isolation is the object key path and the short-lived signed URL, enforced separately — which is why storage tenancy is its own mechanism rather than a consequence of the database's. Treat this pair as being as privileged as `DATABASE_ADMIN_URL`: it belongs in Doppler and nowhere else, never in a `.env` and never in a Terraform artifact.

**5 — ZITADEL**, per environment. Two values from two different places, and the
second is the one people miss.

| Setting | Where |
|---|---|
| `ZITADEL_CLIENT_SECRET` | that environment's ZITADEL console → **this product's** project → its OIDC application. ZITADEL shows it **once**; if it is gone, regenerate rather than guess |
| `ZITADEL_PLATFORM_CALLER_SUB` | the `sub` of the estate's `product-caller` service account, which lives in the **platform's** ZITADEL organization, not this product's. Read it from the Control Plane's own key rather than retyping it — `doppler secrets get ZITADEL_PRODUCT_CALLER_KEY_JSON --plain --project koras-control-plane --config <env>`, and take the `userId` field, which *is* the `sub` because the assertion is issued and subjected to the service user. Or: ZITADEL console → the platform organization → Service Users → `product-caller` → its ID |

`ZITADEL_PLATFORM_CALLER_SUB` has its own procedure, including the two settings
that are not this one — `product-caller` must be on the **JWT** access token
type, and it must have **no project grant**. Both are in
`koras-control-plane/docs/runbooks/product-platform-caller.md`. Getting the token type wrong gives a
401 *after* a successful token exchange, which reads like a credential problem
and is not.

**6 — Model providers**, only with `ai_gateway`. These are read by the gateway
and by nothing else; the product never holds a provider credential.

| Setting | Where to create it | If that URL has moved |
|---|---|---|
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> | platform.openai.com → the project selector → **API keys** |
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com/settings/keys> | console.anthropic.com → **Settings → API keys** |
| `GEMINI_API_KEY` *(optional)* | <https://aistudio.google.com/apikey> | aistudio.google.com → **Get API key** |
| `OPENROUTER_API_KEY` *(optional)* | <https://openrouter.ai/keys> | openrouter.ai → **Keys** |

The navigation path is given beside each link because console URLs move and the in-console path outlives them.

**OpenAI and Anthropic cannot be skipped** — both are class `supplied`, so the prompt refuses an empty answer. Gemini and OpenRouter are `optional`: an unkeyed provider is answered with that provider's own refusal rather than silently falling through to another model.

**Both need billing before the key works.** A key issued on an account with no credit returns a quota error on first use, which reads like a bad key and is not. Each key is shown **once**; copy it straight into Doppler, and reissue rather than hunt for a lost one. 
**A separate key per environment is not required, and is worth doing anyway.** Label them the way the S3 pairs are labelled — `docoris-dev`, `docoris-prod` — so that revoking a leaked development key is not also a production incident.

#### The checklist

Per environment, before running step 7. Nine rows without `ai_gateway`, twelve
with it.

| # | Setting | dev | test | stg | prod |
|---|---|:--:|:--:|:--:|:--:|
| 1 | `DATABASE_URL` | ☐ | ☐ | ☐ | ☐ |
| 2 | `DATABASE_ADMIN_URL` | ☐ | ☐ | ☐ | ☐ |
| 3 | `SESSION_SECRET` | ☐ | ☐ | ☐ | ☐ |
| 4 | `OTEL_SERVICE_NAME` | ☐ | ☐ | ☐ | ☐ |
| 5 | `STORAGE_BUCKET` | ☐ | ☐ | ☐ | ☐ |
| 6 | `STORAGE_ACCESS_KEY` | ☐ | ☐ | ☐ | ☐ |
| 7 | `STORAGE_SECRET_KEY` | ☐ | ☐ | ☐ | ☐ |
| 8 | `ZITADEL_CLIENT_SECRET` | ☐ | ☐ | ☐ | ☐ |
| 9 | `ZITADEL_PLATFORM_CALLER_SUB` | ☐ | ☐ | ☐ | ☐ |
| 10 | `LITELLM_MASTER_KEY` | ☐ | ☐ | ☐ | ☐ |
| 11 | `OPENAI_API_KEY` | ☐ | ☐ | ☐ | ☐ |
| 12 | `ANTHROPIC_API_KEY` | ☐ | ☐ | ☐ | ☐ |

Rows 10 to 12 exist only when `ai_gateway` is enabled. Confirm the list against
the manifest rather than against this table — the count command above is there
because this table has been wrong before.

#### The full reference

Every prompt, including the optional ones the gather list does not walk through:

| Prompt | Where the value comes from |
|--------|----------------------------|
| `DATABASE_URL` | printed by step 5 — the `koras_app` role |
| `DATABASE_ADMIN_URL` | the privileged URL you passed to step 5 |
| `ZITADEL_CLIENT_SECRET` | that environment's ZITADEL console → the project → its OIDC application. ZITADEL shows it once |
| `ZITADEL_SERVICE_TOKEN` | Control Plane only. A PAT on a machine user in that instance |
| `ZITADEL_PLATFORM_CALLER_SUB` | that environment's ZITADEL: the subject of the identity the platform calls as. Prompted for every product |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | the object store's credentials. Prompted for every product, and **not** derivable: the storage module provisions no bucket, so nothing in the Terraform outputs knows them |
| `LITELLM_MASTER_KEY` | only when `ai_gateway` is enabled. **Nobody issues this one — you invent it.** See below |
| `SESSION_SECRET` | `openssl rand -base64 48`. **Different in every environment** — one shared key makes a development cookie a production cookie |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | **Empty is valid and is the right answer until a collector exists.** Empty means no exporter, not no tracing: spans are still created and context still propagates |
| `OTEL_EXPORTER_OTLP_HEADERS` | Empty unless a hosted collector needs auth, then `authorization=Basic <base64>` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` for a managed collector, `grpc` otherwise. Not inferable — the local collector is an `http://` URL that speaks gRPC |
| `OTEL_SERVICE_NAME` | the product slug |
| `KORAS_CONTROL_PLANE_TOKEN` | **empty, and never copied from another product** — see below. **not** issued by the Control Plane, whatever this row said before 2026-08-30: nothing mints a per-product credential (F2b). It is a ZITADEL token for the estate-wide `registrar` service user, and it lasts twelve hours. The generator prefers `KORAS_CONTROL_PLANE_KEY_JSON` and mints per call (F2a). Empty is correct here: the deploy-time job that would read it is off by default |
| `KORAS_CONTROL_PLANE_URL` | the Control Plane's address. Empty if there is none. It cannot be derived: the Control Plane is a separate estate with its own state |
| `STORAGE_BUCKET` | a name you pick. The storage module provisions no buckets, so there is nothing to derive it from |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | only when `ai_gateway` is enabled |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD` | optional: any provider that speaks SMTP, for the mail the product sends itself (the assistant's approval notice). Empty means the notice is recorded and logged, not sent |
| `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | only when `ai_gateway` is enabled, and optional: an empty answer leaves that provider unkeyed, and a routing policy naming it is answered with the provider's refusal |

**`LITELLM_MASTER_KEY` is not a key anyone issues you.** It is a shared bearer
token between two things the estate owns: the product's API sends it, and the
product's own LiteLLM gateway checks it. It is unrelated to `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY`, which are the provider credentials the gateway then calls
*with* — the gateway holds those so the product never does.

Generate one, per environment, and a different one in each:

```bash
echo "sk-$(openssl rand -hex 32)"
```

No format is enforced — `guard.py` compares the bearer with
`hmac.compare_digest` against whatever is set — but LiteLLM's own convention is
an `sk-` prefix, so use it. Both the API and the gateway read the value from the
same Doppler config, which is what makes the two sides match.

**Empty is not "off", it is open.** The gateway's middleware treats an empty key
as unset and stops validating (`self._key = key or None`), so a deployed gateway
with no master key serves anyone who can reach its URL. This is not
hypothetical: the manifest entry was marked `local` at one point, which left
every deployed gateway with no master key at all. The product side fails closed
— an empty value raises `CONFIGURATION_ERROR` rather than calling out
unauthenticated — so the failure is one-sided and silent on the side that
matters.

Nothing consumes it until a product actually calls a model, so a placeholder now
and a rotation later is defensible. A short or memorable one is not: it is the
only thing between a public URL and a provider bill.

#### The three Control Plane settings, and the one you must not copy

All three are class `optional`. Step 7 does prompt for them, and pressing
enter leaves each unset, which is correct for the third and wrong for the first
two — those you type, per environment. Two are estate-wide identifiers that every product in
an environment shares. The third looks like the other two and is not.

| Setting | Shared across products? | What it is |
|---|---|---|
| `KORAS_CONTROL_PLANE_URL` | **Yes** — same value for every product in that environment | Where the Control Plane lives. One per environment |
| `KORAS_CONTROL_PLANE_PROJECT_ID` | **Yes** — same value for every product in that environment | The Control Plane's ZITADEL project id, requested as an extra token audience at sign-in so a product's web tier can read a customer's own plan. An identifier, not a credential |
| `KORAS_CONTROL_PLANE_TOKEN` | **No. Never copy it between products** | A bearer for the estate-wide `registrar` service account, valid twelve hours |

```bash
# The two that are copied. Per environment, per product.
doppler secrets set KORAS_CONTROL_PLANE_URL --project <product> --config <env>
doppler secrets set KORAS_CONTROL_PLANE_PROJECT_ID --project <product> --config <env>
```

**Why `KORAS_CONTROL_PLANE_TOKEN` is not one of them.** It is not per-product —
nothing mints a per-product credential (F2b) — so the value sitting in one
product's config is the *estate's* registrar, and the registrar can write **every
product's registry entry**. Copying it from a product that has one gives each
product write access to the other's registration. That is the reason the
deploy-time registration job is off by default, not an incidental consequence of
it.

It also would not work. The token lasts twelve hours, so a value copied out of
another product's Doppler is expired or about to be.

**Empty is the correct answer**, and the failure mode of a wrong one is quiet:
an unset Control Plane URL is a documented skip (R-001), so registration reports
"no Control Plane configured" rather than failing. That is how an estate *with* a
Control Plane went for a period reporting that it had none — the bootstrap
prompted for `CONTROL_PLANE_API_KEY` while every reader looked for the prefixed
name, and nothing anywhere went red.

**What to do instead when a product's references need re-sending:**
`--register-only` from the starter. It reads Terraform outputs and sends them,
never plans and never applies, and the generator mints a token per call from
`KORAS_CONTROL_PLANE_KEY_JSON` in the bootstrap config (F2a). Nothing long-lived
has to sit in a product's Doppler at all.

```bash
pnpm create-koras-app <name> --profile <profile> --register-only --output-dir ../output
```

**If you find a token already set in a product's config**, it is one of two
things: a deploy-time registration job that somebody deliberately enabled for
that product, or a value set once and dead ever since. Neither is a reason to
replicate it into a new product. Check
`koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md` and
`docs/REGISTRATION_LIFECYCLE.md` before enabling the job anywhere.

#### The retention settings, and the one that is not like the others

Nine settings decide how long things are kept. All are class `optional` and **all
have defaults**, so step 7 asks and enter is the right answer to every one of
them. Leave them unset unless there is a reason to change one — a number typed to look decisive is the
main way these go wrong.

| Setting | Unset means | Keeps |
|---|---|---|
| `AI_RETENTION_DAYS` | 90 days | An assistant conversation, its messages and its actions, counted from when it was last *touched* rather than created. Usage rows survive the purge: a call that happened still happened |
| `AI_AUDIT_RETENTION_DAYS` | 1 year | Assistant audit rows |
| `AUDIT_RETENTION_DAYS` | 1 year | The `audit` and `administrative` classes. Foundation, like the table: every product records, so every product forgets |
| `AUDIT_ACTIVITY_RETENTION_DAYS` | 90 days | `activity` — a file opened, a report viewed. The bulk of the rows and the least of them worth a year |
| `AUDIT_SECURITY_RETENTION_DAYS` | **3 years** | `security` — a refusal, an authorization decision, a hold. The longest, because the question asked about one of these is usually asked late |
| `STORAGE_BACKUP_RETENTION_DAYS` | 30 days | A backup copy, before the catalogue retires it. Deliberately shorter than the objects' own retention: a backup is insurance against losing something recently, not a second archive |
| `REPORT_EXPORT_RETENTION_DAYS` | 7 days | A background report export in the tenant's bucket |
| `STORAGE_RETENTION_DAYS_SENSITIVE` | 10 years | Objects a product classified `sensitive` |
| `STORAGE_RETENTION_DAYS_RESTRICTED` | 10 years | Objects a product classified `restricted` |

Every sweep is nightly, and every one asks about legal hold before it acts. A
value below 1 is refused rather than honoured — `AI_RETENTION_DAYS must be at
least 1; retention of nothing is a wipe`.

**`STORAGE_RETENTION_DAYS_STANDARD` is the exception, and it is the dangerous
one.** Unset does not mean a short default. It means **no automatic deletion at
all**: an ordinary customer document is kept until the customer deletes it.

Do not read it as "days before cleanup". It does two jobs at once — the floor a
tenant may not go below, *and* the period after which an object is actually
deleted — so a `7` there does not mean "keep for at least a week", it means every
customer file of that class disappears in a week. That conflation has already
produced a defect in this platform; `docs/RETENTION_POLICY.md` records it. A
tenant may lengthen retention through their own override and may never shorten it
below a floor that is set.

`SENSITIVE` and `RESTRICTED` carry ten-year defaults for the opposite reason:
those are classifications a product applies deliberately, to content it has
decided carries an obligation.

#### The sweeps, and the switches that start them

Three nightly sweeps run over stored objects, and **each is separately off until
its own setting asks for it**. The capability decides whether the code is there;
these decide whether it runs. All are class `optional`: step 7 asks, and enter
leaves each off, which is what you want until the product stores files.

| Setting | Unset | Why it is opt-in rather than opt-out |
|---|---|---|
| `STORAGE_LIFECYCLE_ENABLED` | off | **It deletes.** Objects past their retention are removed — and a legal hold outranks it whatever the dates say |
| `STORAGE_RECONCILE_ENABLED` | off | It deletes nothing, but it lists every active tenant's prefix, which costs provider requests on every run |
| `STORAGE_BACKUP_ENABLED` | off | It bills a second destination |

Two delete or cost money and the third costs money, which is the whole reason
none of them defaults on.

**`STORAGE_PENDING_STALE_HOURS`** is a parameter of the reconciliation sweep
rather than a switch of its own: hours a `pending` file row is given to become
`ready` before the sweep counts it as stale. **24 when unset**, and it does
nothing at all while `STORAGE_RECONCILE_ENABLED` is off.

Twenty-four hours, when the signed URL itself lasts fifteen minutes, is
deliberate. Anything still pending at the sixteenth minute is already never
completing — but clock skew, a retried confirm, a slow client and a queue
backlog all leave a row briefly pending while nothing is wrong. A day is past
every benign explanation, and since the outcome is a number in a report rather
than a deletion, waiting costs nothing. A rising `stale_pending` count is a
signal about the *upload path* — a confirm failing silently, clients abandoning
uploads, quota refusals at confirmation — not about storage.

**What reconciliation can and cannot see.** It covers the platform's default
bucket only. The worker holds the platform's own credentials and nothing else: a
customer's storage policy is read by the API with that customer's token, and the
worker has no machine identity toward the platform (F2b). A tenant whose policy
names a bucket of their own is therefore counted **unverifiable**, not missing —
the difference between "the object is gone" and "the object is somewhere this
process cannot look" is the difference between an alert and a false alarm.

**A copy in the same bucket is not a backup.** `STORAGE_BACKUP_ENABLED` needs a
destination, and the bucket is created by a person rather than by Terraform — the
storage module provisions none, which is why `STORAGE_BUCKET` is `supplied` at
all. A copy beside the original survives a deleted object and nothing else: not a
deleted bucket, not a mistaken lifecycle rule, and not a compromised key, which
reaches every object that key reaches. Use a different bucket at least, and a
different provider where the data is worth a second bill.

**Each sweep has a per-pass ceiling, and the two are not the same kind of
number.**

| Setting | Unset | The ceiling is there to contain |
|---|---|---|
| `STORAGE_PURGE_LIMIT` | 500 | **A mistake.** It is what stands between a mistyped retention floor and an empty bucket by morning: instead of losing everything you lose 500 objects, notice, and fix it |
| `STORAGE_BACKUP_LIMIT` | 2000 | **A bill.** The dangerous moment for backup is day one, when an entire existing corpus is unbacked and one night's pass would copy all of it across egress and storage on a second destination |

Both are per pass across the whole estate, not per tenant — so one misconfigured
tenant can consume the whole budget while other tenants' work waits. That is
acceptable for a safety ceiling and worth knowing before tuning either.

`STORAGE_PURGE_LIMIT` is the one not to raise. It is not a throughput knob: it is
the only thing containing the setting most likely to be misunderstood, which is
`STORAGE_RETENTION_DAYS_STANDARD` two prompts earlier. A genuine retention
backlog of more than 15,000 objects a month deserves a person looking at it
rather than a larger number. `STORAGE_BACKUP_LIMIT` may reasonably be raised
*temporarily* to clear an initial backlog and then put back; a permanently high
ceiling is a bill waiting for a large tenant.

A third ceiling sits outside this section and guards a third thing again:
`AI_REQUESTS_PER_MINUTE` contains abuse rather than a mistake or a bill. All
three default to a value chosen to be survivable, and none is a performance
setting.

**Turn them on in order, on dev, with a person reading the first report.**
Reconciliation first, because it is the one that only looks; lifecycle last,
because it is the one that deletes. The reconciliation sweep in particular was a
promise in two migration comments from `00005_files.sql` until the storage
protocol gained a listing operation, so its first output against a real bucket is
worth eyes rather than a dashboard.

#### One limit that is neither retention nor a sweep

`AI_REQUESTS_PER_MINUTE` — model calls **one organization** may make in a minute,
across all its users. **30 when unset; zero switches it off.** Also `optional`,
so enter is the answer.

It is the middle of three limits, and it exists because the other two leave a
gap: the tier-2 limiter bounds one caller's requests, the plan's monthly
allowance bounds a tenant's spend for the month, and without something in
between a loop can make a model call every few milliseconds until the month's
allowance is gone. The per-caller limiter does not see that shape, and the
monthly allowance only notices after the money has left.

It is a **setting rather than a plan entitlement, deliberately**: it exists to
stop abuse, not to sell capacity. Wanting to raise it for a paying customer is
the monthly allowance's job.

Two behaviours to know before tuning it. It is keyed on the organization the
token already proved, so it costs no tenant lookup and is one bucket per
organization. And **no Redis degrades to allowing** — as every limiter here does
— so it is a ceiling rather than a guarantee, and it will not hold during a Redis
outage.

**`optional` settings are prompted too — press enter on them.** The bootstrap
skips only class `local`; everything else is asked for, in manifest order. What
differs is what an empty answer does:

| Class | Empty answer | Run |
|---|---|---|
| `supplied` | `skipped, still missing` | **marked failed** |
| `optional` | `left unset` | fine — the default applies |
| `derived` | not asked; taken from Terraform | — |

So an `optional` you press enter on is answered, not skipped, and the line
confirming it says `left unset`. A line that says `set` means a value was
written. Input is read with `read -rs` and is not echoed, so a typo is invisible
at the prompt and surfaces wherever the value is first parsed — a
`STORAGE_RECONCILE_ENABLED` of `y` rather than `true` fails at worker startup,
not here.

Undo one with `doppler secrets delete <NAME> --project <product> --config <env>`.
Deleting is the right correction rather than writing the default in by hand: an
explicitly written value stops tracking the default if the default ever moves.

**An empty answer to a `supplied` setting is not recorded.** Pressing enter
prints `skipped, still missing`, writes nothing, and marks the run failed; the
script then hands off to `doppler-check.sh`, which reports it as absent. That is
correct behaviour for a `supplied` setting — there is no such thing as one that
is legitimately empty, which is what the class means.

**F5a is done, and this passage used to describe the workaround for it.** The
prompt could not express "there is none", so the settings that are legitimately
empty had to be written directly with `printf '' | doppler secrets set …`. They
no longer do: those settings are class `optional`, enter answers them, and the
script prints `left unset`. `doppler-check.sh` requires only names that are
neither `local` nor `optional`, so an unset optional passes it — the guarantee is
unchanged and the workaround is gone.

If you are reading an older copy of this runbook that tells you to write empty
values by hand, that copy predates the fix.

Values are read with `read -rs` and piped to `doppler secrets set` on stdin, so
none reaches `ps` output or shell history. Already-set values are skipped unless
`--overwrite`. A value that appears in a committed Terraform artifact is
**refused**: it has been published, and storing it would record a burned
credential as live. Rotate and paste the new one.

**On Windows**, `make` resolves `bash` itself and finds Git Bash, so steps 7 and
8 work from PowerShell unchanged. Step 5 and the `--dry-run` in step 6 are typed
as `bash ...` and need the explicit path — see the note above.

---

## Secrets for step 9

Two credentials, and they are set up in completely different ways for a reason
that is worth knowing before you start: one belongs to the factory and is
stored, the other belongs to *you* and is not.

| | What | Where it lives | How long it lasts |
|---|---|---|---|
| 1 | The payment provider's secret key | Doppler, once per estate | Until rotated |
| 2 | Your own staff token | An environment variable, per run | Hours |

### 1. The provider key — in Doppler, once

This is the factory's key, not a product's. No generated repository ever holds
one, and nothing in a product's template reads it: it is read by the operator
running `create-koras-app`, which is why it sits beside the other provisioning
credentials rather than in the product's own config.

**Where it goes:** the `koras-platform-bootstrap` project, `prod` config. That
is the config the factory already re-execs itself under — the same one
`bootstrap:doctor`, `teardown` and `pnpm koras:token` read — so no `doppler run`
wrapper is typed and no outer one should be.

**`prod` is the config's name, not the target estate.** It holds the
bootstrap credentials for the whole estate; which environment a command acts
on comes from the Control Plane URL, not from here.

**Where the value comes from:** the payment provider's dashboard, Developers →
API keys, the **secret** key. Use the **test-mode** key. Live mode is for
production only and is refused anywhere else — see the note below.

```bash
# Read it without echoing and pipe it in on stdin -- the same pattern
# doppler-bootstrap uses, so the value reaches neither `ps` nor your history.
read -rs -p 'provider secret key: ' KEY && printf '%s' "$KEY" | \
  doppler secrets set KORAS_BILLING_PROVIDER_KEY \
    --project koras-platform-bootstrap --config prod && unset KEY

# Confirm the name is there. Prints names, never values.
doppler secrets --project koras-platform-bootstrap --config prod \
  --only-names | grep KORAS_BILLING
```

Nothing else is added to Doppler for step 9. The Control Plane URL, its project
id and the `ZITADEL_*_DOMAIN` family are already in that config, put there when
registration was set up, and the environment is derived from the URL rather than
answered separately.

### 2. Your staff token — per run, not stored

**There is no service account for this, and one cannot be created.** Writing a
price onto a plan needs the platform **billing** role; a platform role requires
a second factor; a machine identity has no interactive authentication to
reference, so its token is refused at verification. The Control Plane's verifier
says it outright: machine identities are how products and internal jobs call the
platform API, and they are never granted platform roles.

So the credential is yours, and it is the same one the walkthrough uses for any
staff call that has no console form:

1. Sign in to the **Control Plane console** for the environment you are
   provisioning, as an account holding `platform_billing`, `platform_admin` or
   `platform_super_admin` — **with a second factor**. A sign-in without one
   produces a token the API refuses, and the refusal looks like an expired one.
2. Open DevTools → **Application** → Cookies → the console's own origin.
3. Copy the **Value** of the cookie named `id_token`.
4. Export it in the shell you are about to run step 9 in:

```bash
export KORAS_CONTROL_PLANE_BILLING_TOKEN='<paste>'
```

**It has to be the Application tab.** The cookie is `httpOnly` on purpose, so a
script injected into the page cannot read the session — which means
`document.cookie` in the browser console returns nothing, and that looks exactly
like the cookie being absent. DevTools shows `httpOnly` cookies anyway; that is
why this route works and the obvious one does not.

**Check it before running step 9**, because the failure it prevents happens
after prices have been created:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "authorization: Bearer $KORAS_CONTROL_PLANE_BILLING_TOKEN" \
  "$KORAS_CONTROL_PLANE_URL/api/platform/v1/plans?product_code=<name>"
```

`200` is good. `401` is expired, or a sign-in without a second factor. `403` is
the role — the account is staff but not billing staff.

**Why it is not stored.** It lasts hours. A copy in Doppler would be wrong more
often than right, and its failure would arrive in the middle of provisioning
rather than where somebody could fix it. A credential shorter-lived than the
gap between uses belongs in the shell that uses it. Decided 2026-09-23, and it
changes when the machine door lands.

**A service-account key is refused rather than attempted.** If
`KORAS_CONTROL_PLANE_BILLING_KEY_JSON` is set, step 9 stops and says why —
because the `401` it would otherwise earn is indistinguishable from an expired
token, and somebody would spend an afternoon on it. That variable is reserved
for when the catalogue endpoints learn to admit a named machine, which is the
proper fix and is recorded in `docs/FOLLOW_UPS.md` F29.

### What step 9 does with them

The provider key creates products and prices. The staff token writes their
references onto the plans and records what each plan was sold as. Neither
credential is logged, and neither appears in any failure message: the redactor
knows the provider's key prefixes and the client adds the token in hand to what
it must never print.


## Provisioning the catalogue for a product that already exists

Step 9 above is the sequence for a product being provisioned from nothing. A
product registered before the catalogue existed needs one step in front of it,
because the file step 9 reads is generator-written and that product was
generated before there was one to write.

Everything else is identical, credentials included — see **Secrets for step 9**.

### 1. Give it the catalogue file

```bash
cd /c/repos/Projects/koras-saas-starter

# Preview. Writes nothing.
pnpm create-koras-app <name> --profile product \
  --refresh .koras/billing-catalogue.yaml --dry-run --output-dir ../

# Write it.
pnpm create-koras-app <name> --profile product \
  --refresh .koras/billing-catalogue.yaml --output-dir ../
```

`--output-dir ../` because a real product sits beside the starter rather than
under `output/`. It reports `Refreshed 1 file(s)` and touches nothing else:
`--refresh` writes only the paths it is given.

**Safe to re-run.** A file already matching what the generator would write is
reported unchanged rather than rewritten, so this does not clobber amounts
somebody has edited.

### 2. Read it, and change what differs

It arrives holding the platform standard, so a product selling at the standard
needs no edit at all. Check the amounts and the included counts against what
this product actually sells, and change the numbers that differ.

**The storage figures are the platform's, not this product's.** They are
restated in the file so a product can override them in the one place a product
overrides anything — and a product whose storage differs from 5, 50 and 250
gigabytes has to say so here.

**`limits` is recorded and acted on by nothing yet.** The platform holds one
set of limits shared by every product; a per-product value has nowhere to go
until that changes. Editing it records the intent and changes no customer's
storage today. The command lists this on every run, which is the point — an
inert field that says so is not a promise.

### 3. Dry run

```bash
pnpm create-koras-app <name> --profile product \
  --provision-billing --dry-run --output-dir ../
```

**Read it before going further.** It prints every amount in minor units *and*
in major units side by side — `9900 (99.00 usd)` — which is the arrangement
that catches a factor-of-a-hundred error before it becomes a price somebody is
charged. It also prints every lookup key and every declared field nothing acts
on yet.

It sends nothing, and it reads nothing from the provider either, so it cannot
say which of those already exist. That is what the run itself reports.

### 4. Provision

```bash
pnpm create-koras-app <name> --profile product \
  --provision-billing --output-dir ../
```

For a catalogue on the standard shape that is: a provider product and two
prices per priced tier, one more product and two prices for the additional
internal user, the price references and recorded amounts written onto each
plan, and one catalogue version recorded per plan.

Nothing is deleted, archived or re-priced. The negotiated tier gets no price.

### 5. Run it a second time

```bash
pnpm create-koras-app <name> --profile product \
  --provision-billing --output-dir ../
```

**Expect `already current; nothing was created or written`.**

This is the step worth doing rather than assuming. Idempotence is asserted
against a fake provider in the factory's own tests, and a fake answers what it
was told to answer; the second run against a real account is the only thing
that shows a price is found by its lookup key rather than created again. A
second run that creates anything is a defect, not a quirk.

### If it refuses

Nothing is left half-done. Prices are addressed by lookup key, so a re-run
finds what the last one made and carries on from there.

| What you see | What it is |
|---|---|
| `Skipped: … is not in this project` | Step 1 has not been done |
| `declares no plans` | The file was emptied rather than edited |
| HTTP 401 | The staff token expired, or the sign-in used no second factor |
| HTTP 403 | The account is staff but does not hold the billing role |
| A plan code refused | The catalogue names a tier the Control Plane does not hold for this product. It lists both sides; a mistyped code is refused rather than created, because the endpoint would otherwise make a real priced tier that grants nothing |
| A live key refused | The provider key is a live one and the target is not production |

**A failure after the prices exist says so.** If the provider work succeeded and
only the record of what was sold did not, the message says that rather than
reporting a total failure — the difference between a safe retry and somebody
going to look for prices that are already there.


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
