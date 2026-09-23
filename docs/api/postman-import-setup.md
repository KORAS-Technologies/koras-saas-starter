# Postman import & setup

Step by step: get a KORAS Postman collection open, pointed at a running DEV
API, and returning real responses. For how the collection is generated and
what it's allowed to contain, see `docs/api/postman-standard.md`.

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

## 4. Set the base URL (only if not running on the default port)

The environment ships with a default local address:

| Variable | Default | Used by |
|---|---|---|
| `control_plane_base_url` | `http://localhost:8000` | Control Plane collection |
| `product_base_url` | `http://localhost:8001` | any product collection |

If your local stack runs on a different port (`local/scripts/ports.sh`
resolves one per machine -- check `local/.env` for what it actually picked),
open the environment (the eye icon, or Environments in the sidebar -> edit)
and update the value.

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

  Ports are *preferences*, the same as step 4's: `local/scripts/ports.sh`
  walks upward when one is taken, which is exactly what happens the moment
  you run a product and the Control Plane on the same machine at once --
  check each repository's own `local/.env` for what it actually resolved to
  rather than assuming the default held. A product has no `apps/portal` and
  the Control Plane has no `apps/web`; sign into whichever app the table
  above pairs with the token you need.
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

From there, any folder is organized by the API's own tags (Organizations,
Settings, Notifications, ...) -- open one, pick a request, hit Send.

**Path parameters** (anything shown as `:organization_id`, `:account_id`,
etc. in the request URL) resolve from an environment variable of the same
name in snake_case (`organization_id`, `account_id`). Set the ones you need
before running a request that isn't a pure list/search -- Postman leaves an
unset path variable as literally `:organization_id` in the request, and
you'll see that exact string echoed back in a 404 or 422 if you forget.

**Request bodies** are pre-filled with realistic example values from the
API's real schema (field names are real; the values are placeholders like
`"string"` / `0` / today's date) -- edit them before sending a create/update
request.

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
