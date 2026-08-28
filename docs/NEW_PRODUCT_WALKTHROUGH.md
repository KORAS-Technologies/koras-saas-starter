# Walkthrough — a new product, end to end

> Scope: one worked example, `koras-e2e-atlas`, from nothing to a product a
> platform user can see in the Control Plane console alongside a customer
> organization and a provisioned tenant.
>
> `PROVISIONING_RUNBOOK.md` owns the general command sequence and every failure
> mode; this does not repeat it, it names the step and moves on. Where the two
> disagree, the runbook is right about provisioning and this is right about what
> happens after it. The registration contract is owned by neither and lives in
> `koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md`.

## The name is load-bearing

`koras-e2e-atlas` begins with `koras-e2e-`, which is what every guard in
`koras teardown` checks. A real estate is refused by name even with deletion
enabled. Pick this prefix when the estate is meant to be disposable, and do not
pick it when it is not.

---

## Read this first — three things that will stop you

**1. The plan catalogue is empty and has no user interface.** A provisioning run
requires a plan code. `koras-control-plane/docs/COMMERCIAL_CATALOGUE.md`
measured dev as zero plans, zero entitlements, zero subscriptions, and states
that a plan can only be created with `curl` and a staff token. Stage 4.2 is the
way through. Without it you will create the organization, start a run, and have
it name a plan that does not exist.

**2. `KORAS_CONTROL_PLANE_TOKEN` is not issued by the Control Plane**, whatever
`PROVISIONING_RUNBOOK.md` used to say. It is a ZITADEL token for a service user,
nothing provisions it, and §A below is the only description of it that exists.

**3. `doppler-bootstrap` never asks for the two Control Plane settings.** They
are deliberately absent from the environment contract so that
`make doppler-check` cannot demand them — that is what keeps R-001 working. The
consequence is that deploy-time re-registration is off until you set them by
hand. Stage 3.3.

---

# A. The two credentials, and how to get them

This section exists because the answer was not written down anywhere, and the
one sentence that tried was wrong.

## A.1 `KORAS_CONTROL_PLANE_URL`

**What it is:** the origin of the Control Plane's platform API. Scheme and host,
no path and no trailing slash — both the generator and
`local/scripts/register-with-control-plane.sh` append
`/api/platform/v1/products` themselves.

```
https://koras-control-plane-api-prod.fly.dev
```

or the custom hostname if the Control Plane's Cloudflare zone gives it one.

**Where to find it:** it is the Control Plane's own API, so it comes from the
Control Plane's estate rather than from anything this product knows. Two
reliable ways:

```bash
# From the Control Plane project's Terraform outputs.
terraform -chdir=../output/koras-control-plane/infrastructure/terraform \
  output -json | jq -r '.api_urls.value'
```

or read it off the deployment: the shared `deploy.yml` names Fly apps
`<repository>-<service>-<environment>`, so the Control Plane's production API is
`https://<its repository name>-api-prod.fly.dev`.

**Rules the tooling enforces.** It must parse as a URL; it must be `https`
unless the host is a loopback address; and it must carry no embedded
credentials — a bearer token already travels in the request header, and
`https://user:pass@host` would put a second one in the URL and in printed
output. A trailing slash is stripped rather than rejected.

**Confirm before you store it:**

```bash
curl -sS "$KORAS_CONTROL_PLANE_URL/api/v1/health"
```

## A.2 `KORAS_CONTROL_PLANE_TOKEN`

**What it is not.** There is no endpoint on the Control Plane that issues one.
Its routers are products, organizations, entitlements, tenants, domains,
branding, policies, operations, infrastructure, portal and health — not one of
them mints a credential. The description carried in this repository's documents
for months, *"bearer token the Control Plane issues to the factory"*, was wrong
in the specific way R-042 names: a claim about **where** something comes from
that nothing could contradict.

**What it is.** A **ZITADEL token for a service user**, presented as
`Authorization: Bearer`. The Control Plane verifies it in
`koras-control-plane/services/api/koras_api/core/auth.py`, which fetches the key
set from its own ZITADEL instance. Four things have to be true, and the fourth
is the one that surprises people:

