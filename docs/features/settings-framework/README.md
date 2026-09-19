# Settings & Preferences Framework

A reusable three-level settings framework — platform default, organisation,
person — for every KORAS product, with the values resolved once per request and
consumed by shared components rather than fetched page by page.

Phase 1 opened 2026-09-17. **It is built as of 2026-09-19**, in all three
repositories, and no manual pass has been run against any of it.

## The documents

Four of these are the design, written before the work and left as they were
written. Two are what was actually built. They disagree in places, and where
they do the as-built ones are right — a design document edited after the fact
stops being a record of what was decided and becomes a second, worse
description of the code.

| Document | What it answers | Written |
|----------|-----------------|---------|
| `audit.md` | What existed, what was reusable, what was missing, and where the brief conflicted with decisions already taken | Before |
| `architecture.md` | The recommended design: scopes, storage, resolution, registry, API, frontend, grid, RBAC, audit, caching | Before |
| `implementation-plan.md` | Phases, workstreams, the repository sync matrix, and the test plan | Before |
| `sync-matrix.md` | What each of the three repositories owes this feature, and what it got | After |
| `manual-test-plan.md` | The fifteen cases no automated test in this estate reaches | After |

The as-built description is `docs/SETTINGS_ARCHITECTURE.md`; how to add a
setting is `docs/SETTINGS_DEVELOPER_GUIDE.md`. The decision record is
`docs/adr/0007-koras-settings-framework.md`, written at the end of Phase 1 and
amended twice since — once on the table names, once on when the locale moved.

### Where this README was wrong

It named the value tables `organization_settings` and `member_settings`. They
are `global_settings`, `tenant_setting_values` and `member_setting_values`; the
rename was the ADR's first amendment, and this file was not updated with it for
two days. That is R-042 in miniature, on the file somebody reads first to find
out what this feature is.

## The one-paragraph summary

Setting *definitions* are declared in Python code and registered at import, the
way reports and audit actions already are; the API publishes them and every
other surface reads them from there, so there is one catalogue rather than a
mirrored pair. Setting *values* live in three narrow key/value tables in the
product's own database — `global_settings`, `tenant_setting_values`,
`member_setting_values` — resolved user → organisation → global → the
definition's own default. A new organisation receives a **copy** of the applicable global values
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
