# KORAS SaaS Starter — Sync Backlog

## What this document is

The factory produces two profiles and the profiles produce repositories. Work
lands in four places and does not always land in all of them:

```
koras-saas-starter                    the factory, and its own CI
  profiles/product/template           →  (no product repository today)
  profiles/control-plane/template     →  koras-control-plane
```

`output/sample-product` filled the first row until 2026-08-30, when the estate
was deleted to close C4 and FOLLOW_UPS F1. Entries below that name it are dated
records of what was true then; the divergence they describe was real and is now
moot rather than fixed.

**The product row being empty is a gap, not a tidy state.** Every entry in this
document exists because a fix landed in one place and not another, and the
control-plane row is the only one left that can prove it. Until a product
repository exists again, product-side drift is caught by
`generator-integration.yml` generating one and building it — which is D1, and is
why D1 mattered more than this document estimated.

A fix applied downstream — in `koras-control-plane`, by hand, at the moment it
was needed — is invisible to the factory. A fix applied to one profile template
is invisible to the other. Both have happened repeatedly, and neither shows up
in a review of the repository that was changed.

This document tracks those gaps until they are closed. It is not a roadmap
(`IMPLEMENTATION_ROADMAP.md` owns forward scope) and not a risk register
(`RISK_REGISTER.md` owns defects found in operation). It holds one class of
problem only: **the same thing is true in one place and not another.**

## How to use it

Each item names the gap, the evidence, and where the corrected version already
exists. Check an item off only when it is true in *every* place the "Applies to"
line lists — a fix that reaches one template and not the other is the defect
this document exists to catch, not a partial success.

Tiers are ordered by what breaks if the item is left alone:

| Tier | Meaning |
|------|---------|
| **A** | The generator emits something that does not work |
| **B** | A capability exists in one profile and is missing or broken in the other |
| **C** | A security control exists downstream but not in the factory or the templates |
| **D** | Structural — the reason this document keeps needing entries |
| **E** | Record-keeping |

**Last full survey:** 2026-08-22, against starter `535cd58`,
control-plane `9546623`, sample-product `27f2949`.

**Closed since:** A1, A2, A3, A5, A6, B1, B2, B3, B4, B5, C1, C2, C3, D1, D3, D4,
E1, E2, E3. A4, A7 and C4 are open; C4 carries two actions no change to this
repository can close.
D2 is guarded rather than fixed; see its entry. `koras-control-plane` has not been
re-synced against any of it, and `output/sample-product` carries B4 but not B1.

---

## Tier A — the generator emits something that does not work

Verified by generating both profiles into a scratch directory and reading the
output, not by reading the templates.

### A1 — the control-plane profile does not typecheck as generated

- [x] `packages/permissions/src/index.ts` carries the real implementation
- [x] `packages/auth/package.json.hbs` declares `jose`
- [x] `packages/auth/package.json.hbs` declares `next`
- [x] `packages/auth/package.json.hbs` declares the workspace `permissions` package
- [x] `packages/auth/package.json.hbs` sets `"type": "module"`
- [x] `packages/auth/package.json.hbs` defines a `test` script

Two more were needed and the survey had not found them, because reading the
templates cannot: `packages/api-client` and `packages/types` were stubs that
`apps/admin/src/lib/session.ts` imports, and neither application declared
`api-client` as a dependency at all, so pnpm never linked it and turbo never
built it.

- [x] `packages/api-client` and `packages/types` carry the real implementations
- [x] `apps/admin` and `apps/portal` declare `@<slug>/api-client`

**Closed against evidence rather than inspection.** `pnpm install && pnpm turbo
run build` on a freshly generated project: 18 of 18 tasks, and its own auth
suite runs there — 39 tests, 0 failures.
`generators/create-koras-app/tests/generated-builds.test.ts` now does exactly
that on every run. It is slow, a couple of minutes, and it is the only test
here that would have caught this: the other 393 read the files the generator
wrote and never built the result. Verified non-vacuous by restoring the
permissions stub, which fails it.

**Applies to:** `profiles/control-plane/template`

`packages/auth/src/index.ts.hbs:16` imports `isPlatformRole` and the
`PlatformRole` type from the project's `permissions` package. The template's
`packages/permissions/src/index.ts` is two lines — a comment and `export {}`.
Line 14 imports `jose`, which no manifest declares.

The four shipped test files total 1,142 lines and never execute: without a
`test` script, `turbo run test` has nothing to call.

**The corrected version exists:** `koras-control-plane/packages/permissions/src/index.ts`
(82 lines) and `koras-control-plane/packages/auth/package.json`, both fixed by
hand in the downstream repository.

### A2 — the product profile's middleware redirects to a page that does not exist

- [x] `verifySession` either verifies a session, or the middleware stops calling it

**Closed by B1 (b71f176)**, as anticipated below: the sign-in was promoted
rather than the stub repaired.

**Applies to:** `profiles/product/template`

`packages/auth/src/index.ts:21` returns `null` unconditionally, under a comment
reading *"Verification delegated to koras-auth server-side utility."*
`apps/web/src/middleware.ts.hbs` redirects every non-public path to `/login` when
`verifySession` returns falsy. The product template ships no `/login` page and no
`/api/auth/*` route, so every authenticated path redirects to a 404 permanently.

A stub that returns `null` is worse than no stub: the middleware trusts it.

Superseded by **B1** if the sign-in is promoted rather than the stub repaired.

### A3 — a fresh product fails at API startup