| Requirement | Why | Failure |
|---|---|---|
| Signed by the Control Plane's ZITADEL instance and verifiable against its key set | A token minted by another environment cannot validate here, because the keys that would verify it are never fetched | `401` |
| Audience includes the Control Plane's `zitadel_project_id` or `zitadel_client_id` | Never widened to "any audience": a token minted for another application is not a token for this one | `401` — *addressed to another application* |
| **No** `email` claim | That is how a service user is told apart from a person | `403` |
| **No** platform role granted to it | A token carrying a platform role is classified as staff, and registration admits machines only — *"a human token must be rejected even when the human is an admin"* | `403` — *requires a machine identity* |

That last row is the trap. The instinct, on being told the factory needs
permission to register products, is to grant the service user `platform_admin`.
Doing so **breaks registration**, and the error says nothing about roles.

### Steps

1. **ZITADEL console → Users → Service Accounts → New**, in the Control Plane's
   instance for the environment you are registering against.
   - Name: `KORAS Factory`
   - Username: `factory`
2. **Grant it no platform role.** Not an omission — see the table above. It
   needs none: registration checks only that the caller is a machine.
3. **Obtain an access token addressed to the Control Plane's application.** A
   ZITADEL *personal access token* is validated by ZITADEL's own introspection
   endpoint rather than against a key set, so it will not verify here. Use the
   service user's credentials against the token endpoint — client credentials,
   or the JWT-profile grant with its downloaded key — and ask for the Control
   Plane's project as the audience.
4. **Check it before you store it**, because the failures above are otherwise
   indistinguishable:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' \
     -X POST "$KORAS_CONTROL_PLANE_URL/api/platform/v1/products" \
     -H "authorization: Bearer $KORAS_CONTROL_PLANE_TOKEN" \
     -H 'content-type: application/json' -d '{}'
   ```

   `422` is success — the token was accepted and the empty body was refused.
   `401` is the token. `403` is the identity: it has an email claim, or it has a
   platform role.

5. **Store it in Doppler**, `koras-platform-bootstrap` / `prod`, beside the URL.
   It has no command-line flag and is never to be given one: a token on a
   command line is a token in shell history, in the process table, and in
   whatever CI log echoes the command. `--control-plane-url` overrides the URL
   for one run; nothing overrides the token.

> **Nothing provisions this.** The ZITADEL Terraform module creates a project,
> its roles, an OIDC application and user grants — no service account and no
> credential. Recorded in `docs/FOLLOW_UPS.md`.

## A.3 `STAFF_TOKEN` — the one in the `curl` examples

**What it is:** the ZITADEL **ID token** belonging to a human who holds a
platform role. It is not a separate credential to create; it is what you already
have once you have signed in to the console.

The console does not call the platform API with its own authority. It stores the
provider's ID token in a cookie named `id_token` and forwards it as the bearer,
so the API applies the caller's role rather than trusting the console to have
applied it, and the audit log attributes the call to the person rather than to
the application.

**How to get one:**

1. Sign in to the Control Plane console for that environment.
2. DevTools → Application → Cookies → the console's origin → copy `id_token`.
3. `export STAFF_TOKEN=<that value>`

It expires with the session. When calls start returning `401`, reload the
console and copy it again.

**Which role you need**, read off the endpoint dependencies rather than assumed:

| What you are doing | Roles admitted |
|---|---|
| Reading anything — products, organizations, tenants | any platform role |
| Creating organizations, starting a provisioning run | `platform_super_admin`, `platform_admin` |
| Creating entitlements, plans, subscriptions | those two, plus `platform_billing` |

**Two things that will bite:**

- **MFA is mandatory for staff.** `require_mfa_for_platform` defaults to true, so
  a platform token that did not go through a second factor is rejected — as a
  `401` rather than a `403`, because it is verification that failed.
- **Exactly one platform role.** A token carrying two is treated as a
  provisioning mistake, and the **least** privileged wins, deliberately, rather
  than the check guessing upward. If an endpoint refuses a user you believe is
  an admin, look for a second role on them.

---

# B. The walkthrough

Everything runs from the starter root, `C:/repos/Projects/koras-saas-starter`.
Never type a `doppler run` wrapper: the CLIs re-run themselves under one and say
so on stdout.

## Stage 1 — provision

```bash
# 0. Estate preflight. Read-only. Never skip it.
pnpm koras bootstrap:doctor

