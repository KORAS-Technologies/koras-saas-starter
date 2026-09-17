# Settings & Preferences Framework — pre-implementation audit

Read across all three repositories on 2026-09-17, before any implementation
code was written. Every claim below is a path, not a recollection.

---

## Current State

### There is no settings framework anywhere

A search across `koras-saas-starter`, `koras-control-plane` and
`output/koras-e2e-shop` for `setting_definition`, `global_settings`,
`GlobalSettings`, `user_preferences`, `organization_settings` and "settings
registry" returns nothing outside `.venv` and `node_modules`. As of 2026-09-17:

- No settings-definition registry, in either language, in any repository.
- No generic key/value settings table at any scope.
- No platform-default concept. Nothing is copied into a tenant at provisioning.
- No settings API router in the product or in the Control Plane.
- No Settings section in the Control Plane's navigation.
- No feature-flag implementation. `profiles/product/template/packages/feature-flags/src/index.ts`
  is two lines: a comment and `export {}`. The Control Plane has no hit for
  "feature flag" at all.

### What passes for settings today, in the product

Settings exist as named columns on one table plus one single-column sibling.

`public.tenant_settings` — `profiles/product/template/supabase/migrations/00001_initial.sql:35-42`:

| Column | Added by | Meaning |
|--------|----------|---------|
| `branding` jsonb | `00001` | The customer's own colours and logo |
| `domains` text[] | `00001` | Custom domains |
| `features` jsonb | `00001` | Optional features this customer switched on |
| `locale` text | `00017_locale_preferences.sql:50` | The organisation's default language |
| `retention_overrides` jsonb | `00023_retention_overrides.sql:22` | Per-class audit retention, validated by a SQL function |

`public.member_preferences` — `00017_locale_preferences.sql:59-72`. Primary key
`(tenant_id, user_id)`, one value column (`locale`), per-verb RLS policies keyed
on **both** `current_tenant_id()` and `current_user_id()`
(`:84`, `:92`, `:100`). It is the repository's only table a person may write
about themselves and a colleague may not read.

Two properties of this table decide much of the design below. The migration's
own comment (`:14-24`) explains why it is not a column on `tenant_members`: that
table is written by provisioning for the owner and by nothing else, so a
preference stored on it would exist for one person per tenant, and it carries
`role` — a policy letting a member update their own row would be a policy
letting them update their own role. **`member_preferences` is already the
correct shape for user-scoped settings.** It is under-used, not wrong.

`tenant_settings` has **no row at all** until a customer first writes something
(`routers/tenant.py:124-137`). Every read is a left join, and an absent row
means "the product's own defaults", which is a finished answer rather than a
missing one.

### What passes for settings today, in the Control Plane

Three separate shapes, none of them generic:

1. **Entitlements** — `supabase/migrations/00006_commercial.sql`. A catalogue
   (`public.entitlements`, `:37-62`) with `default_enabled` / `default_limit` /
   `default_period`, per-plan grants (`plan_entitlements`, `:66-80`) and
   per-customer overrides (`subscription_entitlements`, `:102-117`). This is a
   three-tier default-and-override model that already works.
2. **Policy tables** — `00009_policy.sql`. `storage_policies` (`:5-24`) and
   `ai_policies` (`:27-46`), each one row per `(organization_id, product_id)`
   with a `config jsonb` column and a **check constraint refusing
   secret-shaped top-level keys** (`storage_policies_config_holds_no_secrets`,
   `:19-21`).
3. **Code-declared catalogues** — `koras_platform/ai.py` (`MODEL_ALIASES` `:29`,
   `AI_PROVIDERS` `:41`, `ROUTING_TEMPLATES` `:153`) and
   `koras_platform/plans.py` (`PLAN_CATALOGUE` `:28`).

`packages/config/src/index.ts` in the Control Plane is a two-line stub, as are
`packages/audit`, `packages/notifications`, `packages/tenant` and
`packages/branding`.

### Grid and table rendering