- [x] `ENVIRONMENT` is set in the product `.env.local.example`

**Closed (85438d8).** Found by the contract cross-check rather than by looking:
`doppler-check` validates that every key in `.env.local.example` is classified
in `secrets.manifest`, and running it both ways showed `ENVIRONMENT` classified
and set nowhere.

**Applies to:** `profiles/product/template`

`services/api/src/core/settings.py:12` declares `environment: Environment` with
no default, commented *"a missing or misspelled value yields a valid-looking
configuration."* `local/config/.env.local.example.hbs` never sets it, so
`make bootstrap && make dev` fails on the first API start.

**The corrected version exists:** the control-plane template's
`.env.local.example.hbs` sets `ENVIRONMENT=dev` with a four-line explanation.

---

### A4 — the generated `control-plane-client` cannot produce a request the Control Plane accepts

- [ ] `ProductRegistration` in the template matches `ProductRegistrationRequest`
- [x] The template header says so, and points at the contract
- [x] `PROFILE_ARCHITECTURE.md` distinguishes the outbound half from the inbound one

**Applies to:** `profiles/product/template/packages/control-plane-client`

Promoted from `koras-control-plane/docs/starter-promotion/SYNC_BACKLOG_ENTRIES.md`,
where it was recorded as an accuracy note. It is worse than that.

`capabilities.control_plane_client` generates a package whose payload type is:

```ts
{ projectName, projectSlug, profile, githubRepository,
  zitadelProject, vercelProjects: string[], environments: EnvironmentReference[] }
```

The Control Plane's `ProductRegistrationRequest` requires `code`, `name`,
`slug`, `profile` and an `environments` **map** keyed by environment, and sets
`extra="forbid"`. Every field name above is therefore either missing or
rejected: a request built from this type is a 422 in full, not a partial match.

It has never been noticed because **nothing calls it**. Registration is
performed by `generators/create-koras-app/src/registration/`, which is written
against the contract and is correct, and now also by
`local/scripts/register-with-control-plane.sh` at deploy time. This package is
generated, compiled, shipped, and used by nothing — so the first caller to trust
it gets a 422 that reads like an authentication problem.

The accuracy note it came from is worth keeping beside it: this package is the
**outbound** half only, the client for calling the Control Plane. The inbound
half — the `/internal/platform/v1/tenants` endpoints the Control Plane calls back
into, contract §6 — is served by `services/api` and is a different thing that has
already been conflated with this one once.

**Not fixed here.** Rewriting the types is easy; deciding whether the package
should exist at all is not, and doing the first without the second leaves a
correct implementation that nothing calls, next to two that everything calls.

### A5 — registration happened once, at generation, and never again

- [x] A re-registration step in the generated deployment pipeline
- [x] It refuses to run in the Control Plane
- [x] The decision, and what each pass can carry, written down
- [x] `starter_version` and `profile_version` actually sent

**Closed.** Promoted from
`koras-control-plane/docs/starter-promotion/SYNC_BACKLOG_ENTRIES.md`.

**Applies to:** `profiles/_shared/template`

`runRegistration` is the last thing generation does, and its comment says why:
*"It reports what exists, so it runs once the repository has been pushed and
there is nothing further that could change the references being registered."*
That was true of the moment and not of the following year. Nothing re-sent a
reference, and the generated `.github/workflows/` had no registration step at
all — confirmed by looking rather than by inference: neither profile ships its
own `.github/`, and the shared `deploy.yml` ended at `verify`.

So a service added later, an environment provisioned later, a rotated ZITADEL
project, or a product generated before its Control Plane existed (R-001, the
documented bootstrap order) all left the registry holding the day the project
was generated. Reconciliation compares the registry against reality, so each of
those became drift with no explanation attached.

**What was added.** `local/scripts/register-with-control-plane.sh` in the shared
template, called from a `register` job in `deploy.yml` after `verify`. It sends
the one environment that just deployed. That is safe because the Control Plane
upserts environments and references without pruning them — read out of its
repository layer rather than assumed — and it is *only* safe under that reading,
which is why `docs/REGISTRATION_LIFECYCLE.md` records it rather than leaving it
as a property of two files in different repositories.

**The trap, named because it nearly caught this.** `deploy.yml` is shared by both
profiles, and the Control Plane must never register itself. The generator does
expose `registersAsProduct` to the template context, but that conditional is
unavailable here: `deploy.yml` is copied verbatim and must never become a `.hbs`,
because Handlebars would parse every GitHub expression in it and turn
`secrets.FLY_API_TOKEN` into an empty string. The guard is therefore at runtime,
in the script, reading `.koras/project.yaml` — the same mechanism
`check-rls-connection.sh` already uses in the same workflow.

**A defect found on the way.** `buildRegistration` declared `starter_version` and
`profile_version` on its payload type and populated neither, so every product
registered so far reads as generated from nothing in particular — the two fields
the contract provides precisely so the Control Plane can identify products
needing an upgrade. Both are sent now.

### A6 — Tailwind never compiled, and the CSP nonce never reached the renderer

- [x] `postcss.config.mjs` in `_shared/apps/admin`
- [x] `postcss.config.mjs` in `control-plane/apps/portal`
- [x] `postcss.config.mjs` in `product/apps/web`
- [x] All four `middleware.ts.hbs` set the policy on the forwarded request
- [ ] `product/apps/marketing` either gets a stylesheet or drops the dependency

**Closed** by applying `koras-control-plane/docs/starter-promotion/starter-promotion.patch`,
which was staged there on 2026-08-25 and never applied. `git apply --check`
passed against the current templates before it was used, so it was applied
rather than regenerated.