# 1. Generate. No infrastructure is touched.
pnpm create-koras-app koras-e2e-atlas --profile product --output-dir ../output

# 2. Plan. Writes the project to disk and stops after `terraform plan`.
pnpm create-koras-app koras-e2e-atlas --profile product --provision --dry-run --output-dir ../output

# 3. Apply. `yes` must be typed in full; `y` and `Y` are refusals.
pnpm create-koras-app koras-e2e-atlas --profile product --provision --output-dir ../output
```

A failed step 3 leaves the project on disk, and step 3 refuses to overwrite it.
Retry with `--provision-only`, which skips generation and keeps existing state.
That is the normal path, not an exception.

## Stage 2 — settings, which provisioning does not do

Terraform creates the Doppler project and its four configs and never writes a
setting into them. It cannot: it does not know the Supabase password or the
ZITADEL client secret. **A completely successful apply leaves every config
empty**, and the first sign is an empty Secrets tab rather than an error.

```bash
cd ../output/koras-e2e-atlas

# Once per environment. Four Supabase projects, four privileged URLs in,
# four restricted URLs out. Keep both of each pair.
bash local/scripts/create-app-role.sh "<privileged supabase url for dev>"

bash local/scripts/doppler-bootstrap.sh --dry-run
make doppler-bootstrap        # dev, test, stg
make doppler-bootstrap-prod   # prod is skipped by the line above, deliberately
make doppler-check            # names only, never values
```

`DATABASE_ADMIN_URL` is the privileged URL you passed in; `DATABASE_URL` is the
restricted one the script printed once and stored nowhere. Losing it costs a
re-run, which rotates the credential — that is the recovery path, not a failure.

On Windows, `create-app-role.sh` needs `psql` **and** needs Git Bash by full
path: `bash` typed at a PowerShell prompt is the WSL launcher, and it reports
`psql is not installed` whether or not it is. `PROVISIONING_RUNBOOK.md` carries
the full note.

## Stage 3 — registration

### 3.1 It already happened

Registration is the last thing Stage 1 step 3 does. It builds the payload from
the Terraform outputs and posts it. You do nothing, provided §A.1 and §A.2 are
in `koras-platform-bootstrap` / `prod`.

| State of those two settings | Result |
|---|---|
| Neither set | Skipped, exit 0 — the documented bootstrap order, R-001 |
| URL set, token missing | Provisioning succeeds and **registration fails** — a misconfiguration reported as nothing-to-do is one nobody fixes |
| Both set | Registered, all four environments in one request |

### 3.2 Confirm it landed

```bash
curl -s -H "authorization: Bearer $STAFF_TOKEN" \
  "$KORAS_CONTROL_PLANE_URL/api/platform/v1/products" \
  | jq '.[] | select(.code == "koras-e2e-atlas")'
```

A read, so any platform role will do.

### 3.3 Switch on re-registration — the step nothing prompts for

Set both names in **each of the product's own four Doppler configs**, not only
in the bootstrap project:

```bash
for env in dev test stg prod; do
  doppler secrets set KORAS_CONTROL_PLANE_URL   --project koras-e2e-atlas --config "$env"
  doppler secrets set KORAS_CONTROL_PLANE_TOKEN --project koras-e2e-atlas --config "$env"
done
```

Without them the `register` job still runs, reports that no Control Plane is
configured, and exits 0 — correct behaviour, and indistinguishable from working.
With them, every deployment re-sends that environment's references, and carries
`zitadel_client_id`, which generation-time registration cannot send because its
Terraform output is marked sensitive.

`docs/REGISTRATION_LIFECYCLE.md` covers what each pass can and cannot carry.

## Stage 4 — make it visible to a platform user

### 4.1 Sign in

The staff console is the Control Plane's admin application. The user needs a
platform role on that environment's ZITADEL project, and MFA. **The product
appears under Products as soon as Stage 3.1 succeeded** — nothing further is
needed for that half of the question.

The rest of this stage is what makes an *organization* and a *tenant* appear.

### 4.2 Create a plan — the blocker

No console form exists for any of this. Needs `platform_billing` or above.

```bash
CP="$KORAS_CONTROL_PLANE_URL/api/platform/v1"
H="authorization: Bearer $STAFF_TOKEN"