**There is no DataTable in the product at all.** The only reusable table is
`profiles/product/template/packages/ui/src/reporting/report-table.tsx:14`, which
is reporting-specific and renders whatever `table.rows` holds with no
pagination; truncation is signalled by the API's `Table.truncated` flag.

Every other dashboard surface hand-rolls its markup:

| Surface | File | Paginates? |
|---------|------|-----------|
| Audit | `dashboard/audit/AuditPanel.tsx.hbs:230` | Yes — cursor by timestamp, "more" button at `:290-296` |
| Files | `dashboard/files/FilesPanel.tsx.hbs:309` | No — the API returns every ready row |
| Restore | `dashboard/restore/RestorePanel.tsx.hbs:183` | No |
| Governance | `dashboard/governance/GovernancePanel.tsx.hbs` | No table; cards and lists |

There is no `Pagination`, no `Toggle`, no `Switch` and no `Checkbox` primitive
in `packages/ui`.

The Control Plane does have one: `apps/admin/src/components/ui/DataTable.tsx`,
135 lines, "the one table" (`:5-17`), with a `Column<T>` interface carrying
`header`, `cell`, `align`, `width` and `hideBelow`. **It has no pagination
either** — no page prop, no page-size constant, no pager control. Its
`TableToolbar.tsx` keeps search and filter state in the URL and takes `total`
and `shown` counts, but renders no pager. It lives in `apps/admin`, not in
`packages/ui`, and the portal has no equivalent.

### Audit infrastructure

The product's is the richer of the two and is what this feature will use.

`public.audit_events` — `00013_audit_events.sql:21-31`, plus `classification`
from `00019_audit_classification.sql:19-24`. Columns: `id`, `tenant_id`,
`actor_id`, `action`, `target_type`, `target_id`, `outcome`, `details`,
`created_at`, `classification`. Select and insert for the own tenant; **no
update policy and no tenant delete policy**.

The vocabulary is a registry, not a convention:
`koras_audit.AuditAction(key, classification, summary)` with a dotted-lowercase
key regex (`__init__.py:41`), `AuditActionRegistry.add` refusing duplicates
(`:101`), and `classification_of` **raising on an unregistered action rather
than defaulting** (`:123`). `_FORBIDDEN_DETAIL` (`:142`) refuses a detail key
that looks like a secret.

Emission from a route is `await record(session, tenant_id=, actor_id=, action=,
target_type=, target_id=, outcome=, details=)` — `core/audit.py:204-233` — on
the router's own session, so it commits with the change.

The Control Plane's `audit_events` is a **different table with a different
schema in a different database** (`00010_operations.sql:124-149`), recording
what platform staff did to the platform. It has no action registry — 28 literal
strings at 28 call sites — and `before_state`/`after_state` are deliberately
never rendered in its UI (`apps/admin/src/app/audit/page.tsx:25-30`), so it has
no change-history view.

### Provisioning

The product side is one function. `POST /tenants` on
`routers/platform.py:95-145` (machine identity only, `/internal/platform/v1`)
calls `core/tenant_store.py::create` (`:82-183`), which:

1. Inserts the tenant `on conflict (tenant_key) do nothing` (`:107-128`).
2. Adopts an existing row on a retry (`:136-160`).
3. Upserts the owner into `tenant_members` (`:164-180`).
4. **Commits once, at `:182`.**

The Control Plane side is the 16-step `SEQUENCE` in
`services/worker/koras_worker/provisioning/steps.py:543-589`, run by
`ProvisioningEngine`, with post-run persistence in `tasks/__init__.py:600-740`.

Two steps in that sequence are direct precedents, and **they point in opposite
directions**:

- `entitlements` (step 10, `steps.py:365-374`) is a deliberate no-op returning
  a result saying it materialised nothing and resolves on read. Entitlements are
  never snapshotted.
- `apply_ai_routing_template` (`tasks/__init__.py:725-738`, repository
  `:1217-1262`) **does** snapshot, with `on conflict do nothing` so that a later
  staff edit survives a retry.

