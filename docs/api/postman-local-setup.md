# Koras Postman — LOCAL Environment Setup & Verification

This document covers **LOCAL development only**. For a deployed DEV
environment, use `docs/api/postman-dev-setup.md` instead — the two are not
interchangeable (different URLs, different identities, different token
sources).

Follow the numbered steps in order. Every command, port, role and route name
below is read from the real code and configuration in this repository — see
`docs/api/postman-standard.md` for how the collection itself is generated and
kept honest.

---

## 1. Purpose

By the end of this guide you will have:

1. A running Control Plane local API and/or product local API.
2. The application you actually sign in through, started.
3. A local identity with a known role.
4. A real access token, obtained the way the application itself gets one.
5. Postman variables set correctly for your machine's resolved ports.
6. Five requests run in order, each one confirming a distinct layer:
   the process is up, the token verifies, the tenant/organization resolves,
   authorization behaves as the code says, and a real feature answers.

---

## 2. Choose What You Are Testing

| Target | Collection | Login app | Identity after `make bootstrap` |
|---|---|---|---|
| Control Plane platform APIs (`/api/platform/v1/...`) | Koras Control Plane | `apps/admin` | the bootstrap `admin` user, granted `platform_super_admin` |
| Control Plane customer/portal APIs (`/api/portal/v1/...`) | Koras Control Plane | `apps/portal` | **not seeded** — see §9 |
| Product customer APIs (`/api/v1/...`) | `<Product>` collection | `apps/web` | the bootstrap `admin` user, granted `organization_owner` |
| Product administration (same routes, owner/admin-gated) | `<Product>` collection | `apps/admin` | the same bootstrap `admin` user (already owner) |

Verified from `local/zitadel/provision.py` (both profiles) and
`profiles/{product,control-plane}/manifest.yaml`'s `apps/*` declarations.

---

## 3. Prerequisites

1. Clone the repository (`koras-control-plane`, or a product generated from
   `koras-saas-starter`, such as `docoris` or `lexveria`).
2. Docker Desktop (or an equivalent) running, for the local stack's
   infrastructure containers.
3. Node.js ≥ 20, pnpm ≥ 9, Python 3.12+, `uv`.
4. Postman installed (desktop app or web).
5. Nothing else pre-provisioned — `make bootstrap` (step 4) creates the
   local ZITADEL instance, its project, and one usable identity from
   scratch. There is no separate "local users exist" prerequisite to check.

---

## 4. Start the LOCAL Environment

From the repository root:

```bash
# 1. Install dependencies and bootstrap the stack (first time, or after `make reset`)
make bootstrap
```

This runs, in order (verified from `local/scripts/bootstrap.sh`):
resolve host ports → pull/start infrastructure containers → wait for
Supabase and ZITADEL → initialize ZITADEL (`local/zitadel/init.sh` +
`provision.py`, which is what creates the one usable identity — see §9) →
apply database migrations. It prints `Run: make dev` when done.

```bash
# 2. Start every application and service
make dev
```

Equivalent to `docker compose -f local/docker-compose.yml up -d && pnpm turbo run dev`
(verified from the `Makefile`). This starts the infrastructure containers
(if not already up) and every app/service declared for the profile —
`apps/web`, `apps/admin`, `apps/marketing`, `services/api`, … for a product;
`apps/admin`, `apps/portal`, `services/api` for the Control Plane.

```bash
# 3. Verify services are actually up
make health
```

Do not skip this. `make dev` returns as soon as processes have *started*,
not as soon as they can serve a request.

---

## 5. Determine the Actual LOCAL Ports

**Mandatory.** Ports are resolved per machine and are not fixed. The
resolved values live in `local/.env`, written by `local/scripts/ports.sh`
(`make ports` to re-resolve). Read your own repository's `local/.env` before
setting anything in Postman — the table below shows the *preferred* value
each profile asks for, from `profiles/{product,control-plane}/defaults.yaml`;
what you actually get may differ if that port was already taken on your
machine.

