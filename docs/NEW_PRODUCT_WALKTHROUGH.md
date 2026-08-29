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

**2. Neither Control Plane setting exists in the bootstrap config**, so
registration has never actually run in this estate — checked, not assumed. And
`KORAS_CONTROL_PLANE_TOKEN` is not issued by the Control Plane, whatever
`PROVISIONING_RUNBOOK.md` used to say: it is a ZITADEL token for the `registrar`
service account, it lasts 12 hours, and §A.2 is the only description of it that
exists.

**3. `doppler-bootstrap` never asks for the two Control Plane settings.** They
are deliberately absent from the environment contract so that
`make doppler-check` cannot demand them — that is what keeps R-001 working. The
consequence is that deploy-time re-registration is off until you set them by
hand. Stage 3.3.

---

# A. The three credentials, and where each comes from

Measured against the live dev estate on 2026-08-28, not described from the
shape of the code. Where a value is given below it was read from Doppler or
from ZITADEL; where a result is given it was observed.

**Neither name exists in `koras-platform-bootstrap` / `prod` today.** Listed by
name on 2026-08-28: Cloudflare, Doppler, Fly, GitHub, Supabase, Terraform,
Vercel and four ZITADEL instances' worth of settings, and neither of these
among them. So generation-time registration has never run in this estate —
every product so far was skipped as not-configured, correctly and silently.

## A.1 `KORAS_CONTROL_PLANE_URL`

The origin of the Control Plane's platform API: scheme and host, no path and no
trailing slash. The generator and
`local/scripts/register-with-control-plane.sh` both append
`/api/platform/v1/products` themselves.

**The values.** Read from `koras-control-plane`'s own Doppler configs, which
already carry this name in all four:

| Control Plane environment | Value |
|---|---|
| dev | `https://koras-control-plane-api-dev.fly.dev` |
| test | `https://koras-control-plane-api-test.fly.dev` |
| stg | `https://koras-control-plane-api-stg.fly.dev` |
| prod | `https://koras-control-plane-api-prod.fly.dev` |

The pattern is the one `deploy.yml` deploys to — `<repository>-<service>-<environment>.fly.dev`
— so it holds for any Control Plane the same pipeline built.

**Which one goes where.** Two different questions, and they have different
answers:

- **In `koras-platform-bootstrap` / `prod`**, read by the generator: there is
  one name and one value, because generation-time registration sends all four
  of a product's environments in a single request to a single registry. Point it
  at the Control Plane that owns this estate. For an acceptance run like
  `koras-e2e-atlas`, that is **dev**.
- **In the product's own four Doppler configs**, read by the deploy-time
  `register` job: each may point somewhere different, so the product's dev
  deployment registers with the Control Plane's dev and its prod with prod. If
  you have only one Control Plane, put the same value in all four.

Confirmed reachable while writing this:

```bash
$ curl -sS https://koras-control-plane-api-dev.fly.dev/api/v1/health
{"status":"ok","version":"0.1.0","environment":"dev"}
```

## A.2 `KORAS_CONTROL_PLANE_TOKEN`

### What it has to be

A **JWT access token for the `registrar` service account**, obtained from
ZITADEL by the JWT-profile grant, carrying the Control Plane's project in its
audience. Every clause in that sentence is load-bearing, and three of them were
measured by getting it wrong first.

The account already exists — `KORAS Product Registrar`, username `registrar`,
in each environment's ZITADEL instance. It has a JSON key and its access token
type is JWT, which is the setting that matters most:

```
$ GET /management/v1/users/<id>          (dev instance, 2026-08-28)

KORAS Terraform Automation   accessTokenType unset  -> Bearer
KORAS Product Registrar      accessTokenType ACCESS_TOKEN_TYPE_JWT
KORAS Provisioning Worker    accessTokenType unset  -> Bearer
```

**Why that setting decides everything.** A service account left on the default
issues an *opaque* token. The Control Plane verifies against a JWKS key set, so
an opaque token cannot be verified at all. Observed, using the Terraform
account's key against the dev Control Plane:

```
exchange      : HTTP 200          <- the grant works
expires       : 43199 seconds
form          : opaque            <- because that account is Bearer
control plane : HTTP 401          "Invalid or expired token"
```

The grant succeeded and the token was still useless. `registrar` is set to JWT
precisely so this does not happen; **do not reuse the Terraform or Worker
accounts**, and if you create a replacement, set the access token type to JWT
at creation.

The other three requirements, from
`koras-control-plane/services/api/koras_api/core/auth.py`:

| Requirement | Failure if wrong |
|---|---|
| Signed by *that environment's* ZITADEL instance | `401` — the keys that would verify it are never fetched |
| Audience contains the Control Plane's `zitadel_project_id` or `zitadel_client_id` | `401` — *addressed to another application* |
| No `email` claim — that is what marks a service user | `403` — *requires a machine identity* |
| **No platform role granted to it** | `403` — same message, different cause |