**Applies to:** both templates

Two defects latent in every generated project, neither of which shows up until
somebody writes the first line of code that depends on the broken thing.

**Tailwind had never compiled.** Every app template does `@import "tailwindcss"`,
declares `tailwindcss` and `@tailwindcss/postcss`, and shipped no PostCSS config
— there was not one `postcss.config.*` anywhere in the repository. Without it
Next handles the import with its own CSS pipeline, inlines the package
stylesheet and serves it verbatim, so the built bundle carries a literal
`@tailwind utilities` directive and no utility class exists at runtime.
Preflight still arrives, because Next resolves the package's nested imports,
which is what makes it quiet: the page looks styled. It surfaces the first time
somebody writes `bg-surface` and the element renders unstyled, at which point
the obvious suspect is their class name rather than the build.

Measured downstream before promotion: adding the config *shrank* the stylesheet
from 23,175 to 5,991 bytes, because the unused default theme block stops being
shipped whole; and applied to an app using no utility classes at all, the
rendered page was byte-identical before and after.

**The CSP nonce never reached the renderer.** All four `middleware.ts.hbs`
minted a per-request nonce, named it in the policy, and forwarded it as
`x-nonce`. Next does not read `x-nonce`. It reads `Content-Security-Policy` off
the incoming request, lifts the nonce out of it, and stamps that onto the script
tags it renders; given only `x-nonce` it finds nothing, emits bare `<script>`
tags, and the policy then blocks them. This costs nothing while every page is a
server component — there is no hydration to lose. The first client component to
ship goes dead in the browser, with a console error as the only symptom, while
the policy looks correct in every response header.

The same change collapses a duplicate: the response recomputed the policy rather
than reusing the one the request carries. Identical today, because the function
is pure and the nonce is the same — but if one gained a `connect-src` source and
the other did not, the policy the browser enforces would stop naming the nonce
the renderer used. That is this same bug one level up.

**Left open deliberately.** `product/apps/marketing` declares `tailwindcss` and
has no CSS file at all, so a PostCSS config there would do nothing. Either it
gets a `globals.css` or it drops the dependency; that is a design decision
rather than a fix.

### A7 — two role resolvers that disagree, so the console shows authority the API refuses

- [ ] One resolution rule, shared or tested against the other
- [ ] A test asserting the two agree for every combination of platform roles

**Applies to:** `profiles/control-plane/template`

Both halves are generated from this repository, so every Control Plane it
produces carries this.

A token may carry more than one platform role. Both implementations call that a
provisioning mistake and resolve *downward* rather than guessing upward, which
is right. They then disagree about which role is lower.

| Where | Rule |
|---|---|
| `packages/auth/src/index.ts.hbs` | `platform.sort()[0]` — **alphabetical** on the role string |
| `python-packages/koras-auth/src/koras_auth/__init__.py` | sorted by position in `PlatformRole`, descending |

`PlatformRole` is declared most-privileged-first, so the Python side genuinely
takes the least privileged. Alphabetical order is not privilege order, and the
two coincide only by luck:

| Roles held | Console (TypeScript) | API (Python) |
|---|---|---|
| `platform_admin`, `platform_billing`, `platform_super_admin` | `platform_admin` | `platform_billing` |
| `platform_admin`, `platform_readonly` | `platform_admin` | `platform_readonly` |
| `platform_admin`, `platform_support` | `platform_admin` | `platform_support` |
| `platform_billing`, `platform_super_admin` | `platform_billing` | `platform_billing` |

**What it looks like when it bites**, observed on dev 2026-08-28: the console
header names the signed-in operator `platform_admin`, the Plans page answers
*"Not permitted — Insufficient platform role"*, and the same call by `curl`
returns `{"detail":"Insufficient platform role"}`. The operator has been told
they hold a role the API is not applying, and nothing names the second role that
caused it.

The failure is safe — both resolve downward, so neither grants authority nobody
was given — but it is unexplainable from either side alone, and the console is
the side people believe.

**Why this is one defect and not two.** The rule is written twice because the
session is minted in TypeScript and verified in Python. Neither is wrong on its
own terms; there is simply no test that they answer the same question the same
way, and a shared table of role precedence would make the divergence impossible
rather than merely detectable.

## Tier B — capability present in one profile, absent in the other

### B1 — sign-in was promoted to the control-plane profile only

