# Settings Architecture

What the settings framework is, as built. The design that preceded it is
`docs/features/settings-framework/architecture.md`; the decisions and the two
amendments are `docs/adr/0007-koras-settings-framework.md`. This document
describes what a generated product actually contains.

Three levels, and only three: the platform's default, the organisation's value,
the person's preference. A product does not get a tier of its own, and the
reason is in the ADR rather than here.

## It is foundation, not a capability

There is no `settings` entry in `profiles/product/manifest.yaml`, no gated
migration and no Handlebars conditional around any of it. Every generated
product has the tables, the catalogue, the routes and both pages, whatever it
was generated with.

That follows the rule the governance work wrote down after breaking it: a table
is gated only when no foundation code and no foundation migration reaches it.
The settings tables fail that test in the first instance — `seed_tenant` runs
inside tenant creation, which every product does — so gating them would produce
a product whose tenants are created without settings and whose pages read an
absent table.

## The three tables

`profiles/product/template/supabase/migrations/00029_settings.sql` creates them.

| Table | One row per | Written by |
|-------|-------------|------------|
| `global_settings` | key | The platform, through the Control Plane |
| `tenant_setting_values` | tenant and key | An organisation administrator |
| `member_setting_values` | member and key | The person themselves |

Narrow key/value, not a column per setting. A column per setting means a
migration per setting, which means a setting is a deployment — and the brief
asks for a catalogue a product can add to, which a deployment-shaped setting is
not.

All three enable **and force** row-level security. The two tenant-scoped tables
carry per-verb policies keyed to `current_tenant_id()`; `member_setting_values`
is keyed to `current_user_id()` as well, because a colleague in the same
organisation is not entitled to read what theme somebody chose.

`global_settings` is the odd one. It is not tenant-scoped — the platform's
defaults are the same row for everybody — so its select policy asks a different
question:

```sql
create policy "global_settings_select_declared"
  on public.global_settings for select
  using (public.current_tenant_id() is not null or public.is_provisioning());
```

It was `using (true)` first, and `rls-policy-ordering.test.ts` refused it. The
guard was not weakened to get past the test: a caller with no declared tenant
and no provisioning context has not established who they are, and a table that
answers such a caller is a table that answers an unauthenticated pool
connection.

### No secret may be stored in one

`setting_holds_no_secret(p_key, p_value)` is an immutable function applied as a
check constraint on all three tables. It refuses a key matching

```
(secret|token|password|passwd|credential|(private|access|api|secret)_?key)
```

The `_?` matters and was not there first: `integrations.accessKey` passed the
original pattern, and the isolation suite
`profiles/product/template/supabase/tests/280_member_setting_values_isolation.sql`
is what caught it. Doppler is the secret authority for every KORAS repository
and this framework does not become a second one.

The same refusal exists in the Control Plane, as `koras.setting_holds_no_secret()`
in `koras-control-plane/supabase/migrations/00045_product_settings.sql`. It is a
function rather than an inline check because Postgres refuses a subquery in a
`CHECK`, which this estate has now discovered three times.

## The snapshot

A new organisation receives a **copy** of the applicable global values, taken at
provisioning inside the transaction that creates the tenant. Later changes to a
platform default never reach an organisation that already exists; a newly
created one gets whatever the defaults say that day.

`core/tenant_store.py` calls `seed_tenant` on both the create and the retry
path, before the single commit, so a tenant cannot exist without its snapshot
even if provisioning is retried.

`profiles/product/template/supabase/migrations/00030_settings_snapshot.sql`
records what was copied: `tenants.settings_global_version`,
`settings_copied_at`, `settings_copied_by`. Without those columns "this
organisation has an old default" and "this organisation chose that value
deliberately" are the same row.

### What the snapshot cost, and the rule it produced

A setting whose absence means *infer it from context* stops inferring the moment
it is snapshotted, because the snapshot gives it a value. `general.language` was
exactly that: absent, the product negotiated `Accept-Language`. Copied, it would
have pinned every new organisation to whatever the default said.