That last row is the trap. Told the factory needs permission to register
products, the instinct is to grant `registrar` the `platform_admin` role. That
**breaks** registration: a platform role reclassifies the token as staff, and
the endpoint admits machines only.

### The reference values you need

Read from `koras-control-plane`'s Doppler configs:

| Environment | Control Plane project id | ZITADEL instance | `registrar` user id |
|---|---|---|---|
| dev | `386896303700837805` | `https://auth-dev.korastechnologies.com` | `388065508789893846` |
| test | `386896303432402349` | `https://koras-test-zjjy6j.us1.zitadel.cloud` | `388159672206518965` |
| stg | `386896303432467885` | `https://koras-stg-yfcztt.us1.zitadel.cloud` | `388159782114060981` |
| prod | `386896303449179565` | `https://koras-prod-xvn69x.us1.zitadel.cloud` | `388160767641283253` |

All four `registrar` accounts exist and **all four report an access token type
of JWT**, read off each instance on 2026-08-28. So the identity side of this is
already correct in every environment; what is missing is only the key material
and the two Doppler settings.

### Minting one

**One command.** Signing an RS256 assertion is not something to do at a shell
prompt, so it is not asked of you:

```bash
pnpm koras:token          # mint and verify, store nothing
pnpm koras:token --set    # ...and write it to KORAS_CONTROL_PLANE_TOKEN
```

It fetches its own credentials from `koras-platform-bootstrap` / `prod`, the way
`bootstrap:doctor` and `teardown` do, so **no `doppler run` wrapper is typed**.
Nothing it prints is secret: not the key, not the assertion, not the token.
`--set` writes through stdin, so the token reaches neither the terminal, the
process table nor the shell history.

It needs three names in that config, and works out the rest:

| Name | What it is |
|---|---|
| `KORAS_CONTROL_PLANE_KEY_JSON` | the `registrar` service account's JSON key, downloaded from ZITADEL |
| `KORAS_CONTROL_PLANE_URL` | the Control Plane origin, from §A.1 |
| `KORAS_CONTROL_PLANE_PROJECT_ID` | that Control Plane's ZITADEL project id, from the table above |

The ZITADEL instance is **not** a fourth setting. The script reads the
environment out of the Control Plane URL — `…-api-dev.fly.dev` is dev — and
takes the instance from the `ZITADEL_DEV_DOMAIN` family already in that config.
Deriving it rather than asking is deliberate: a separately-answered instance can
disagree with the Control Plane it is supposed to belong to, and that mismatch
is a `401` indistinguishable from an expired token.

Observed on 2026-08-28 against dev:

```
==> Control Plane : https://koras-control-plane-api-dev.fly.dev  (dev)
    ZITADEL       : https://auth-dev.korastechnologies.com
    service user  : 388065508789893846
    token         : JWT, valid for 12 hours
    accepted      : yes (422 on an empty body, which is the identity passing)
```

That last line is the check worth having. `422` means the Control Plane accepted
the identity and refused only the empty body — the one outcome that tells a good
token from a merely well-formed one. The script fails with the cause named
instead: `401` points at the audience or the instance, `403` at the identity,
and an opaque token is caught before it is ever sent.

### It expires in twelve hours

**Measured:** the exchange returns a lifetime of 43,199 seconds.
`KORAS_CONTROL_PLANE_TOKEN` is read from Doppler as a finished string, so a
value stored today stops working tomorrow. It fails as a *misconfiguration* —
provisioning succeeds, registration fails, loudly — which is the right failure
and a daily one.

So mint it when you are about to use it rather than in advance.

### The whole configuration, and where it belongs

**Four names, in `koras-platform-bootstrap` / `prod`**, and only one of them is
read by the generator:

| Name | Read by | Purpose |
|---|---|---|
| `KORAS_CONTROL_PLANE_URL` | generator, `pnpm koras:token` | where to register |
| `KORAS_CONTROL_PLANE_TOKEN` | **generator** | the bearer it presents |
| `KORAS_CONTROL_PLANE_KEY_JSON` | `pnpm koras:token` only | what mints the bearer |
| `KORAS_CONTROL_PLANE_PROJECT_ID` | `pnpm koras:token` only | the audience to ask for |

That split is worth understanding, because the shape of it is temporary. The
generator reads a base URL and a finished bearer token and nothing else — see
`src/registration/config.ts`, which declares exactly those two names. It cannot
mint, so the key and the project id exist for the script rather than for the
generator, and the token is the hand-off between them.

Storing the key is therefore *not* optional dressing: without it there is
nothing to re-mint from when the token expires twelve hours later.