### Permissions

The product has a real permission catalogue.
`profiles/product/template/packages/permissions/src/index.ts:73-108` declares 16
`PRODUCT_PERMISSIONS`, dotted `<area>.<verb>`, **including `settings.read` and
`settings.manage` already**. `ROLE_PERMISSIONS` (`:134-145`) is a total record,
one line per role. It is mirrored in
`python-packages/koras-auth/src/koras_auth/permissions.py:22-48` and the two are
compared as text by `generators/create-koras-app/tests/product-ai.test.ts:101-102`.

Enforcement is an explicit guard function called as the first statement of a
handler — there is **no** `require_permission` dependency and no decorator
(`routers/audit.py:91-97`, called at `:192` and `:270`).

The Control Plane has no permission-string catalogue. Authorisation is by role
name through `AREA_ROLES` (`packages/permissions/src/index.ts:100-128`), and the
only permission strings in the repository are the four platform reporting
constants inside `reporting/platform.py:65-68`.

### Caching

There is effectively none, in either repository.

- Redis is the ARQ queue transport, and in the product it is **only** the rate
  limiter's counter (`main.py.hbs:50`).
- The product has one in-process TTL cache — `core/platform.py:55`, holding the
  Control Plane's portal answers, invalidated per organisation at `:158-159`.
- The Control Plane has one — `billing/prices.py`, with a ten-minute TTL, which
  deliberately does not cache a failed lookup (`:61`).
- `ReportDefinition.cache_seconds` is declared and validated in both
  repositories and **read by nothing**. It is reported to the client and acted
  on nowhere.
- The frontend convention is React `cache()` for per-render de-duplication
  (`lib/tenant-settings.ts.hbs:29`, `lib/entitlements.ts.hbs:43`,
  `lib/locale.ts.hbs:39`), every dashboard page forced dynamic, and
  `revalidatePath('/dashboard', 'layout')` as the write-invalidation
  (`dashboard/settings/actions.ts.hbs:55`). The API client hard-codes
  no-store on every request (`api-client/src/index.ts:136`).

---

## Existing Reusable Components

Ten things this feature should build on rather than beside.

| # | What | Where | Why it fits |
|---|------|-------|-------------|
| 1 | `koras_reporting` registry pattern | `profiles/_shared/template/python-packages/koras-reporting/` | Frozen dataclass definitions with a post-init that enforces key shape; a registry whose `add` raises on duplicate; `build_catalogue()` called once at import so a bad catalogue is a traceback, not a 500. Exactly the shape a setting definition registry needs. |
| 2 | `resolve_filters` | `koras_reporting/filters.py:102` | Typed coercion driven by a definition, **refusing unknown keys rather than ignoring them** (`:111-113`). A settings write needs the same behaviour and the same `_coerce` (`:140`). |
| 3 | `visibility_for` | `koras_reporting/authorization.py:26` | Pure permission/entitlement/capability visibility with a three-value answer. Settings need the same idea with a different vocabulary. |
| 4 | `member_preferences` | `00017_locale_preferences.sql:59` | Already the per-tenant, per-person table with per-verb RLS on both keys. Extend it; do not build a second one. |
| 5 | `koras_audit` action registry | `koras-audit/__init__.py:68-140` | Register six new actions and every settings mutation is classified, retained and swept correctly with no new code. |
| 6 | `PRODUCT_PERMISSIONS` | `packages/permissions/src/index.ts:73` | `settings.read` and `settings.manage` already exist and are already granted per role. |
| 7 | `api_error` | `services/api/koras_api/core/errors.py:83` | The code-and-message contract the web tier maps to an i18n key. |
| 8 | `tenant_store.create` | `core/tenant_store.py:82-183` | One transaction, one commit at `:182`. The settings snapshot belongs inside it. |
| 9 | Control Plane `DataTable` and `TableToolbar` | `apps/admin/src/components/ui/` | The column model and the URL-state toolbar are right; only the pager is missing. |
| 10 | `SidebarFrame`, `AREA_ROLES`, `NAVIGATION_GROUPS` | Control Plane `packages/ui/src/sidebar-frame.tsx`, `packages/permissions`, `apps/admin/src/lib/navigation.ts` | Adding a Settings section is five mechanical steps, documented at `docs/CONSOLE_UI.md:466-477`. |