| Service | Env var in `local/.env` | Product preferred | Control Plane preferred |
|---|---|---:|---:|
| Web (customer) | `KORAS_PORT_APP_WEB` | 3000 | — (no `apps/web`) |
| Admin | `KORAS_PORT_APP_ADMIN` | 3001 | 3010 |
| Marketing | `KORAS_PORT_APP_MARKETING` | 3002 | — |
| Portal | `KORAS_PORT_APP_PORTAL` | — | 3011 |
| API | `KORAS_PORT_SERVICE_API` | 8000 | 8010 |
| ZITADEL | `KORAS_PORT_ZITADEL` | 8080 | 8083 |

The API is what Postman calls. Confirm it with:

```bash
grep KORAS_PORT_SERVICE_API local/.env
```

The API binds to `127.0.0.1` (verified: `local/scripts/dev-service.mjs`
runs `uvicorn koras_api.main:app --host 127.0.0.1 --port <resolved>`), so
your Postman base URL is `http://127.0.0.1:<that port>` or
`http://localhost:<that port>` — both work.

---

## 6. Generate the LOCAL Postman Collection

Same command regardless of LOCAL vs DEV — the collection is generated from
your API's own code, not from where you plan to run it against:

```bash
pnpm postman:generate
```

Auto-detects a `uv`-managed Python and calls the venv interpreter directly.
If that fails, pass it explicitly: `pnpm postman:generate -- --python "uv run --no-project python"`.

Writes, at the repository root:

```
postman/<Name>-DEV.postman_collection.json
postman/environments/DEV.postman_environment.json
```

The file is still named `DEV` — that names the *server tier the collection's
own tests were written against* (an always-running, always-reachable API),
not the URL you point it at. You will overwrite `control_plane_base_url` /
`product_base_url` to a local address in §8. Do not rename the file; nothing
in the generator or in CI expects a different name.

---

## 7. Import Into Postman

1. Open Postman.
2. Select or create a workspace.
3. Click **Import**.
4. Import the collection file from step 6 -- the Control Plane's is named
   postman/Koras-Control-Plane-DEV.postman_collection.json, a product's is
   `postman/<Product>-DEV.postman_collection.json`.
5. Import the environment file from step 6, postman/environments/DEV.postman_environment.json
   -- same repository, same import dialog, select both files at once.
6. Select the imported environment in Postman's environment dropdown
   (top right).
7. Open the environment (eye icon) and confirm the variables from §8 and §9
   are visible.
8. Save.

---

## 8. Configure LOCAL Base URL

### 8.1 Control Plane

Set `control_plane_base_url` to `http://localhost:<KORAS_PORT_SERVICE_API from local/.env>`
— for the Control Plane's own preferred default, that is
`http://localhost:8010`, but **use your resolved value from §5, not this
default.**

### 8.2 Product

Set `product_base_url` to `http://localhost:<KORAS_PORT_SERVICE_API from local/.env>`
— preferred default `http://localhost:8000`, again subject to §5.

Every other variable (`organization_id`, `tenant_id`, `account_id`, …) can
stay as generated (blank) until you need it — see §14.

---

## 9. Identify the Correct LOCAL Test User

`make bootstrap` creates **exactly one** usable human identity per ZITADEL
instance — verified from `local/zitadel/provision.py`'s `grant_admin()`:

| ZITADEL instance | Username | Role granted | Login app it works for |
|---|---|---|---|
| Product's project | `admin` | `organization_owner` | `apps/web` (as any member — owner is a superset) and `apps/admin` (owner/admin required) |
| Control Plane's project | `admin` | `platform_super_admin` | `apps/admin` (Control Plane's staff app) |

**Password:** printed by `local/zitadel/init.sh`'s own console output the
first time you run `make bootstrap` — not repeated here, and not the same
value across every machine's install if that script has been changed
locally. Look at your own terminal output, or re-run
`ZITADEL_URL=http://localhost:<KORAS_PORT_ZITADEL> bash local/zitadel/init.sh`
(the port from `local/.env`) in a throwaway check. `init.sh` has no default URL
and refuses to run without one.

**There is no separate `member`-only, `billing_admin`, `security_admin`, or
`platform_readonly` local identity by default.** To test a lesser role,
create a second ZITADEL user yourself:

1. Open the local ZITADEL console: `http://localhost:<KORAS_PORT_ZITADEL from local/.env>`.
2. Sign in as `admin` (above).
3. Users → Create.
4. Project → Roles → the role you want → Authorizations → grant it to the
   new user.

