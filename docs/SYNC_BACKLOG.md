# KORAS SaaS Starter — Sync Backlog

## What this document is

The factory produces two profiles and the profiles produce repositories. Work
lands in four places and does not always land in all of them:

```
koras-saas-starter                    the factory, and its own CI
  profiles/product/template           →  output/sample-product
  profiles/control-plane/template     →  koras-control-plane
```

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

**Closed since:** A1, A2, A3, B1, B2, B3, B4, B5, C1, C2, C3, D1, D3, D4, E1, E2.
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

## Tier D — structural

### D1 — nothing prevents a fix from landing in one profile only

- [x] `generator-integration.yml` generates both profiles
- [x] …installs, typechecks and tests each
- [x] …fails the build on a non-zero result

**Applies to:** `koras-saas-starter/.github/workflows/generator-integration.yml`

Every Tier A item, and the dependency half of B1, would have failed such a gate
on the commit that introduced it. The workflow already exists; it does not yet
build what it generates.

This is the highest-leverage item in the document. Without it, this document
needs new entries after every burst of work.

### D2 — the two templates hold 110 identical files with no shared source

- [x] Drift between the duplicated files fails the build
- [ ] `local/scripts/` single-sourced
- [ ] `local/observability/`, `local/queue/` single-sourced
- [ ] `.github/workflows/` single-sourced
- [ ] `packages/` stubs single-sourced
- [ ] `eslint.config.mjs`, `turbo.json`, `tsconfig.base.json` single-sourced

**Guarded, not yet fixed.** The count was wrong: it is **110** byte-identical
files, not ~40. `tests/shared-template-parity.test.ts` lists every one and fails
when they stop matching, so a fix reaching one profile and not the other is now
a failing build rather than something a review of either repository cannot see.
Verified non-vacuous by appending a line to one copy of `migrate.sh`.

**Why the extraction did not follow.** `shared_assets` copies verbatim — that is
what makes `--refresh-modules` safe — and most of the 110 are `.hbs` files
needing interpolation. A `profiles/_shared/` tree therefore needs a rendering
path the engine does not have, plus precedence rules for profile overrides, and
a precedence bug is silent: the wrong file wins and nothing says so. Worth doing
deliberately rather than alongside eleven other items.

**Applies to:** `profiles/`

The `shared_assets` mechanism in both manifests already solves this and is used
for exactly one entry: `infrastructure/terraform/modules`. Extending it to a
`profiles/_shared/` tree would make "promote to one profile" impossible by
construction rather than merely discouraged.

An earlier survey found these diverged: `settings.py` (`doppler_token` in product
only), root `package.json.hbs` (`@types/node` in product only), and the
control-plane's hardcoded description where the product interpolates the project
name.

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

### D4 — `output/sample-product` has one remaining drift

- [x] `Makefile` — `BUILD_CONCURRENCY`, and the `doppler-bootstrap-prod` target

**Applies to:** `output/sample-product`

Everything else is current as of `27f2949`.

---

## Tier E — record-keeping

### E1 — the risk register has decayed

- [x] Summary table has a row for R-022 through R-027
- [x] R-024 is written (commit `98fc7e0` names it; the register does not)
- [x] R-025 is written (commit `4f6a36e` names it; the register does not)
- [x] R-022 uses `##`, matching every other entry
- [x] The two registers no longer collide

**Applies to:** `RISK_REGISTER.md`

The table holds 21 rows against 25 body sections. R-024 and R-025 appear
nowhere — no row, no body — though both have commits naming them.

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
