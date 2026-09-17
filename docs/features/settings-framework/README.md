# Settings & Preferences Framework

A reusable three-level settings framework — platform default, organisation,
person — for every KORAS product, with the values resolved once per request and
consumed by shared components rather than fetched page by page.

Phase 1 opened 2026-09-17. Nothing in this feature is built yet as of
2026-09-17; these documents are the design gate the work is not allowed to
start without.

## The documents

| Document | What it answers |
|----------|-----------------|
| `audit.md` | What exists today, what is reusable, what is missing, and where the brief conflicts with decisions already taken |
| `architecture.md` | The recommended design: scopes, storage, resolution, registry, API, frontend, grid, RBAC, audit, caching |
| `implementation-plan.md` | Phases, workstreams, the repository sync matrix, and the test plan |

The decision record is `docs/adr/0007-koras-settings-framework.md`, written at
the end of Phase 1.

## The one-paragraph summary

Setting *definitions* are declared in Python code and registered at import, the
way reports and audit actions already are; the API publishes them and every
other surface reads them from there, so there is one catalogue rather than a
mirrored pair. Setting *values* live in three narrow key/value tables in the
product's own database — `global_settings`, `organization_settings`,
`member_settings` — resolved user → organisation → global → the definition's own
default. A new organisation receives a **copy** of the applicable global values
at provisioning, inside the transaction that creates the tenant, and later
changes to the platform defaults never reach it. The Control Plane manages the
platform defaults for each product it knows about, reading that product's
published catalogue through the platform contract and writing values back
through one new contract route.

## What this deliberately is not

- Not a second feature-flag system. `tenant_settings.features` stays where it
  is and keeps its meaning: what a customer switched on out of what their
  repository was built with. A setting is a value; a feature is a gate.
- Not a product-level inheritance tier. Three levels, and the brief is explicit
  that there is no fourth.
- Not a home for secrets. The provider policy tables in the Control Plane
  already refuse secret-shaped keys with a check constraint; this framework
  copies that refusal rather than inventing a "sensitive value" store.
- Not a replacement for `packages/branding`. A product's name, palette and
  navigation are edits to that package and stay compile-time facts.
