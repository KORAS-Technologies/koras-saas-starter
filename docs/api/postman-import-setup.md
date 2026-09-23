# Postman import & setup

Step by step: get a KORAS Postman collection open, pointed at a running DEV
API, and returning real responses. For how the collection is generated and
what it's allowed to contain, see `docs/api/postman-standard.md`.

## Local, or deployed dev? Pick one before you start

Both use the exact same collection and environment file -- only the base URL
and where you sign in change. Don't mix them: a token from one environment's
ZITADEL is refused by the other.

- **Local** -- you have the repository's stack running on your own machine
  (`pnpm stack:up` / `pnpm dev`, or the control-plane's equivalent). Base URL
  stays at the environment's shipped default (`http://localhost:8000` or
  `:8001`), or whatever `local/.env` resolved to if that port was taken --
  step 4's "Local" bullets.
- **Deployed dev** -- you want to hit `*-api-dev.fly.dev`, the shared dev
  instance everyone's changes land on after merge. Base URL has to be edited
  to the Fly hostname, and your token has to come from that same dev
  ZITADEL, not your laptop's local one -- step 4's "Deployed dev" bullets and
  step 5.

If you don't know which one you need: if you're testing a change before it's
merged, or the stack is already running on your machine for other reasons,
use **local**. If you're checking what's actually live after a merge, or
your machine doesn't have the stack running, use **deployed dev**.

## 0. Verify it works, before anything else

This confirms Postman, the import, and the base URL are all correct --
nothing here needs a token, an organization, or any setup beyond step 1-3.

1. Do steps 1-3 below (locate the files, import both, select the
   `<Name> - DEV` environment).
2. Open **CI Smoke** at the top of the collection -> **Liveness**.
3. Hit **Send**, with no other setup.
4. You should get back `200` and a small JSON body (`{"status": "ok"}` or
   similar). That's it -- setup works.

If you get anything else, don't go further until it's fixed:

- **`ECONNREFUSED` or a timeout** -- nothing is listening on the base URL.
  Local: is the stack actually up? Deployed dev: did you leave the base URL
  at `localhost` instead of switching to the Fly hostname (step 4)?
- **A response, but not `200`** -- you're reaching *a* server, just not the
  right one, or it isn't healthy. Check the base URL value against step 4
  again.
- **Every `{{variable}}` in the request stays literally unresolved** -- the
  environment isn't selected (step 3).

## Who should test, and as whom

There is no shared seeded test account -- each environment (your laptop's
local ZITADEL, and the shared dev ZITADEL behind `*-api-dev.fly.dev`) is its
own identity provider with its own users, and putting a password in a doc
that gets committed is exactly the kind of secret exposure `.claude/CLAUDE.md`
refuses. Get an identity the same way a real one would exist:

- **Testing as a customer** (product `apps/web`/`apps/portal` routes,
  anything a paying organization would call): sign yourself up. Every
  product's signup is self-serve (`/signup` on `apps/web`) -- the first
  person to sign up for a new organization becomes its owner automatically,
  which is exactly the identity most product requests need. Locally, the
  verification email lands in Mailhog, not your real inbox --
  `http://localhost:8025` by default (`KORAS_PORT_MAIL_UI`, check
  `local/.env` if that port moved). On deployed dev, it goes to whatever
  address you actually used, for real.
- **Testing as staff** (a product's `apps/admin`, or the Control Plane's
  `apps/admin`/platform routes): staff access is not self-serve by design --
  a customer signing up and granting themselves a platform role would be the
  registrar problem this estate has already found and closed once (see
  `FOLLOW_UPS.md`). You need an account that already holds that role. If you
  don't have one:
  - **Local** -- create it yourself in your own local ZITADEL console
    (`http://localhost:8080` by default, `KORAS_PORT_ZITADEL`) and grant it
    the role the request needs; it's your own throwaway instance.
  - **Deployed dev** -- ask whoever administers that repository's dev
    ZITADEL instance for a staff account, or use one you already have. This
    doc can't hand you one.
- **Testing the Security & Negative folder** (step 7): some cases
  specifically want an identity *without* the access being tested --
  `no_tenant_access_token` is a real token for a real person, just one with
  no organization provisioned in this product. Sign up a second, separate
  throwaway account for it rather than reusing your main one.