The answer is the `auto` value — `LANGUAGE_OPTIONS` is `auto` followed by the
offered locales — and the rule the ADR now carries: **a setting whose absence
means "infer it from context" must express that inference as one of its values,
or the snapshot will silently end the inference.**

## The catalogue is code

`SettingDefinition` is a frozen dataclass in the shared package
`profiles/_shared/template/python-packages/koras-settings`, registered at
import. A duplicate key is a traceback at startup rather than a 500 later, which
is the same shape `koras_reporting` and `koras_audit.AuditActionRegistry`
already use.

The definition refuses, in `__post_init__`, a key that is not `group.name`, an
enum with no options, a default outside its own bounds, and `user_visible` on a
scope that is not three-level. Those are not validations performed on a request;
they are conditions under which the process does not start.

| Scope | Who may set it |
|-------|----------------|
| `GLOBAL_ONLY` | The platform |
| `GLOBAL_ORG` | The platform and an organisation |
| `GLOBAL_ORG_USER` | The platform, an organisation and a person |

A person may never override a setting that is not `GLOBAL_ORG_USER`. That is
enforced in `check_writable()` in the shared package, so both the API and the
Control Plane get the same refusal from the same code rather than from two
implementations that agree until they do not.

### What ships in the catalogue

`profiles/product/template/services/api/koras_api/settings_catalogue/standard.py`
declares 32 settings in seven categories — general, ui, grid, notifications,
files, reporting, accessibility. Five of them are marked `surfaced=False`, which
is a deliberate and slightly uncomfortable piece of honesty:
`grid.allowColumnResize`, `grid.allowColumnReorder`, `grid.rememberFilters`,
`grid.rememberSort` and `grid.rememberColumns` are in the brief's catalogue and
nothing in the shared table honours them yet. A setting a person can change that
changes nothing is worse than one that is not offered, so they are registered,
resolvable and not drawn. **27 settings appear on the two pages.**

`settings_catalogue/product.py` ships an empty `SETTINGS` list. That file is the
extension point: a product adds its own settings there and they appear on both
pages, in the API, and in the Control Plane's view of that product, without an
edit to any page.

## Resolution

One request answers everything. `GET /settings/effective` returns, per key, the
key, the value, the source, whether the caller may override it, the
organisation's value and the platform's value.

The source is which rung the value came from. The two extra values are there
because both editing pages need the rung *below* the one they edit — clearing a
preference has to show what it goes back to, and a page that has to make a
second request to find out will eventually not make it.

The route requires no permission. Reading what applies to you is not an act that
needs authority, and the resolution is scoped to the caller's own tenant and
subject by the database.

The product's `apps/web` resolves it once in the dashboard layout and puts it in
a provider; `useSettings()` and `useSetting` read from there. No component
fetches settings.

### The routes

The product's own router is
`profiles/product/template/services/api/koras_api/routers/settings.py`:

| Route | Who |
|-------|-----|
| `GET /settings/definitions` | Any signed-in caller |
| `GET /settings/effective` | Any signed-in caller, no permission |
| `GET /tenant/settings/values` | A caller who may read settings |
| `PATCH /tenant/settings/values` | A caller with `settings.manage` |
| `POST /tenant/settings/values/{key}/reset` | A caller with `settings.manage` |
| `GET /me/settings` | The caller, for themselves |
| `PATCH /me/settings` | The caller, for themselves |
| `DELETE /me/settings/{key}` | The caller, for themselves |

The platform's three are in `routers/platform.py`:
`GET /settings/definitions`, `GET /settings/global` and `PUT /settings/global`.

## The grid

A data table works with no props beyond the data. Page size, whether it pages at
all, the sizes offered, the sticky header and the row density all come from the
resolved `grid.*` settings.