That config is the right home because it is the factory's own credential store:
`GITHUB_TOKEN`, `FLY_API_TOKEN` and the four
`ZITADEL_DEV_SERVICE_ACCOUNT_KEY_JSON`-style keys already live there, and the
generator re-runs itself under it.

Not `koras-control-plane`'s configs — those are the Control Plane's *runtime*
settings, loaded into its Fly machines at boot. A credential for calling the
Control Plane, held by the Control Plane, points the wrong way and would be
shipped to a process that never uses it.

Not a product's configs either. Stage 3.3 is why, and it matters more than it
looks.

**The URL and the token must agree.** Both names are singular because
generation-time registration targets a single registry. The token has to have
been minted in the ZITADEL instance belonging to whatever Control Plane the URL
names: a URL on prod with a token minted in dev is a `401` that reads as an
expired token.

The token has no command-line flag and must never be given one — a token on a
command line is a token in shell history, in the process table, and in whatever
CI log echoes the command. `--control-plane-url` overrides the URL for one run;
nothing overrides the token.

### Why this arrangement is temporary

Storing a twelve-hour credential as standing configuration is wrong, and the fix
is a code change rather than a different secret name: the generator should hold
the *key* and mint a token per call, which is what the ZITADEL Terraform
provider already does with the `ZITADEL_DEV_SERVICE_ACCOUNT_KEY_JSON` family.
Registration is the one caller that never adopted that pattern.

Tracked as `F2a` in `docs/FOLLOW_UPS.md`. Until it lands, the two names above are
the complete and only configuration.

## A.3 `STAFF_TOKEN` — the one in the `curl` examples

Not a credential you create, and not related to registration. Registration is
machine-to-machine; this is *you*, acting as staff, and it is only needed where
the console has no form.

**You may not need one at all.** Every read in this document has a console page
showing the same thing — Products, Organizations, Tenants — and needs no token.
A staff token is required for stage 4.2, which creates a plan and its
entitlement, because those have no user interface.

**What it is.** The ZITADEL **ID token** for a signed-in human holding a platform
role. The console does not call the platform API with its own authority: it
stores the provider's ID token in a cookie named `id_token` and forwards it as
the bearer, so the API applies your role and the audit log names you rather than
the application.

**How to get one:**

1. Sign in to the Control Plane console for that environment.
2. DevTools -> **Application** -> Cookies -> the console's own origin.
3. Copy the **Value** of the cookie named `id_token`.
4. `export STAFF_TOKEN='<paste>'`

**It has to be the Application tab.** The cookie is set `httpOnly` on purpose,
so a script injected into the page cannot read the session. `document.cookie` in
the browser console therefore returns nothing, which looks exactly like the
cookie being absent. DevTools shows `httpOnly` cookies anyway; that is why this
route works and the obvious one does not.

Check it before relying on it:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "authorization: Bearer $STAFF_TOKEN" \
  "$KORAS_CONTROL_PLANE_URL/api/platform/v1/products"
```

`200` is good. `401` is expired, or a sign-in that did not use a second factor.
`403` is the role.

**Which role**, read off the endpoint dependencies rather than assumed:

| What you are doing | Roles admitted |
|---|---|
| Reading — products, organizations, tenants | any platform role |
| Creating organizations, starting a provisioning run | `platform_super_admin`, `platform_admin` |
| Creating entitlements, plans, subscriptions (stage 4.2) | those two, plus `platform_billing` |

**Two things that bite.** MFA is mandatory for staff —
`require_mfa_for_platform` defaults to true, and a token that did not go through
a second factor is rejected as `401`, not `403`, because verification is what
failed. And a token carrying **two** platform roles resolves to the *least*
privileged, deliberately, rather than guessing upward: if an endpoint refuses
someone you believe is an admin, look for a second role on them.

It expires with the session. When calls start returning `401`, reload the
console and copy it again.

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

**The console answers this**: Products lists the product with a tag per
registered environment, and needs no token. The call below is the same read,
for when you want it in a script.

```bash
curl -s -H "authorization: Bearer $STAFF_TOKEN" \
  "$KORAS_CONTROL_PLANE_URL/api/platform/v1/products" \
  | jq '.[] | select(.code == "koras-e2e-atlas")'
