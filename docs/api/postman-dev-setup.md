# Koras Postman — DEV Environment Setup & Verification

This document covers the **deployed DEV environment only**. For running
against your own machine, use `docs/api/postman-local-setup.md` instead — do
not mix the two; a LOCAL token is meaningless against DEV and a DEV base URL
is not what your local stack listens on.

---

## 1. Purpose

By the end of this guide you will have:

1. The real, deployed DEV API URL for the Control Plane and/or a product.
2. The right *browser* URL to sign in at — a different thing from the API URL.
3. A DEV identity with a known role.
4. A real access token, taken from that identity's own signed-in session.
5. Postman variables set for the deployed environment, not localhost.
6. A first-run verification sequence that proves DNS, TLS, the deployed
   service, your token, and a real feature all work — before you touch
   anything that changes data.

---

## 2. Choose What You Are Testing

| Target | Collection | Login app (browser) | Identity |
|---|---|---|---|
| Control Plane platform APIs | Koras Control Plane | `apps/admin` (Control Plane) | Platform staff, holding a platform role |
| Control Plane customer/portal APIs | Koras Control Plane | `apps/portal` | A member of an organization provisioned in this Control Plane |
| Product customer APIs | `<Product>` collection | `apps/web` | Any signed-in member of that product's tenant |
| Product administration | `<Product>` collection | `apps/admin` (product) | `organization_owner` / `organization_admin` of that tenant, + MFA |

---

## 3. Prerequisites

1. The DEV deployment you are testing is actually healthy — check
   `gh run list --branch develop` for the repository in question, or the
   Control Plane's own `/platform-health`. A red `develop` means treat
   nothing here as reliable until it is fixed.
2. You have DEV access: a real account for the product/organization you are
   testing, or platform staff access to the Control Plane.
3. The Postman collection you are about to import corresponds to the code
   actually deployed to DEV — see §5. **Do not test an old collection
   against newly deployed API code without regenerating or verifying it.**
4. Postman installed.
5. You know which product/environment you are testing — `docoris`,
   `lexveria`, `koras-control-plane`, or another generated product, and that
   it is specifically `dev` (not `test`, `stg`, or `prod` — those have their
   own URLs, by the same pattern, and this document does not cover them).

---

## 4. Identify the DEV URLs

**The browser URL and the API URL are not the same thing, and mixing them
up is the single most common mistake here.**

### Browser/application URL (for signing in — never for Postman's base URL)

Verified pattern, from `docs/ENVIRONMENT_STRATEGY.md`'s Vercel section (one
Vercel project per application per environment, named
`<project>-<app>-<environment>`, its `dev` production domain following):

```
https://<hostname-alias>-dev.<primary_domain>
```

`<primary_domain>` is that repository's own `infrastructure/terraform/terraform.tfvars`
→ `primary_domain`. `<hostname-alias>` is the app's own name, except `web`
which is served at `app` (`application_hostnames` remaps it — verified in
the same doc).

Real, verified values:

| Repository | `primary_domain` | `web` (as `app`) DEV | `admin` DEV | `portal` DEV |
|---|---|---|---|---|
| `docoris` | `docoris.korastechnologies.com` | `https://app-dev.docoris.korastechnologies.com` | `https://admin-dev.docoris.korastechnologies.com` | — |
| `lexveria` | `lexveria.korastechnologies.com` | `https://app-dev.lexveria.korastechnologies.com` | `https://admin-dev.lexveria.korastechnologies.com` | — |
| `koras-control-plane` | `korastechnologies.com` | — | `https://admin-dev.korastechnologies.com` | `https://portal-dev.korastechnologies.com` |

For a product generated later, read its own `terraform.tfvars` — do not
guess a domain that isn't there yet.

### API URL (what Postman's `control_plane_base_url` / `product_base_url` actually points at)