## 1. Locate the files

Every KORAS repository that carries an API ships its collection and
environment at the same two paths:

```
postman/<Name>-DEV.postman_collection.json
postman/environments/DEV.postman_environment.json
```

| Repository | `<Name>` in the path above |
|---|---|
| `koras-control-plane` | Koras-Control-Plane |
| `docoris` | Docoris |
| `lexveria` | Lexveria |
| any product generated from this starter | the project's own name |

These files live in each of those repositories, not in this one -- this
starter has no `postman/` directory of its own to check them against.

If the files look out of date (missing a route you know exists), regenerate
them first -- see step 8 -- rather than importing something stale.

## 2. Import into Postman

1. Open Postman (desktop app or web).
2. **Import** (top left) -> **Files** -> select both files from step 1: the
   collection and its DEV.postman_environment.json.
3. Postman adds the collection to your workspace and the environment to your
   environment list. Nothing runs yet -- every request needs the environment
   selected first (next step).

## 3. Select the environment

Top-right corner of Postman -> the environment dropdown -> pick
**`<Name> - DEV`**. Without this selected, every `{{control_plane_base_url}}`
/ `{{product_base_url}}` / `{{access_token}}` in a request stays literally
unresolved and every call fails.

## 4. Set the base URL

**Set only the one variable the collection you imported actually calls** --
`control_plane_base_url` for the Control Plane collection, `product_base_url`
for any product's. The other one is present in the file but unused (see the
note at the end of this step); leave it alone.

### Local

- The environment ships with this default already set -- change nothing if
  your stack is on its default port:

  | Variable | Default |
  |---|---|
  | `control_plane_base_url` | `http://localhost:8000` |
  | `product_base_url` | `http://localhost:8001` |

- If your local stack runs on a different port (`local/scripts/ports.sh`
  resolves one per machine when the default is taken), check `local/.env`
  for what it actually picked and use that instead.
- To change it: open the environment (the eye icon, or Environments in the
  sidebar -> edit) and update the value.

### Deployed dev

- The API has no DNS record of its own (`docs/ENVIRONMENT_STRATEGY.md`) -- it
  answers on its Fly hostname, a different host from the
  `admin-dev.<apex>` / `app-dev.<project>.<apex>` addresses you sign into in
  step 5:

  | Variable | Set it to |
  |---|---|
  | `control_plane_base_url` | `https://koras-control-plane-api-dev.fly.dev` |
  | `product_base_url` | `https://<that product's project slug>-api-dev.fly.dev`, e.g. `https://docoris-api-dev.fly.dev` |

- The generator only ever produces a **DEV** collection and environment
  (`tooling/postman/README.md`) -- there is no generated `-test` / `-stg` /
  `-prod` variant to import. Pointing the same environment at another Fly app
  (`<project>-api-test.fly.dev`, per the naming in
  `docs/ENVIRONMENT_STRATEGY.md`) works, since it is only a URL, but it is a
  manual edit you are making yourself, not a supported second file --
  `access_token` then has to come from *that* environment's own sign-in app,
  never from a token issued against a different environment's ZITADEL
  instance.

### Why the unused variable is there, and why that's fine

Both `control_plane_base_url` and `product_base_url` exist in every
environment file regardless of which repository generated it, and only one
of them is ever actually used:

- The Control Plane's own collection references `{{control_plane_base_url}}`
  and nothing else -- `{{product_base_url}}` sits there unused, carried along
  from the fixed set of identity variables every KORAS environment ships
  with (`generate-environment.mjs`'s `ALWAYS_PRESENT`), so switching between
  a Control Plane environment and a product environment in the same
  workspace doesn't produce a missing-variable error.
- The same is true in reverse in a product's own environment file:
  `control_plane_base_url` sits there unused.
- Leaving the unused one at its default changes nothing about what the
  collection you're actually running sends.

## 4a. Every variable in the environment, in detail

`generate-environment.mjs` writes the same fixed set of identity variables
into *every* environment file it produces (`ALWAYS_PRESENT` in that script),
then adds whatever else the specific collection actually references. That is
why a Control Plane environment and a product environment both carry
`product_id`, `tenant_id`, `user_id`, and so on, even though each collection
only ever calls a handful of them -- Postman does not error on an unused
variable, and a workspace with both environments open switches between them
without re-adding `access_token` by hand each time.

**What the Control Plane's own collection (`Koras-Control-Plane - DEV`)
actually calls**, checked against the real generated file rather than
assumed:

| Variable | What it identifies | Used by (folder / request) |
|---|---|---|
| `organization_id` | the organization/customer being managed | Organizations, Users, Products, Identity, Provision, Tenants, Domains, Branding, Storage Policy, AI Policies, AI Usage, AI Overage -- most of the Platform surface takes this |
| `tenant_id` | one organization's provisioned tenant in a specific product | `PATCH /tenants/:tenant_id` |
| `domain_id` | a custom domain attached to an organization | `POST /domains/:domain_id/verify` |
| `subscription_id` | a billing subscription | `PUT /subscriptions/:subscription_id/entitlements` |
| `job_id` | a provisioning run | `GET /provisioning/jobs/:job_id` -- "one run, with the steps it is made of" |
| `intent_id` | a social/identity-provider sign-in in progress | `POST /api/sign-in/v1/providers/intents/:intent_id` -- finishes a sign-in the provider redirected back from |
| `attempt_id` | a sign-in awaiting its second factor | `POST /api/sign-in/v1/attempts/:attempt_id/factor` |
| `access_token`, `api_version` | your credential and the API version segment | every request (step 3) |
| `control_plane_base_url`, `product_base_url` | which server a request goes to | step 4 |

**`product_id`, `product_key`, `tenant_slug` and `user_id` appear in this
environment and are not called by any request in it, checked the same way
against the collection generated as of 2026-09-23** (zero occurrences of
`{{product_id}}` etc. in the collection file). They are not dead weight to
delete -- generation always writes them, and a route added later may start
using one -- they are simply unwired as of that check. Leave them blank.

**A product's own environment (`Docoris - DEV`, `Lexveria - DEV`, ...) is the
same mechanism with different variables actually in use.** `docoris`'s
collection, for one example, calls `{{tenant_id}}` (its own `Platform` folder
-- the routes the Control Plane calls *into* the product, also runnable by
hand from here) and `{{account_id}}` (step 7's If-Match/ETag case), while
leaving `organization_id`, `domain_id`, `job_id` and the rest of the
Control-Plane-only set unused for the same reason `product_base_url` is
unused there. There is no single list that covers every product -- each one
can add its own domain and its own path parameters -- so the reliable way to
know what a *specific* environment's variables actually do is the same check
used above: open that repository's `postman/<Name>-DEV.postman_collection.json`
and search it for `{{the_variable}}`.

None of these ever holds a real value in the committed file -- `access_token`
and `product_key` ship as Postman `secret` type and blank; every ID ships
blank because a request that needs one is naming *something that must
already exist* (an organization, a tenant, a job), and the only place that
value is real is whatever `List`/`Get` request you ran to find it.

## 5. Get a real access token

There is no OAuth2 flow wired into the collection -- inventing one that
doesn't match the deployed ZITADEL client would be exactly the kind of
guessed contract `docs/api/postman-standard.md` exists to avoid. Get a real,
verifiable token the same way the application does:

- **Sign in through the running application** and pull the access token from
  the browser's network tab or your local dev tooling -- whichever your
  stack already gives you. Which app to sign into depends on the repository
  (`docoris`/`lexveria`/any generated product vs. `koras-control-plane`) and
  which token you need -- these are separate Next.js apps, on separate
  ports, each with its own `/login`:

  | Repository | App | Default dev URL | Signs into |
  | --- | --- | --- | --- |
  | any product (`docoris`, `lexveria`, ...) | `apps/web` | `http://localhost:3000` | the product's own API, `{{product_base_url}}` -- a customer identity |
  | any product | `apps/admin` ("product-admin") | `http://localhost:3001` | the same product API, but a staff identity with that product's admin role |
  | `koras-control-plane` | `apps/admin` (platform admin) | `http://localhost:3001` | the platform API, `{{control_plane_base_url}}` -- a platform staff identity |
  | `koras-control-plane` | `apps/portal` ("account") | `http://localhost:3011` | the platform API, `{{control_plane_base_url}}` -- a customer/account identity, not staff |

  - Ports are *preferences*, the same as step 4's: `local/scripts/ports.sh`
    walks upward when one is taken, which is exactly what happens the moment
    you run a product and the Control Plane on the same machine at once --
    check each repository's own `local/.env` for what it actually resolved
    to rather than assuming the default held.
  - A product has no `apps/portal`, and the Control Plane has no `apps/web`
    -- sign into whichever app the table above pairs with the token you
    need.
- **Or**, for a service/test identity, request a token directly from
  ZITADEL's token endpoint for that identity.

Paste the token into the environment's `access_token` variable (mark it as
the value, not just the initial value, if you want it to persist across a
Postman restart -- Postman does not sync a `secret`-typed variable to the
cloud by default). **Never commit a real token** -- the file in git always
ships this blank.

Tokens expire. When requests that worked start failing with 401, get a new
one and update the variable; this is expected, not a collection bug.

## 6. Run something

Start with **CI Smoke** at the top of the collection -- it's built to be
safe:

- **Liveness** (`GET /health` or `GET /api/v1/health`) needs no token at all.
  Run it first to confirm you're pointed at the right server before touching
  anything else.
- The rest of CI Smoke and every other folder need `access_token` set; a
  request whose test script finds it empty reports `pm.test.skip(...)`
  rather than failing, so an empty run there means "set the token," not
  "something is broken."

- From there, any folder is organized by the API's own tags (Organizations,
  Settings, Notifications, ...) -- open one, pick a request, hit Send.