For the Control Plane's **portal** app (`apps/portal`, a *customer* of the
platform — organization roles, not platform roles): there is no bootstrap
identity at all. A portal identity only exists once an organization has been
created and a member invited, which is a Control Plane workflow outside this
document's scope (see `docs/NEW_PRODUCT_WALKTHROUGH.md` if you need to set
one up).

---

## 10. Obtain LOCAL Authentication

**The application does not hand you a bearer token directly** — sign-in
sets an `httpOnly` cookie named `id_token` (verified:
`packages/auth/src/{index,oauth}.ts` in both profiles, `PROVIDER_TOKEN_COOKIE
= 'id_token'`, `httpOnly: true`). The API verifies this token, the same one
the application forwards to the API on your behalf — so this is the real
credential, not a workaround.

1. Open the correct LOCAL app for what you're testing (§2) —
   `http://localhost:<KORAS_PORT_APP_WEB or _ADMIN or _PORTAL, from local/.env>`.
2. Sign in with the identity from §9.
3. Complete the ZITADEL login (and its second factor, if the app requires
   one — `apps/admin` in both profiles always does).
4. Open DevTools → **Application** tab → Cookies → the app's own origin.
   (Not the Network tab, and not `document.cookie` in the console — the
   cookie is `httpOnly` specifically so page script cannot read it; DevTools'
   Application panel can.)
5. Copy the **Value** of the cookie named `id_token`.
6. In Postman, paste it into the environment's `access_token` variable.
7. Save the environment.

It expires with your session. When previously-working requests start
answering `401`, sign in again and copy a fresh value.

---

## 11. LOCAL Verification — Run These Requests in Order

Use the **`00 - Setup Verification`** folder at the top of the collection —
it exists for exactly this. It is intentionally three steps for a product
(see below for why) and offers two three-step variants for the Control
Plane, one per identity.

### Product (or Control Plane portal — same shape)

| # | Request | Token needed | Confirms | Expect |
|---|---|---|---|---|
| 1 | `RUN FIRST — Liveness` (`GET /api/v1/health`) | none | base URL is right, process is up | `200`, `{"status": "ok", ...}` |
| 2 | `RUN SECOND — Authentication & Tenant Context` (`GET /api/v1/settings/effective`) | yes | token verifies **and** an active tenant resolved for it, in one response | `200` |
| 3 | `RUN THIRD — Representative Data Read` (`GET /api/v1/notifications`) | yes | a real feature route answers for this tenant | `200` |

**Why only three, not five.** This API's `require_tenant` (`core/tenant.py`)
calls `require_auth` before it does anything else, so "the token verifies"
and "the tenant resolved" are proven by the *same* response — there is no
route that proves one without the other. And there is no safe (`GET`, no
side effect) route restricted to `organization_owner`/`organization_admin`
specifically to serve as a distinct authorization check — that boundary is
enforced on writes (`PATCH`/`PUT`/`DELETE`) and, separately, by the
product's own `apps/admin` application at the middleware level (owner/admin
+ MFA, checked before any API call happens). Forcing a fifth, fake step here
would be exactly the kind of invented contract this standard exists to
avoid.

When step 3 passes: **LOCAL POSTMAN SETUP VERIFIED.**

### Control Plane platform staff

| # | Request | Token needed | Confirms | Expect |
|---|---|---|---|---|
| 1 | `RUN FIRST — Liveness` | none | base URL, process up | `200` |
| 2 | `RUN SECOND (Platform Staff) — Authentication` (`GET /api/platform/v1/products`) | staff token, any of the 5 platform roles | token verifies and MFA was used | `200` (a token that skipped MFA is `401`, not `403` — verification failed, not authority) |
| 3 | `RUN THIRD (Platform Staff) — Representative Data Read` (`GET /api/platform/v1/organizations`) | same | a second real route answers | `200` |

When step 3 passes: **LOCAL POSTMAN SETUP VERIFIED (platform staff).**

---

## 12. LOCAL CONTROL PLANE Quick Start