---

## Gaps

What has to be built, in dependency order.

1. **A setting definition type and registry.** Nothing like it exists.
2. **Three value tables** — global, organisation and member — with RLS, forced
   RLS, per-verb policies and a numbered isolation suite each.
3. **A resolver** that answers one key and the whole set, with source and
   override metadata.
4. **A snapshot step** at provisioning, inside the tenant-create transaction.
5. **A settings router** in the product and a platform surface beside it.
6. **A frontend provider** — `SettingsProvider`, `useSettings`, `useSetting` —
   seeded once per request from the dashboard layout.
7. **`KorasDataTable`**, which does not exist in the product in any form, with
   pagination that defaults to the resolved page size.
8. **Pagination for the Control Plane's `DataTable`**, which it has never had.
9. **A Control Plane Settings area** — three pages, one new area key, one new
   migration, one new router.
10. **A contract extension** so the Control Plane can read a product's published
    catalogue and write the platform defaults.
11. **Six audit actions**, registered.
12. **i18n entries** for every label, description and error code, in `en`, `de`
    and `es` — the catalogues stop compiling without them.
13. **A shop surface that lists enough rows to page**, because none exists.

---

## Conflicts

Six places where the brief meets a decision this estate has already taken. Each
needs an answer before Phase 2, and four of them I am recommending against the
brief's literal wording.

### C1 — Setting definitions in a table vs in code

The brief (sections 4 and 5) asks for a definitions table with active,
created-at and updated-at columns, implying rows an administrator edits.

Every comparable catalogue in this estate is declared in code and registered at
import, and the reason is written down. `koras_platform/ai.py:1-21` says a table
edited from a form would be a list of model names nobody tests, and that in code
a name is checked and changed in one commit. `koras_reporting/registry.py:1-6`
makes a duplicate key an error at import rather than at request time.

A definitions table also cannot work for the Control Plane without a second
mechanism: the platform manages several products, each with its own settings,
and it can only know a product's catalogue if the product publishes it.

**Recommendation: the registry is code; the catalogue is published over the
API.** The Control Plane's Setting Definitions page becomes a read-only
inspector of what a product declares, which is what section 12 actually asks for
— *available only to authorized platform administrators*, never *editable*. The
active flag becomes a deprecated status on the definition, mirroring
`ReportDefinition.status`.

### C2 — Snapshot versus resolve-on-read

The brief (sections 2, 10 and 11) requires a copy at provisioning that later
global changes never touch. The Control Plane's entitlements provisioning step
(`steps.py:365-374`) exists specifically to record that entitlements are **not**
materialised — they resolve on read, every time.

These are different questions with legitimately different answers. An
entitlement is what a customer *bought*; changing the plan must reach them
immediately, so resolve-on-read is right. A setting is a default someone was
given; changing the platform default must **not** silently change what a
customer already configured. `apply_ai_routing_template` is the existing
snapshot precedent and it uses a conflict-do-nothing insert so a later staff
edit survives a retry.

**Recommendation: follow the brief.** Snapshot, and say in the ADR why this
differs from entitlements, because the next reader will ask.

### C3 — Synchronising to the Control Plane is not a code sync

The brief's sections 1, 12 and 26 assume the Control Plane receives
functionality from the starter. `docs/features/PROFILE_SYNC_MATRIX.md:36-45`
records that it does not: it was generated once and built out independently, its
packages are local workspace members resolving to nothing upstream, and
**exactly one artifact is genuinely shared** —
`contracts/product-platform.v1.json`, kept byte-identical by hand.