- [x] `packages/auth` — `oauth.ts` and the full `index.ts`
- [x] `packages/auth` — the four test files
- [x] `apps/web` — `/api/auth/start`, `/api/auth/callback`, `/api/auth/signout`
- [x] `apps/web` — `login/page.tsx`
- [x] `apps/admin` — `middleware.ts` (the product's admin app has none)
- [x] `apps/admin` — the same three auth routes and login page

**Closed (b71f176).** Not a copy. `oauth.ts` is profile-agnostic and moved
verbatim; everything else was adapted from one resolved platform role to a set
of organization roles, because `billing_admin` and `security_admin` are scoped
authorities a member may hold alongside others and collapsing them to one would
silently drop the rest.

`packages/permissions` defines organization roles only. A platform role
arriving in a product's token is therefore an unrecognised name that grants
nothing, which two tests assert directly.

The two applications differ where they should: `apps/web` admits any caller
holding a recognised role; `apps/admin` requires `organization_owner` or
`organization_admin` **and** a second factor, because it acts on customer data
on an operator's behalf.

**A2 is closed by this** — the `verifySession` stub that returned `null`
unconditionally is gone, and with it the redirect to a login page that did not
exist.

Verified in a generated project: build 22/22, typecheck 31/31, the auth suite
43 pass 0 fail, pytest 20/20.

**Applies to:** `profiles/product/template`

Commit `2464cc3` promoted a working OIDC sign-in into the control-plane profile:
663 lines of implementation and 1,142 lines of tests. The product profile kept
the 33-line stub.

The stub also carries a bug the control-plane has already fixed and now guards
with a test: `packages/auth/src/index.ts:32` builds the authorize URL by
concatenating `ZITADEL_DOMAIN`, treating a value that may be a bare hostname as
a base URL. See control-plane `e2324e0`, and the guard at
`profiles/control-plane/template/packages/auth/src/oauth.ts.hbs:85`.

Note that `apps/admin` — the higher-privilege surface — is the one with no
middleware at all. If that is deliberate, it needs a comment saying so.

### B2 — the product profile derives 3 of 11 settings from Terraform

- [x] Every `derived out:` line in the product `secrets.manifest` names an output
      the product's `main.tf.hbs` actually emits

**Closed against a plan, not a reading.** Six of the eight are emitted:
`primary_domain`, `zitadel_domains`, `app_urls`, `admin_urls`,
`app_redirect_uris`, `api_urls`, `storage_endpoints`, plus `ai_gateway_urls`
when that service is enabled. A plan against the live estate resolves every one
across all four environments.

Two were never derivable and the manifest now says `supplied` rather than
naming an output that cannot exist: `CONTROL_PLANE_URL` belongs to a separate
estate with its own state, and `STORAGE_BUCKET` is a name the project picks,
not a resource the storage module creates.

The URLs are computed from `primary_domain` rather than read back from
`module.bootstrap.vercel_domains`, because that map is empty until the apply
that attaches the domains — and these settings are needed by the bootstrap
that runs before it. The hostname labels match the vercel module's
`application_hostnames` default, so `web` resolves to `app` in both places.

**Still open downstream:** the Doppler configs stay at 11/31 and 1/31 until
`output/sample-product` applies. The outputs are computed but not in state, and
`doppler-bootstrap` reads state.

**Applies to:** `profiles/product/template`

`infrastructure/terraform/main.tf.hbs` is 93 lines and emits 13 outputs. The
control-plane's is 196 lines and emits 21. `local/config/secrets.manifest`
declares eleven `derived out:` settings; eight name outputs that do not exist:

| Setting | Output referenced | Emitted |
|---|---|---|
| `ZITADEL_PROJECT_ID` | `zitadel_project_ids` | yes |
| `ZITADEL_CLIENT_ID` | `zitadel_client_ids` | yes |
| `REDIS_URL` | `redis_urls` | yes |
| `NEXT_PUBLIC_APP_URL` | `app_urls` | **no** |
| `NEXT_PUBLIC_API_URL` | `api_urls` | **no** |
| `ZITADEL_DOMAIN` | `zitadel_domains` | **no** |
| `ZITADEL_REDIRECT_URI` | `app_redirect_uris` | **no** |
| `CONTROL_PLANE_URL` | `control_plane_urls` | **no** |
| `STORAGE_ENDPOINT` | `storage_endpoints` | **no** |
| `STORAGE_BUCKET` | `storage_buckets` | **no** |
| `AI_GATEWAY_URL` | `ai_gateway_urls` | **no** |

This does not crash. `local/scripts/doppler_bootstrap_support.py` treats an
unresolvable source as "ask a person", so the effect is that every product
bootstrap hand-types its application URL and OIDC redirect URI — the manual step
R-021 was raised to remove.

Either emit the outputs or delete the lines. A manifest that names outputs
nobody produces reads as configured when it is not.

### B3 — the product `.env.local.example` is missing what the sign-in needs

- [x] `SESSION_SECRET`
- [x] `CORS_ORIGINS`
- [x] The note explaining that `make bootstrap` rewrites the ports below it

**Applies to:** `profiles/product/template`

Depends on **B1**: `SESSION_SECRET` has nothing to sign until the product profile
has a session. The port note is independent and applies now.

### B4 — the RLS policy-ordering defect is fixed downstream only

- [x] Policies ship as numbered migrations, not as `supabase/policies/*.sql`
- [x] `local/scripts/migrate.sh` no longer applies a policies directory
- [x] `supabase/policies/` carries the README explaining why it is empty
- [x] `output/sample-product` regenerated and confirmed

**Closed (e5c802e).** Verified against postgres:15 rather than by reading: both
migrations apply in order, seven policies exist, RLS is on for all three tables,
and re-running the policy migration is clean.
`generators/create-koras-app/tests/rls-policy-ordering.test.ts` asserts the
shape for both profiles and was checked non-vacuous by restoring a stray policy
file, which fails it.

Two things the check turned up. The policies are now dropped before they are
created, because that is what the README asks for when a policy changes and a
file modelling the wrong pattern gets copied. And `migrate.sh` claimed every
migration is re-runnable, which was untrue of the one it ships -- `00001`
creates tables without `if not exists`. The ledger is what makes re-running
safe, and the header now says so.

**Applies to:** both templates, and `output/sample-product`

`local/scripts/migrate.sh:72` in *both* templates applies every migration and
then every file in `supabase/policies/`. On an existing database this is
invisible, because the policies file was applied before the corrective migration
ran. On a clean bootstrap the corrected policies are created and then
overwritten by the leaky ones.

**The corrected version exists:** `koras-control-plane/supabase/policies/README.md`
documents the sequence and names the defect it reintroduced (control-plane R-05,
cross-organization read). Its `migrate.sh` no longer reads the directory.

This is the oldest open item and the one with a known security consequence.

### B5 — the control-plane manifest claims storage it does not ship

- [x] `capabilities.storage` and the template agree

**Applies to:** `profiles/control-plane/manifest.yaml`

`manifest.yaml:41` declares `storage: true` and the template ships
`packages/storage` and `python-packages/koras-storage`. The same template's
`.env.local.example.hbs` states in prose: *"This profile has no MinIO/object
storage stack… Those settings belong to `--profile product` repositories."*

One of the two is wrong. The manifest is what the generator reads and what
`.koras/project.yaml` records, so it is the one that matters.

---

## Tier C — security controls that never reached the factory

### C1 — secret scanning exists in one repository out of five

- [x] `.gitleaks.toml` in `profiles/product/template`
- [x] `.gitleaks.toml` in `profiles/control-plane/template`
- [x] `.gitleaks.toml` in the starter itself
- [x] A gitleaks job in both templates' `ci.yml`
- [x] The starter's `security.yml` installs the binary rather than the wrapper
- [x] The starter's `security.yml` passes `--max-archive-depth`
- [x] The starter's `security.yml` triggers on `develop` and `test`

**Applies to:** the starter and both templates

`.gitleaks.toml` exists only in `koras-control-plane`. The starter's
`.github/workflows/security.yml` uses `gitleaks/gitleaks-action@v2` — the
marketplace wrapper that, per the control-plane's own CI comment, *"requires a
paid licence for organizations, and it refuses to run without one."* It passes
no `--max-archive-depth`, so it does not look inside archives at all. It
triggers on `main` and `staging` only, never on `develop`, where the work
happens.

**The corrected version exists:** the `secrets` job in
`koras-control-plane/.github/workflows/ci.yml`.

### C2 — the factory is not subject to its own checks

- [x] `tests/security/test_no_state_artifacts.py` present in the starter
- [x] `tests/unit/test_declared_dependencies.py` present in both templates
- [x] `tests/security/test_settings_are_declared.py` present in both templates
- [x] The starter's `tests/` runs in the starter's own CI

**Applies to:** the starter and both templates

`koras-saas-starter/tests/` contains only `.gitkeep`. The state-artifact check
protects every generated project and not the repository that holds
`private-keys/` and runs Terraform in-tree.

`test_declared_dependencies.py` is the check that **A1** needed and did not have.
Its own docstring names four prior instances of the same defect — R-34, R-39,
R-43, R-45 — each invisible locally because the monorepo shares one virtual
environment. A1 is the fifth, and the first to reach a template.

### C3 — the starter's CI is older than the CI it ships

- [x] Starter workflows on `actions/checkout@v5`
- [x] Starter workflows on `actions/setup-node@v5`
- [x] Starter workflows on `astral-sh/setup-uv@v6`

**Applies to:** `koras-saas-starter/.github/workflows/`

Both templates and both generated repositories are on v5/v5/v6. The starter's
four workflows are the only files left on v4/v4/v3.

---

### C4 — R-65 was never reported upstream, and `sample-product` still carries it

- [x] The generator writes the plan outside the project
- [x] Both templates' `.gitignore` name `tfplan`, `*.tfplan`, `*.plan.out`
- [x] `initAndPushToDevelop` refuses to commit one, checked before `git add`
- [x] Generated projects carry `tests/security/test_no_state_artifacts.py`
- [x] Both templates' `ci.yml` passes `--max-archive-depth 3`, and says what it still cannot catch
- [x] The eight exposed credentials — the estate they reach was deleted 2026-08-30
- [x] `output/sample-product`'s published history — see below

**Closed 2026-08-30 by deleting the estate.** The blob stays in history and
always will — untracking a file does not unpublish it, and rewriting a pushed
branch does not un-distribute what was already fetched. What changed is that the
credentials in it now authenticate to nothing: 41 resources across eight
providers removed, each confirmed absent by asking the provider rather than by
reading a delete response.

Rotation was the alternative and was worse here. A rotated secret protects a
resource that still exists, and there is no way to know who holds the old value;
a deleted resource is unreachable with any credential. FOLLOW_UPS F1 records
what was removed and two things found while removing it.

**Applies to:** the starter, both templates, and `output/sample-product`

`koras-control-plane/docs/RISK_REGISTER.md` R-65 ends *"Report upstream.
`koras-saas-starter` — the generator — committed this file, so every project it
produces carries the same leak."* It was never reported: this document had zero
mentions of it until now. The fix landed here (`f32711b`); the **record** of why
it landed did not, which is the failure this document exists to catch, arriving
from the other direction.

**What the leak was.** `infrastructure/terraform/tfplan`, committed by the
generator in `chore: initial project generation` and pushed. It is a zip holding
a full Terraform state snapshot: four Supabase database passwords and four
ZITADEL OIDC client secrets, in plaintext.

**Why no scanner saw it, and why no scanner can.** gitleaks decides whether to
look inside an archive from the **file extension**, and Terraform writes plan
files without one. Measured rather than inferred: `tfplan` scans as **zero
bytes** and reports nothing, while the byte-identical file named `tfplan.zip`
yields **28 findings**. The scanner is structurally blind to precisely the
artifact most likely to carry an entire estate's credentials, and no tuning
fixes it — which is why the layer that actually closes it is a **path** rule
(`test_no_state_artifacts.py`), on files that have no legitimate reason to be
committed at all. Every generated project now inherits both the rule and the
knowledge of the blindness: the comments in `.gitignore.hbs` and in `ci.yml`
state it, so the next person to raise the archive depth knows what it does not
buy them.

**Still open, and not closable from this repository.**

The eight credentials were published. Deleting a file does not unpublish it, and
nothing in the factory can rotate them.

`output/sample-product` is worse than the risk register allowed for. Checked: the
plan file is not in the working tree and `.gitignore` names it, but commit
`af81b9b` — reachable from `develop`, and the repository has a GitHub remote —
added `infrastructure/terraform/tfplan`, 53,688 bytes. Those credentials are in
that repository's published history now. Untracking a file does not remove its
blob.

## Tier D — structural

### D1 — nothing prevents a fix from landing in one profile only

- [x] `generator-integration.yml` generates both profiles
- [x] …installs, typechecks and tests each
- [x] …fails the build on a non-zero result

**Applies to:** `koras-saas-starter/.github/workflows/generator-integration.yml`

Every Tier A item, and the dependency half of B1, would have failed such a gate
on the commit that introduced it.

**Closed 2026-08-25.** The workflow generates both profiles and then installs,
builds, lints, typechecks and tests each one, plus runs the row-level security
suite against a real Postgres and mutation-tests it by removing `force` and
requiring failure. Three optional-component variants run alongside the two
defaults, so `--with` and `--without` are covered too. A failure in one matrix
leg does not cancel the others, because knowing which profiles broke is the
point.

The paragraph above used to end "the workflow already exists; it does not yet
build what it generates", and stayed there for as long as it took someone to
read this entry beside the file it describes. Line 3 of that workflow says
"Generates both profiles and builds what comes out."

Worth recording rather than quietly deleting, because it is R-042 inside the
document whose job is tracking divergence. The reference-checking test added for
R-042 would not have caught it: the path is real and current, and the false part
is the claim *about* it. A stale "not yet" is the most expensive kind of wrong
sentence in a backlog -- it keeps an item alive, and it ranked this one as the
highest-leverage work outstanding when there was no work in it at all.

### D2 — the two templates held 110 identical files with no shared source

- [x] Drift between the duplicated files fails the build
- [x] A `profiles/_shared/` layer exists and is rendered before the profile
- [x] `local/observability/`, `local/queue/` single-sourced
- [x] `.github/workflows/` single-sourced
- [x] `eslint.config.mjs`, `turbo.json`, `tsconfig.base.json` single-sourced
- [x] `packages/` stubs — 10 single-sourced 2026-08-28
- [x] `local/scripts/` — measured, and the divergence is real

**Largely closed (2026-08-25).** `profiles/_shared/template/` holds **126**
single-sourced files. **63** paths still exist in both profiles, and
`shared-template-parity.test.ts` asserts that none of them is byte-identical, so
each remaining pair is a divergence somebody chose rather than a copy nobody
noticed.

The two unchecked rows are counts, not verdicts: `local/scripts/` keeps
`bootstrap.sh.hbs`, `health.sh.hbs`, `ports.sh.hbs` and `smoke-signin.mjs.hbs`
per profile, and `packages/` keeps 18 — mostly `auth`, whose two profiles model
an authenticated caller differently and always have. Whether those are genuine
divergences or unextracted duplicates has not been audited file by file.

**The guard has a known gap, and it hid a real defect.** Parity forbids
byte-identical copies, so two files that differ pass — including when they
differ *because one profile received a fix and the other did not*. On
2026-08-25 the product's scheduler was found missing a `# type: ignore` the
Control Plane's had carried for some time, which is precisely D1's failure mode
surviving inside D2's guard. Fixing it made the two identical, at which point
parity demanded they be single-sourced; `main.py` now lives in `_shared`.

Nothing detects the general case. A test that could would need to compare
*intent* rather than bytes, which is why the honest mitigation is extraction —
a file that exists once cannot receive a fix in one profile only.

**Counted, 2026-08-28.** These two lines said "4 files" and "18 files" and both
were guesses. Comparing content rather than paths:

Ten `packages/*/src/index.ts` were pure duplication — identical but for one word
in a comment, `// logger package` against `// logger`, plus a trailing blank
line. Nothing distinguished them; they existed twice because nobody had looked.
Single-sourced in `_shared/`, which takes real divergence from 58 paths to 48.

Everything else in `packages/` is genuine. `auth` is four files at 78–94%
similarity, which is the two profiles modelling an authenticated caller
differently and always have. `branding` and `tenant` are 9% and 11% similar —
different files that share a name.

`api-client` and `types` were recorded here as differing by "a `permissions`
dependency the product has no package for", and that was wrong twice over. The
product *does* ship `packages/permissions` — it is in `_shared/`. And looking at
what each package imports rather than what it declares gives three different
answers:

| Package | Imports `permissions` | Declares it | |
|---------|----------------------|-------------|-|
| product `types` | no | no | correct |
| control-plane `types` | yes | yes | correct |
| control-plane `api-client` | **no** | **yes** | unused; removed 2026-08-28 |

The dependency appeared in no source file in that package. It is gone, and the
two `api-client` manifests still differ — correctly, because the control-plane's
imports `@<slug>/types` and the product's imports nothing at all. That is the
divergence; the third dependency was never part of it.

Worth recording because the original note explained the difference with a reason
that was not the reason, and a wrong explanation is harder to catch than a
missing one: it reads as settled.

All ten `local/` files are genuine too, and the "4 files" was wrong in the other
direction: `.env.local.example` is 46% similar between profiles,
`secrets.manifest` 53%, `smoke-signin.mjs` 74%. They describe different stacks.

What is left is deliberate. The remaining work in this item is not extraction —
it is that nothing yet distinguishes "differs because it must" from "differs
because a fix landed once", which is D1's job and is done.

**A narrower gap, closed 2026-08-27.** "Byte-identical" was taken literally.
Five Python package markers — the `__init__.py` of `koras_api`, its `core` and
`routers`, `koras_scheduler` and `koras_worker` — existed in both profiles,
empty in `product` and holding a single newline in `control-plane`. Two bytes is
not zero bytes, so the guard passed on every run for as long as they had both
existed, and each was counted as deliberate divergence in the 63 above.

They are the easiest duplicate in the world to create: an editor adds the
trailing newline without being asked. The comparison now trims trailing
whitespace as well as normalising line endings, and the five are single-sourced
in `_shared/`, which takes real divergence from 63 paths to 58.

Mutation-checked in both directions — a twin differing only by a trailing
newline now fails the duplicate rule, and a copy left in a profile alongside its
`_shared/` original fails the single-source rule.

**Applies to:** `profiles/`

### D3 — a generated project cannot tell that it is behind

- [x] `starter_version` in `.koras/project.yaml` tracks something that changes
- [x] `--check-drift` compares it and says so

**Applies to:** `generators/create-koras-app`

Both generated repositories still record `starter_version: 0.1.0` across every
change the starter has made. The field cannot signal staleness because it never
moves.

One half of this is closed: `--check-drift` now reports any rendered file the
project does not have, across the whole tree rather than only the reviewable
set. That is what a project generated before a file joined the template needs,
since `--refresh-modules` only touches declared shared assets. It caught
`apps/admin/next.config.ts`, absent from a generated product for four days
while every run reported the project as matching.

Related: `--check-drift` prints a matching-tick headline above a list of files
that differ. When the differing files were the shared Terraform modules —
refreshable with one flag, byte-identical by contract — the headline was
actively misleading. Consider moving `infrastructure/terraform/modules/` from
the advisory set into `OWNED_PATHS` (`src/generation/drift.ts`).

### D4 — `output/sample-product` is behind the templates — moot 2026-08-30

- [x] `Makefile` — `BUILD_CONCURRENCY`, and the `doppler-bootstrap-prod` target
- [x] Everything the templates gained on 2026-08-25 — the project no longer exists

**Closed by deletion rather than by catching up.** The estate was destroyed to
close C4 and FOLLOW_UPS F1, so there is nothing left to bring forward. A
replacement demo is generated from the current templates and starts level.

Worth keeping the reason this entry existed: a generated project drifts from the
starter the moment either changes, and the only thing that closed the gap here
was the project ceasing to exist. That is not a fix for a project somebody uses
— `--check-drift` and `--refresh` are, and D3 covers them.

**Applies to:** `output/sample-product`, which is gone

Current as of `27f2949` and no longer. The templates changed substantially on
2026-08-25 and none of it has been propagated — deliberately, since that
repository is out of scope for the work that produced the changes.

What it is missing, so a later sync has a list rather than a diff:

| Change | Effect if left |
|--------|----------------|
| `force row level security` on the tenant tables | RLS policies present and never applied (R-032) |
| Issuer and algorithm pinned on both ZITADEL token paths | OIDC Core 3.1.3.7 unchecked (R-033) |
| `koras-ratelimit`, and its two tiers wired into the API | No rate limiting anywhere (R-034) |
| `assert_rls_enforced` at startup, `check-rls-connection.sh` before deploy | A bypassing connection is never reported |
| `supabase/tests/` and `local/scripts/test-rls.sh` | No way to check the policies hold |
| `ignore_missing_imports` narrowed | A missing first-party import typechecks clean (R-037) |
| The scheduler's `# type: ignore[untyped-decorator]` | `--with scheduler` fails its own typecheck (R-037) |
| `lint:py` / `typecheck:py` / `test:py` in `package.json` | Local checks cover JavaScript only (R-035) |
| `tests/security/test_api_surface.py`, and the API as a root dev dependency | No test can import the app |

Regenerating is the cheap path: none of these is a hand-edit anyone made
downstream, so nothing there is worth preserving against the template.

---

### D5 — optional components are generated by nobody and checked by nothing

- [x] Generator Integration generates at least one profile with `--with`
- [x] …and with `--without`
- [x] …and lints, typechecks and tests the result

**Applies to:** `koras-saas-starter/.github/workflows/generator-integration.yml`

Every CI run generates with default components. `--with marketing,ai_gateway,scheduler`
and every `--without` variant are paths through the generator that nothing
exercises, and the templates they select are checked only by whoever happens to
pass the flag.

Found the hard way on 2026-08-25: `--with scheduler` on the product profile
produced a project that failed its own typecheck, and had for as long as the
flag existed. The Control Plane's scheduler carried a `# type: ignore` for
APScheduler's untyped decorator and the product's did not — D1's failure mode,
in a file no default generation emits.

D1 closed the case where a fix reaches one profile and not the other *in the
default component set*. This is the same gap for everything outside it, and the
component matrix is exactly where a profile's templates diverge most.

**Closed 2026-08-25**, with two matrix entries:
`--with marketing,ai_gateway,scheduler` and `--without admin,worker`.

It found a second defect immediately. The AI gateway called litellm's
`initialize` without awaiting it, so the coroutine was created, discarded, and
never ran — the proxy read no configuration file and served with default
settings while appearing configured. Like the scheduler, it sat in a template no
default generation emits.

Two defects in the first run of a check nobody had written is the argument for
the check. Both were in optional components, and neither could have been found
by reading the templates, because both are only wrong once something runs them.

### D6 — the Control Plane repository is behind the same changes

- [ ] The 2026-08-25 template changes reach `koras-control-plane`

**Applies to:** `koras-control-plane`

**Its Doppler configs are missing `DATABASE_ADMIN_URL`** — checked against
`dev` on 2026-08-26, which holds 18 of the 19 settings the manifest requires.
That is expected: the secret is new, and creating it is part of the
`create-app-role.sh` step, not something to add by hand ahead of it.

`dev` also holds **`ZITADEL_SERVICE_TOKEN`**, which this audit first recorded as
an orphan because no template declared it. That was the wrong conclusion, and it
is worth keeping the correction visible: the secret is real and load-bearing —
`koras-control-plane` carries a runbook for it, its local contract names it, and
its test suite stubs it — and what was actually missing was the *factory's*
declaration of it. The direction of a divergence is not obvious from one side of
it, and "the generator does not mention this" reads identically whether the
estate has something spurious or the generator has a gap. Deleting on that
reading would have removed a working credential.

Now declared `supplied` in the control-plane profile. Still to propagate the
other way: the code that reads it lives only in `koras-control-plane`, so a
freshly generated Control Plane declares the credential and has nothing that
uses it yet.

The same list as D4, filtered to what the control-plane profile ships. It is a
real repository under independent development rather than generated output, so
regeneration is not the path — each change has to be applied deliberately, and
two of them are decisions rather than patches:

- **`force row level security` must NOT be applied there.** Its tables carry RLS
  with no policies as a deny-by-default backstop, and forcing it denies the
  owner too. This is written down because the obvious reading of R-032 is to
  apply the fix everywhere, and doing so locks the Control Plane out of its own
  database. It happened here on 2026-08-25 and was caught before release.
- **`require_rls_enforcement` is `False` for this profile**, for the same
  reason: its service role bypasses RLS by design.

Everything else — the issuer and algorithm pinning, the narrowed
`ignore_missing_imports`, the two-language local checks, the API surface tests —
applies unchanged.

---

## Tier E — record-keeping

### E1 — the risk register has decayed

- [x] Summary table has a row for R-022 through R-027
- [x] R-024 is written (commit `98fc7e0` names it; the register does not)
- [x] R-025 is written (commit `4f6a36e` names it; the register does not)
- [x] R-022 uses `##`, matching every other entry
- [x] The two registers no longer collide

**Applies to:** `RISK_REGISTER.md`

Closed. The table now holds a row for every entry, and the entries added since
(R-030 through R-037) followed the same format.

Two conventions remain side by side, deliberately: R-001 through R-014 are
`###` with a `| Field | Value |` table and describe risks identified in
planning; R-015 onward are `##` with prose and describe defects found in
operation. Reading either tells you which kind it is.

`koras-control-plane/RISK_REGISTER.md` numbers to R-77 in the same
`R-NN` namespace this one numbers to R-027. "R-22" identifies two different
defects depending on which repository is being read. Prefixing them
(`KSS-22` / `KCP-77`) or merging them would fix that.

### E2 — three documentation conventions

- [x] One convention, chosen deliberately

**Closed.** `docs/`, matching what `koras-control-plane` already does. The
starter's twelve planning documents moved out of the root; only `README.md` and
`CLAUDE.md` remain there. Every reference was rewritten — CLAUDE.md's table, the
cross-links between the documents, and the four source files that cite one in a
comment — and checked afterwards for any left pointing at the old location.

Both templates still ship `docs/.gitkeep` and nothing else, which is the right
starting point for a project that has no documents yet.

**Applies to:** all three repositories

The starter keeps 13 flat `SCREAMING_SNAKE.md` files at the root. The
control-plane moved the equivalent set into `docs/`. Both templates ship
`docs/.gitkeep` and nothing else, so a generated project starts with neither.
### E3 — nothing here pointed at the contract this repository implements

- [x] `docs/PROFILE_ARCHITECTURE.md` names it
- [x] `docs/PRODUCT_GENERATOR_PLAN.md` names it
- [x] `src/registration/contract.ts` names it in its header
- [x] The generated `control-plane-client` names it in its header

**Closed.** Promoted from
`koras-control-plane/docs/starter-promotion/SYNC_BACKLOG_ENTRIES.md`.

**Applies to:** the starter's documentation and two source headers

`koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md` is authoritative for
both directions of product registration. This repository implements the client
half of it in two places and named it in none of them.

That is not a tidiness problem. A duplicate of that contract was written in the
Control Plane repository, contradicting the real one in four places, because
nothing connected an implementation to its specification. Four one-line pointers
are the cheapest defence available against the second occurrence.

The same pass found `PROFILE_ARCHITECTURE.md` §6 printing an invented payload —
flat, with `github_repo`, `supabase_projects` and `zitadel_project` in it. No
such request has ever been sent or could be: the Control Plane's request model
sets `extra="forbid"`, so every one of those names is a 422. It was an
illustration nobody had checked against the schema, which is R-042 exactly. It
now shows the real shape, and says what it used to say.