```

A read, so any platform role will do.

### 3.3 Deploy-time re-registration — leave it off for now

**Recommendation: do not set these in the product's Doppler configs yet.** The
`register` job will report that no Control Plane is configured and exit 0, which
is correct, and the references will be those of generation day.

The reason is not that the job does not work. It is what switching it on would
require you to put in a product's CI.

`registrar` is an **estate-wide** identity: a token minted from its key can
register, and therefore rewrite, the registry entry of *any* product. Copying
that key or a token from it into `koras-e2e-atlas`'s Doppler configs makes
anyone who can read that product's deployment credentials able to rewrite every
other product's registration. For one disposable acceptance product that is a
poor trade, and for a real one it is the wrong shape outright.

The right credential for this already has a name and a place in the contract.
`CONTROL_PLANE_API_KEY` is declared in the product's own environment contract
and in `secrets.manifest` as *supplied*, and `PROVISIONING_RUNBOOK.md` describes
it as "issued by the Control Plane when the product registers". Nothing issues
it: the registration response carries an id, a code, a name, a slug, a profile,
a status and a list of environments, and no credential. So the per-product
credential this job should authenticate with was designed, written into the
environment contract, and never built.

Until it is, generation-time registration is the whole story, and a product's
references are refreshed by re-running `--provision-only`. Tracked as `F2b` in
`docs/FOLLOW_UPS.md`; `docs/REGISTRATION_LIFECYCLE.md` covers what each pass can
and cannot carry.

## Stage 4 — make it visible to a platform user

### 4.1 Sign in

The staff console is the Control Plane's admin application. The user needs a
platform role on that environment's ZITADEL project, and MFA. **The product
appears under Products as soon as Stage 3.1 succeeded** — nothing further is
needed for that half of the question.

The rest of this stage is what makes an *organization* and a *tenant* appear.

### 4.1a The object model, and why the order is forced

Six objects, and each step exists because the next one cannot be expressed
without it. Nothing here is ceremony.

```text
product          registered by the generator          Stage 3
  |
  +-- entitlement          a capability that can be granted     PUT /entitlements
  |     |                  product_code optional: omit it and the
  |     |                  entitlement applies to every product
  |     |
  +-- plan                 a named bundle, belongs to a product PUT /plans
        |
        +-- plan entitlement   what this plan grants, and how much
                               PUT /products/<code>/plans/<plan>/entitlements

organization     the customer                          POST /organizations
  |
  +-- subscription         organization + product + plan
  |                        created by the provisioning run, or PUT /subscriptions
  |
  +-- subscription entitlement    an override for this customer alone
                                  PUT /subscriptions/<id>/entitlements
```

**Nothing resolves without a subscription.** The Entitlements page joins
subscriptions to organizations and products; with no subscription there is no
row to resolve, which is what *"This organization holds no subscription for
&lt;product&gt;, so nothing resolves"* is telling you. Creating an organization
does not create one.

### 4.1b How a value is decided

Three tiers, resolved **per field** rather than per entitlement:

```text
subscription override   >   plan   >   catalogue default
```

Each field takes the value from the highest tier with an opinion about it.
`null` means *no opinion*, not *off* — so a plan row that sets only a limit
leaves `enabled` to the catalogue rather than silently disabling the feature.
The `source` reported beside each entitlement is the highest tier contributing
anything, which is what someone asking "why does this customer have this value"
needs to see first.

That is why a plan entitlement can set `limit_value` alone and still behave, and
why an override for one customer does not require restating the whole
entitlement.

### 4.2 Create a plan — the blocker

No console form exists for any of this. Needs `platform_billing` or above.

```bash
CP="$KORAS_CONTROL_PLANE_URL/api/platform/v1"
H="authorization: Bearer $STAFF_TOKEN"

# `kind` is boolean or quota, and nothing else. A quota needs both a default
# limit and a period -- a model validator refuses one without the other, because
# a quota with no period is a number nobody can act on.
curl -sX PUT "$CP/entitlements" -H "$H" -H 'content-type: application/json' \
  -d '{"code":"seats","name":"Seats","kind":"quota","default_limit":25,"default_period":"month"}'

curl -sX PUT "$CP/plans" -H "$H" -H 'content-type: application/json' \
  -d '{"product_code":"koras-e2e-atlas","code":"standard","name":"Standard"}'

curl -sX PUT "$CP/products/koras-e2e-atlas/plans/standard/entitlements" \
  -H "$H" -H 'content-type: application/json' \
  -d '{"entitlement_code":"seats","enabled":true,"limit_value":25,"period":"month"}'
```

All three, not the first two. A plan that can be created but not populated is
the same shape of half-done as a provisioning run that reports success without
creating a tenant.

Each of those three bodies was validated against the Control Plane's own request
models before being written here. The first one previously read
`"kind":"limit","unit":"user"`, and neither exists: `kind` accepts `boolean` or
`quota`, `unit` is not a field, and the model forbids unknown ones. It was an
invented payload that nobody had checked against the schema — the same mistake,
in the same document, that section 6 of `PROFILE_ARCHITECTURE.md` had made about
the registration request.

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
| Plans, Subscriptions | read-only views of what 4.2 created |
| Entitlements | **not a catalogue browser.** It resolves what one organization may do in one product, across plan, subscription and override, so it stays empty until 4.4 has created a subscription |
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