1. `make bootstrap` (once), then `make dev`.
2. `make health` — confirm everything is up.
3. `grep KORAS_PORT_SERVICE_API local/.env` — find the real API port.
4. `pnpm postman:generate`.
5. Import the collection and environment (§7).
6. Select the imported environment.
7. Set `control_plane_base_url` to `http://localhost:<that port>`.
8. Run `00 - Setup Verification` → `RUN FIRST — Liveness`. Expect `200`.
9. Sign in to `apps/admin` (`http://localhost:<KORAS_PORT_APP_ADMIN>`) as
   `admin` (§9), complete MFA.
10. Copy `id_token` from DevTools (§10) into `access_token`.
11. Run `RUN SECOND (Platform Staff) — Authentication`. Expect `200`.
12. Run `RUN THIRD (Platform Staff) — Representative Data Read`. Expect `200`.
13. Explore `Organizations`, `Products`, `Entitlements`, etc. as needed;
    `organization_id` and similar variables populate from a `POST` response
    or from `GET /api/platform/v1/organizations`'s own output (§14).

---

## 13. LOCAL Product Quick Start

Steps 1–7 identical to §12, using the product's ports and
`product_base_url`.

**As a normal member (`apps/web`):**

8. Run `RUN FIRST — Liveness`. Expect `200`.
9. Sign in to `apps/web` (`http://localhost:<KORAS_PORT_APP_WEB>`) as
   `admin` (§9) — this identity is `organization_owner`, which also passes
   every `apps/web` check that only needs *any* recognised role.
10. Copy `id_token` (§10) into `access_token`.
11. Run `RUN SECOND — Authentication & Tenant Context`. Expect `200`.
12. Run `RUN THIRD — Representative Data Read`. Expect `200`.

**As Product Admin (`apps/admin`, owner/admin + MFA):**

8–10. Same as above, but sign in to `apps/admin`
(`http://localhost:<KORAS_PORT_APP_ADMIN>`) instead, and complete MFA — this
app's middleware refuses anyone without `organization_owner` or
`organization_admin` (`canAdminister()` in `packages/permissions`), 403,
before the request reaches the API at all.
11–12. Same requests, same expectation — the API-level routes in this
verification sequence do not distinguish member from owner (see §11's "why
only three").

---

## 14. Obtaining IDs

| Variable | How to obtain it | Required before first verification? |
|---|---|---:|
| `organization_id` | `GET /api/platform/v1/organizations` (Control Plane) response, or a `POST /organizations` response | No |
| `tenant_id` | `GET /internal/platform/v1/tenants/{tenant_id}` path, or a product's own tenant-scoped response | No |
| `account_id` | `POST /api/v1/accounts` response (Docoris only — `accounts.py`; absent on products without it) | No |
| `product_id` / `product_code` | `GET /api/platform/v1/products` response | No |

None of these are needed for §11's verification sequence — every request
there resolves its own context from `access_token`.

---

## 15. Troubleshooting LOCAL

1. **API does not start.** Check `make health` output and the terminal
   `make dev` is running in — a Python import error there fails silently in
   Postman as a connection refusal.
2. **Port mismatch.** You set a default (8000/8010) instead of the value in
   your own `local/.env` — re-check §5.
3. **`ECONNREFUSED` / request times out.** Nothing is listening on that
   port — confirm `make dev` actually started the API (`make health`), not
   just the containers.
4. **Health route 404.** You're hitting a path without `/api/v1` — the
   route is `GET /api/v1/health`, not `/health`.
5. **`401`.** `access_token` is empty, expired, or (Control Plane staff
   only) never went through MFA — see §10 and §11's platform-staff note.
6. **`403`.** A real refusal, not a bug: wrong tenant (product), wrong
   organization role (`apps/admin`), or a platform role that doesn't include
   what the route needs. Read the response body's `detail`.
7. **Wrong tenant / wrong organization.** You signed in as an identity
   belonging to a different organization than you expected — re-check §9;
   there is only one local identity by default.
8. **Unresolved `{{variable}}` in the request.** The environment isn't
   selected (§7 step 6), or the variable genuinely isn't set yet (§14).
9. **Path shows a literal `:something`.** The matching environment variable
   (snake_case of the path parameter) isn't set — see §14.
10. **Token expired mid-session.** Sign in again, copy a fresh `id_token`
    (§10) — local sessions are short-lived by design.
11. **Wrong local identity.** You're signed into the wrong app for what
    you're testing — recheck the matrix in §2 and the role in §9.