**Recommendation: the Control Plane work is a parallel implementation against an
extended contract, not a file copy.** Its `DataTable` gains pagination in its own
repository; it does not receive `KorasDataTable`.

### C4 — A platform write to product settings needs an ADR that does not exist

`contracts/product-platform.v1.json` states a no-direct-writes rule. The sync
matrix (`:60-90`) records the 2026-09-16 decision that the platform *may* act
through contract routes, under one mechanical test — **the platform may only act
in the direction that keeps data** — and says plainly that this needs its own
ADR before the first write route is built.

Pushing platform defaults into a product is a configuration write. It neither
destroys nor discloses, so it passes the test, but it is the first route to be
admitted by it.

**Recommendation: write ADR 0007 covering both this framework and that first
write route, and keep the route to global defaults only — it must never be able
to write an organisation's values.**

### C5 — Section 16's five permission pairs collapse onto two that exist

The brief asks for nine permission strings across global, definition,
organisation, user and audit scopes.

In the product, `settings.read` and `settings.manage` already exist and are
already granted per role. A person setting their own preference needs no
permission at all — it is the same act as choosing a language today, which
requires none. Global settings are not in the product's vocabulary; they are the
Control Plane's, where authorisation is by role through `AREA_ROLES` and there
is no permission-string catalogue to add to.

Adding seven strings that resolve to two existing ones and one role key would
make the catalogue parity test guard a fiction.

**Recommendation: `settings.read` and `settings.manage` in the product, no
permission for one's own preferences, and one new `settings` key in the Control
Plane's `AREA_ROLES`.**

### C6 — The language setting already has storage, in two places

The brief's section 6 catalogue lists a general language setting. That value
exists today as `tenant_settings.locale` and `member_preferences.locale`, is
validated in three tiers, is read by the shell on every request through
`routers/tenant.py:139-155`, and has its own RLS isolation suite
(`160_member_preferences_isolation.sql`) and e2e spec (`e2e/language.spec.ts`).

Registering it without migrating it creates two sources of truth for one value —
the failure mode `CLAUDE.md` records for `audit_events` sitting inside the
reporting gate.

**Recommendation: migrate it.** Backfill both columns into the new tables in the
same migration that creates them, drop the two columns, and repoint
`routers/tenant.py` at the resolver. This is the single largest piece of
migration risk in the feature and it is called out again below.

---

## Recommended Architecture

Stated in full in `architecture.md`. In brief:

```
SettingDefinition (frozen dataclass, Python)
        registered at import into a SettingsRegistry
                    |
                    +-- published over the API to every other surface
                    |
values              v
  global_settings        (no tenant; the platform's defaults for this product)
  organization_settings  (tenant, key)   <- copied from global at provisioning
  member_settings        (tenant, person, key)

resolution:  member -> organization -> global -> the definition's own default
```

- Definitions in Python only. The frontend reads them from the API; a narrow TS
  union of keys is kept level by a structural test, the way the permission
  catalogues are.
- Values are one row per key at every scope, so a reset is a delete, an override
  is the existence of a row, and an audit event names a key.
- The snapshot is written inside the single transaction in
  `core/tenant_store.py:180-182`, carrying the global version it was copied
  from, when, and by whom.
- The framework is **foundation, not a capability**, by the rule at
  `profiles/product/manifest.yaml:170-186`: the shell reads settings on every
  request, so foundation code reaches the tables.
- Caching is React `cache()` plus `revalidatePath`, the established convention.
  No Redis, no new infrastructure — section 18's instruction to review first
  resolves to "there is nothing to reuse and nothing is needed".

---

## Migration Impact

### Product — new migrations 00029 to 00031

| Migration | Contents | Risk |
|-----------|----------|------|
| `00029_settings.sql` | The three value tables; RLS enabled **and forced**; per-verb policies; provisioning policies for the snapshot | Low. New tables, nothing reads them yet |
| `00030_settings_snapshot.sql` | The snapshot provenance columns on `tenants` | Low |
| `00031_settings_locale_migration.sql` | Backfill the two locale columns into the new tables, then drop them | **The highest-risk change in the feature.** A live product's language choices pass through it |