Verified pattern, from `docs/ENVIRONMENT_STRATEGY.md`'s Fly.io section and
`.github/workflows/deploy.yml`'s app-naming expression
(`<repo-name>-<service>-<environment>`, Fly's own default `https://<app>.fly.dev`):

```
https://<repo-name>-api-dev.fly.dev
```

Real, verified values:

| Repository | DEV API URL |
|---|---|
| `docoris` | `https://docoris-api-dev.fly.dev` |
| `lexveria` | `https://lexveria-api-dev.fly.dev` |
| `koras-control-plane` | `https://koras-control-plane-api-dev.fly.dev` |

This is what goes in `control_plane_base_url` / `product_base_url` — **not**
the `app-dev...` browser URL above.

---

## 5. Generate/Obtain the Current Collection

```bash
pnpm postman:generate
```

Run from the repository whose *deployed* code you are testing, so the
collection is extracted from the same source the DEV deployment was built
from. If `develop` has moved since the last deploy, the collection may
describe routes DEV does not have yet, or vice versa — check
`gh run list --branch develop` for the last successful `deploy-dev` run
against the commit you generated from.

Writes `postman/<Name>-DEV.postman_collection.json` and
postman/environments/DEV.postman_environment.json, same as LOCAL -- the
file name does not change; what changes is the base URL you set in §7.

---

## 6. Import Into Postman

1. Open Postman.
2. Select or create a workspace.
3. Click **Import**.
4. Import the collection JSON from §5.
5. Import the environment JSON from §5.
6. Select the imported environment in Postman's environment dropdown.
7. Confirm the variables from §7 are visible.
8. Save.

---

## 7. Configure DEV Variables

| Variable | Required initially? | Value source |
|---|---:|---|
| `control_plane_base_url` | Control Plane only | §4's DEV API URL table |
| `product_base_url` | Product only | §4's DEV API URL table |
| `access_token` | after authentication (§9) | the DEV identity's own `id_token` cookie |
| `organization_id` | later | a list/get response — see §14 |
| `tenant_id` | later | a tenant response — see §14 |
| `no_tenant_access_token` | only for the Security & Negative Tests folder's tenant-refusal case | a real token for an identity with no tenant here |

---

## 8. Identify the Correct DEV User and Role

Real, code-verified role names — do not use anything not in this list:

| Role set | Values | Applies to |
|---|---|---|
| Platform roles (Control Plane staff only) | `platform_super_admin`, `platform_admin`, `platform_support`, `platform_billing`, `platform_readonly` | `apps/admin` (Control Plane) |
| Organization roles (shared vocabulary — Control Plane portal *and* every product) | `organization_owner`, `organization_admin`, `billing_admin`, `security_admin`, `member` | `apps/portal` (Control Plane), `apps/web` and `apps/admin` (product) |

| Use case | Role needed | Login app |
|---|---|---|
| Platform management, reading products/organizations/tenants | any platform role | Control Plane `apps/admin` |
| Creating organizations, starting provisioning | `platform_super_admin` or `platform_admin` | Control Plane `apps/admin` |
| Customer's own organization (portal) | any organization role | Control Plane `apps/portal` |
| Normal product testing | any organization role | product `apps/web` |
| Product administration | `organization_owner` or `organization_admin` | product `apps/admin` |

These are not different accounts you can look up here — they are DEV
accounts that already exist for the organization/staff group you have
access to. This document does not create one for you.

---

## 9. Obtain DEV Authentication

Same real mechanism as LOCAL (§10 of `postman-local-setup.md`) — sign-in
sets an `httpOnly` cookie named `id_token`, which the application forwards
to the API as the bearer token:

1. Open the DEV browser URL for your target (§4).
2. Sign in with your DEV identity (§8), completing MFA where the app
   requires it.
3. DevTools → **Application** tab → Cookies → the app's own DEV origin.
4. Copy the **Value** of the cookie named `id_token`.
5. Paste into Postman's `access_token`.
6. Save the environment.

**Four things not to do, because the token verifies against one specific
ZITADEL instance and one specific project:**

- Do **not** use a LOCAL token against DEV. `core/auth.py` verifies against
  the environment's own ZITADEL domain (`ZITADEL_DOMAIN`, checked in `core/auth.py`);
  a local instance's keys are not that instance's keys.
- Do **not** use a token minted in another Koras environment (`test`,
  `stg`, `prod`) against `dev`. Same reason.
- Do **not** assume a Control Plane token is valid for a product's API, or
  vice versa — they are different ZITADEL projects (verified:
  `ZITADEL_PROJECT_ID` differs per repository's deployed config).
- Do **not** assume a product token grants Platform Admin permissions.
  `PlatformRole` is defined only in the Control Plane
  (`koras_platform.platform_roles`) — a product's ZITADEL project has no
  such role to grant, and a product's API code does not import that module
  at all.

It expires with your session. Sign in again and re-copy when calls that
worked start returning `401`.

---

## 10. DEV Verification — Run These Requests in Order

Use the **`00 - Setup Verification`** folder at the top of the collection.
Same real routes, same reasoning, as LOCAL §11 — repeated here against the
DEV base URL instead.

### Product (or Control Plane portal — same shape)

| # | Request | Confirms |
|---|---|---|
| 1 | `RUN FIRST — Liveness` (`GET /api/v1/health`) | DNS resolves, TLS handshakes, the deployed service answers, and `product_base_url` is the API URL and not the browser URL |
| 2 | `RUN SECOND — Authentication & Tenant Context` (`GET /api/v1/settings/effective`) | your token verifies against *this* environment's ZITADEL, and an active tenant resolved for it |
| 3 | `RUN THIRD — Representative Data Read` (`GET /api/v1/notifications`) | a real feature answers against DEV's actual dependencies (database, queue), not just the health check |

When step 3 passes: **DEV POSTMAN SETUP VERIFIED.**

### Control Plane platform staff

| # | Request | Confirms |
|---|---|---|
| 1 | `RUN FIRST — Liveness` | DNS, TLS, deployed service, correct URL |
| 2 | `RUN SECOND (Platform Staff) — Authentication` (`GET /api/platform/v1/products`) | token verifies, MFA was used (a skipped second factor is `401`, not `403`) |
| 3 | `RUN THIRD (Platform Staff) — Representative Data Read` (`GET /api/platform/v1/organizations`) | a second real route answers |

When step 3 passes: **DEV POSTMAN SETUP VERIFIED (platform staff).**

---

## 11. DEV Control Plane Quick Start

1. Set `control_plane_base_url` to `https://koras-control-plane-api-dev.fly.dev`.
2. Run `RUN FIRST — Liveness`. Expect `200`.
3. Sign in to `https://admin-dev.korastechnologies.com` with your platform
   staff account, complete MFA.
4. Copy `id_token` (§9) into `access_token`.
5. Run `RUN SECOND (Platform Staff) — Authentication`. Expect `200`.
6. Run `RUN THIRD (Platform Staff) — Representative Data Read`. Expect `200`.
7. Continue with `Organizations`, `Products`, `Entitlements`, etc. — read
   (`GET`) requests only until you are certain what a mutating one does.

---

## 12. DEV Product Quick Start

**Normal member:**

1. Set `product_base_url` to `https://<repo>-api-dev.fly.dev` (§4).
2. Run `RUN FIRST — Liveness`. Expect `200`.
3. Sign in to `https://app-dev.<primary_domain>` with a DEV member account.
4. Copy `id_token` into `access_token`.
5. Run `RUN SECOND — Authentication & Tenant Context`. Expect `200`.
6. Run `RUN THIRD — Representative Data Read`. Expect `200`.

**Product Admin:** same steps, signing in at `https://admin-dev.<primary_domain>`
instead, with an `organization_owner`/`organization_admin` account and MFA.

---

## 13. SAFE DEV Requests

**SAFE** (read-only, no state change — verified: every request below is a
`GET` in the real generated collection):

- `GET /api/v1/health`, `GET /api/platform/v1/platform-health`
- Any `GET /api/v1/settings/...`, `GET /internal/platform/v1/settings/...`
- Any `GET /api/v1/notifications`, `/audit`, `/reports`, `/files` (listing)
- `GET /api/platform/v1/{organizations,products,entitlements,tenants,domains}`
- `GET /api/portal/v1/{organization,members,products,subscriptions,billing,...}`

**CAUTION — do not run against shared DEV data without knowing what it
does** (verified: every one of these is a `POST`, `PUT`, `PATCH`, or
`DELETE` in the real collection):

- Anything under `Accounts` past a `GET` (Docoris) — creates/deactivates a
  real account.
- `Files` uploads/deletes, `Restore` approvals — real objects, real backups.
- `Holds` create/approve/release — a legal hold with real consequences.
- `Billing` change-subscription, billing-portal-session — real subscription
  and payment-provider state.
- Anything under `Platform` (`/internal/platform/v1/...`) — these are
  machine-to-machine provisioning routes; running them by hand against DEV
  can create or mutate a tenant record.
- `Organizations` create/provision, `Entitlements`, `Domains`, `Branding`
  writes — real Control Plane state other people's DEV testing depends on.

**DEV data is not disposable.** Other people and other automated jobs
(the reconciliation sweep, scheduled collectors) read and act on it.

---

## 14. DEV ID Resolution

Same table as LOCAL §14 — the mechanism doesn't change with environment:

| Variable | How to obtain it | Required before first verification? |
|---|---|---:|
| `organization_id` | `GET /api/platform/v1/organizations` response | No |
| `tenant_id` | `GET /internal/platform/v1/tenants/{tenant_id}` path, or a product's tenant-scoped response | No |
| `account_id` | `POST /api/v1/accounts` response (Docoris only) | No |
| `product_id` / `product_code` | `GET /api/platform/v1/products` response | No |

---

## 15. DEV Troubleshooting

1. **DNS/TLS failure.** Check the URL against §4 exactly — a typo'd
   subdomain resolves nowhere, or somewhere unrelated.
2. **Wrong API hostname.** You used the `app-dev...` browser domain as the
   API base URL. Use the `*-api-dev.fly.dev` one instead (§4).
3. **Frontend URL used as API URL.** Same mistake as #2, the other
   direction — a request to the Vercel domain for `/api/v1/health` will not
   reach the Fly-hosted API.
4. **`401`.** Token empty, expired, from the wrong environment, or (Control
   Plane staff) missing MFA — see §9.
5. **Token from the wrong environment.** Verified against a different
   ZITADEL instance/project than the one issuing it — see §9's four "do
   not"s.
6. **`403`.** A real authorization refusal — check the role table in §8
   against what the endpoint's own `description` field says it requires.
7. **Wrong organization/tenant.** The identity you signed in with belongs
   to a different organization than the data you expected to see — this is
   the API working correctly, not a bug.
8. **The deployment doesn't match the collection.** You generated the
   collection from a commit that hasn't deployed yet, or DEV deployed a
   commit after you generated — re-run `pnpm postman:generate` from the
   commit `gh run list --branch develop` shows as last deployed.
9. **API healthy but a dependency is failing.** `GET /api/v1/health`
   touches nothing by design (verified: `routers/health.py`); a `200`
   there does not mean the database or queue is reachable — a `500` on a
   real data request with a healthy liveness check points at a dependency,
   not the API process.
10. **Unresolved `{{variable}}`.** Environment not selected, or the
    variable isn't set yet — see §7 and §14.