An explicit prop wins over the setting. That is the whole of the precedence
rule, and it is one function — `chooseValue` in
`profiles/product/template/packages/ui/src/data-table/paging.ts` — rather than a
rule repeated at each call site.

`DEFAULT_PAGE_SIZE` is 50, paging is on, and the offered sizes are 10, 25, 50,
100 and 250, which is what the brief asks for.

## The two customer pages

| Page | Shows | Falls back to |
|------|-------|---------------|
| `/dashboard/settings` | Settings an organisation may change | The platform's value |
| `/dashboard/preferences` | Settings a person may change | The organisation's value |

Neither page knows how a control is drawn and neither knows which scope it is
editing. `SettingsForm` takes groups of fields; the two differences that matter
— whether a value is set, and what it falls back to — are data.

One form per category rather than one per page. A single form for 27 settings
makes every save a 27-field write, and an administrator who changed the upload
limit would get an audit entry for everything they merely looked at.

My preferences carries **no permission requirement**, in the nav module and in
the page. The row is keyed to the caller's verified subject, which is what makes
it safe — the same position `PUT /me/locale` has held since the language work.

The organisation page renders for anybody who may read settings and tells a
member without `settings.manage` that they may not change it *before* they fill
anything in. The API refuses the write regardless; that is the boundary, and the
notice is courtesy rather than security.

## The Control Plane's half

The Control Plane is not code-synced from this repository. Its share of this
framework is a parallel implementation against an extended contract, and the
only byte-identical file is `contracts/product-platform.v1.json`.

It reads a product's published catalogue through the platform contract's
definitions route and writes platform defaults back through the contract's
global settings route. That write route needed the ADR, because the contract's
`no_direct_writes` rule and the 2026-09-16 decision that *the platform may only
act in the direction that keeps data* both had to be squared with a platform
that sets a default. The squaring is in the ADR: a default is not a customer's
data, and setting one cannot remove a value an organisation holds.

Console: Settings → Global Settings, Setting Definitions, Change History. The
history is `audit_events` filtered to the settings actions rather than a second
audit table, and it is the **platform's** history — a customer changing its own
settings is recorded in that product's own `audit_events`, under that tenant's
isolation, and is not visible from the console.

## Audit

Every write to every scope is audited through the existing
`koras_audit.AuditActionRegistry`. There is no settings-specific audit table, no
settings-specific retention and no settings-specific export. A second register
for one feature is a second thing to retain, protect and remember to read.

## Where the locale went

`general.language` replaced two columns that stored the same fact twice:
`tenant_settings.locale` and `member_preferences.locale`.
`profiles/product/template/supabase/migrations/00031_settings_locale_migration.sql`
backfills both into the framework, drops the column and drops the table.

The timing was an amendment to the ADR rather than the original decision. A
migration that moves a live column is the kind of thing that is easy to defer
and then never do, and two places storing one fact is how they disagree.

## What has no automated proof

The e2e suite starts the web application and nothing else — no API, no database.
Sixteen checks run at 1440 and 375, and they prove that both addresses exist,
that a stranger is sent to sign in, that the least-privileged member reaches My
preferences *and is refused the organisation's settings*, that a caller with
`settings.read` and not `settings.manage` is told so before filling anything in,
that an administrator is not told that, and that a page whose catalogue cannot
be read says so rather than falling over.

Writing them corrected two things this document would otherwise have claimed.
Both refusals come from the **middleware**, as a 403 before the route runs,
rather than from the `AccessDenied` component. And a session with no roles at
all is refused the application entirely — `member` is the least-privileged
caller who exists, and "My preferences needs no permission" means no *settings*
permission, not no role.

It does not prove the round trip. Changing `grid.pageSize` and watching a table
repaginate needs an API, a database and rows; stubbing them would prove the
stub. That is `docs/features/settings-framework/manual-test-plan.md`, run by a person against a
deployed environment.

No manual pass has been run against any of this as of 2026-09-19.