**The order changed on building it, 2026-09-17.** The locale migration was
third rather than second, and it lands with the settings API in Phase 4 rather
than with the tables in Phase 3. Dropping the columns in the phase that created
the tables would leave `routers/tenant.py` selecting a column that no longer
exists for as long as it took to build the router that replaces it. The tables
arrive first and nothing reads them; the columns go when there is somewhere
else to read from.

Three isolation suites must ship with them — numbered 260, 270 and 280 — or
`010_rls_structure.sql` fails on a table with no policy.

`160_member_preferences_isolation.sql` and `e2e/language.spec.ts` both change
with the locale migration.

### Control Plane — new migration 00045

One migration holding the platform's per-product defaults and the monotonic
version counter. `tests/rls/test_rls_coverage.py:14-42` carries an explicit
expected-tables set of 27 names; both new tables must be added to it or that
test fails.

### Contract

Three routes added, the version unchanged (they are additive):

- The product publishes its catalogue.
- The product reports what it holds as platform defaults.
- The platform replaces them. **Global scope only.**

The file is kept byte-identical by hand in both repositories and checked from
the starter by `shared-template-parity.test.ts`. Both copies change in the same
commit or that test fails.

### Things that break if forgotten

- A new API error code without a sentence in `en`, `de` and `es` fails
  `product-i18n.test.ts:381`.
- A new table not listed in an isolation suite fails `010_rls_structure.sql`.
- A settings file placed under a capability in `template_map` fails the leak
  detector in `generation.test.ts:273-390`. It must not be gated.
- Any path or identifier named in a top-level `docs/*.md` must exist in the
  code (`identifiers.test.ts:201-220`); these feature documents are outside that
  scan, but `hedged-claims.test.ts` walks `docs/` recursively and every hedge
  here carries a date.

---

## Implementation Phases

Summarised here; the detail, the workstreams and the file-level plan are in
`implementation-plan.md`.

| Phase | Deliverable | Repositories |
|-------|-------------|--------------|
| 1 | These documents and ADR 0007 | starter |
| 2 | The settings package: definitions, registry, resolver, validation | starter |
| 3 | Migrations, RLS suites, the snapshot inside tenant creation | starter |
| 4 | Settings router, audit actions, permissions wiring | starter |
| 5 | `SettingsProvider`, `useSettings`, `useSetting`, loaded once in the layout | starter |
| 6 | `KorasDataTable` with settings-driven paging | starter |
| 7 | Organisation Settings UI and My Preferences UI | starter |
| 8 | Contract extension; Control Plane migration, router, three pages, pagination | starter and control-plane |
| 9 | Sync to the shop, plus a shop list page with enough rows to page | shop |
| 10 | Full automated run, RLS suite, generator integration, e2e | all three |
| 11 | Documentation, manual test guide, final boundary audit | all three |

---

## Repositories Impacted

| Repository | Path | Change |
|------------|------|--------|
| `koras-saas-starter` | `C:\repos\Projects\koras-saas-starter` | Source of everything. New shared Python package, three migrations, one router, one UI package area, two dashboard pages, contract, docs, tests |
| `koras-control-plane` | `C:\repos\Projects\koras-control-plane` | Parallel implementation: one migration, one router, one area key, three pages, table pagination, the contract copy |
| `output/koras-e2e-shop` | `C:\repos\Projects\output\koras-e2e-shop` | Hand-carried sync of the generated output, plus one new list page as the validating surface |

**Explicitly not touched:** Docoris, Dianova, LegalApp, `korastech-enterprise`,
`acme-platform`, `output/koras-phase10-lab`, or anything else under
`C:\repos\Projects\`. All three target repositories were clean and on `develop`
when this audit was taken on 2026-09-17.