- **Path parameters** (anything shown as `:organization_id`, `:account_id`,
  etc. in the request URL) resolve from an environment variable of the same
  name in snake_case (`organization_id`, `account_id`). Set the ones you
  need before running a request that isn't a pure list/search -- Postman
  leaves an unset path variable as literally `:organization_id` in the
  request, and you'll see that exact string echoed back in a 404 or 422 if
  you forget.
- **Request bodies** are pre-filled with realistic example values from the
  API's real schema (field names are real; the values are placeholders like
  `"string"` / `0` / today's date) -- edit them before sending a
  create/update request.

## 7. Security & Negative Tests, if you're checking the boundary rather than the happy path

The last folder in every collection. Each request there is cited to the
source file and function it exercises (`core/auth.py`, `core/tenant.py`, ...)
so you can verify the assertion against the code, not just trust it. A few
need variables the CI Smoke path never touches:

- `no_tenant_access_token` -- a real, verifiable token for an identity with
  no tenant provisioned in this product. Optional; that one case
  self-skips without it.
- `account_id` (Docoris only) -- for the If-Match/ETag concurrency case.

## 8. Regenerating

If the collection is missing a route you know exists in code, don't hand-add
it -- regenerate from the repository root:

```bash
pnpm postman:generate
```

This re-imports the API's own `app.openapi()` and rebuilds the generated
folders from scratch (your environment values are untouched; only the
collection/environment *files* are rewritten). See
`tooling/postman/README.md` for troubleshooting a failed generation.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every request fails with an unresolved `{{variable}}` in the URL | Environment not selected | Step 3 |
| `ECONNREFUSED` / request times out | Nothing is listening on the base URL | Confirm the local stack is up (`pnpm stack:up` / `pnpm dev`) and the port matches step 4 |
| `401` on everything | `access_token` empty, expired, or for the wrong ZITADEL instance | Step 5 |
| `403` where you expected success | Real authorization refusal (right token, wrong tenant/role) -- not a collection bug | Check which identity you're testing as; see the request's `description` for which dependency is refusing it |
| A request's path still shows `:something` literally | The matching environment variable (snake_case of the path param name) isn't set | Step 6 |
| CI Smoke shows everything skipped | No `access_token` set | Expected for every request but Liveness; set a token to exercise the rest |
| The collection is missing a route you added | It hasn't been regenerated since | Step 8 |
| `pnpm postman:generate` itself fails | Tooling/environment issue, not an import issue | `tooling/postman/README.md` |