curl -sX PUT "$CP/entitlements" -H "$H" -H 'content-type: application/json' \
  -d '{"code":"seats","name":"Seats","kind":"limit","unit":"user"}'

curl -sX PUT "$CP/plans" -H "$H" -H 'content-type: application/json' \
  -d '{"product_code":"koras-e2e-atlas","code":"standard","name":"Standard"}'

curl -sX PUT "$CP/products/koras-e2e-atlas/plans/standard/entitlements" \
  -H "$H" -H 'content-type: application/json' \
  -d '{"entitlement_code":"seats","enabled":true,"limit_value":25}'
```

All three, not the first two. A plan that can be created but not populated is
the same shape of half-done as a provisioning run that reports success without
creating a tenant.

### 4.3 Create the organization

From the console, or:

```bash
curl -sX POST "$CP/organizations" -H "$H" -H 'content-type: application/json' \
  -d '{"name":"Atlas Test Co","slug":"atlas-test"}'
```

`201` whether or not this call created the record. A customer buying a second
product must reuse its existing organization, so a repeated create is a
successful no-op rather than a conflict — and provisioning, which is retried,
needs it to be.

### 4.4 Onboard the organization onto the product

```bash
curl -sX POST "$CP/organizations/<organization_id>/provision" \
  -H "$H" -H 'content-type: application/json' \
  -d '{"product_code":"koras-e2e-atlas","plan_code":"standard",
       "owner_email":"owner@atlas-test.example","owner_name":"Atlas Owner"}'
```

**`202`, not `201`.** Nothing has been provisioned yet; what exists when this
returns is a job. The worker owns the sequencing, the retries and the rollback,
because a run driven from a request thread has nowhere to resume from when the
process recycles.

That run is what calls the product's inbound half — the tenant endpoints under
`/internal/platform/v1` in `services/api`. The Control Plane never writes to a
product's business tables; every interaction goes through that contract.

### 4.5 What the platform user now sees

| Console section | Shows |
|---|---|
| Products | `koras-e2e-atlas`, its environments and their infrastructure references |
| Organizations | Atlas Test Co; open it for users, granted products and identity links |
| Provisioning | the run, and each step as it completes |
| Tenants | the tenant created inside the product |
| Plans, Entitlements, Subscriptions | read-only views of what 4.2 created |
| Audit | the registration, the organization, and the provisioning actions |

A figure that renders as an em dash rather than `0` is the console refusing to
invent one: an operator who reads "0 tenants" during an API outage draws exactly
the wrong conclusion.

## Stage 5 — tear it down

```bash
# From the starter. A dry run, because KORAS_E2E_TEARDOWN is unset by default.
pnpm koras teardown koras-e2e-atlas --product-path ../output/koras-e2e-atlas
```

`--product-path` takes the generated product, not its Terraform directory.

**Read the list before enabling deletion.** A missing credential is *skipped, not
failed*: the run finishes, names it once at the top, and looks successful while
that provider's resources are still there. The two easiest to forget are
`ZITADEL_SERVICE_TOKEN`, one per instance, and `TF_TOKEN_APP_TERRAFORM_IO` for
the workspace. Check Cloudflare records specifically — they were missing from
the inventory entirely on the last live run, so eight DNS records survived a
teardown that reported nothing retained.

Delete the project directory **after** teardown, never before. Teardown reads
the Terraform organization out of the project's own backend configuration.

---

## If something does not appear

| Symptom | Look at |
|---|---|
| Product missing from the console | Did Stage 1 step 3 print a registration line? An unconfigured Control Plane skips silently and exits 0 |
| Registration returned `401` | The token: wrong instance, wrong audience, or expired. §A.2 |
| Registration returned `403` | The identity: the service user has an `email` claim, or was granted a platform role. §A.2 |
| Registration returned `422` | A contract mismatch rather than a credential problem — the request model forbids unknown fields |
| Console reads fail with `401` | `STAFF_TOKEN` expired, or the sign-in did not use a second factor |
| An endpoint refuses a user who is an admin | Two platform roles on one token; the least privileged wins. §A.3 |
| A provisioning run will not start | The plan does not exist. Stage 4.2 |
| References stale after a later deployment | Stage 3.3 was skipped, so the `register` job reports no Control Plane and exits 0 |
