# Settings & Preferences Framework — architecture

The design as proposed on 2026-09-17. Nothing described here is built yet; this
is the document the implementation is measured against, not a description of the
system.

Read `audit.md` first — in particular the six conflicts, four of which this
document resolves against the brief's literal wording.

---

## 1. The shape of the thing

```
        DEFINITION                              VALUE
        (what a setting is)                     (what it is set to)

   SettingDefinition, frozen,          global_settings        no tenant
   declared in Python, registered      tenant_setting_values  per tenant
   at import, published over the API   member_setting_values  per tenant, per person

                         resolution, per key
                         -------------------
                         member_setting_values   if the scope permits it
                         tenant_setting_values
                         global_settings
                         definition.default      always present
```

Four levels, exactly as the brief's section 8 requires. The fourth is not a
"code fallback only if required" — it is the definition's own default, is
mandatory on every definition, and is what makes a product with no Control Plane
and no configured rows behave correctly on its first request.

There is no product-level tier. There never will be one without an ADR.

---

## 2. Definitions

### The type

A frozen dataclass in a new shared package,
`profiles/_shared/template/python-packages/koras-settings/`, modelled directly on
`koras_reporting.definitions`:

| Field | Type | Notes |
|-------|------|-------|
| `key` | `str` | Dotted lower-case, `<category>.<name>`, same regex discipline as `AuditAction` |
| `category` | `Category` | StrEnum: general, appearance, grid, notifications, files, reporting, accessibility, and the seven reserved below |
| `data_type` | `DataType` | StrEnum: boolean, integer, decimal, string, enum, string_list, object |
| `default` | `SettingValue` | Mandatory. The fourth resolution level |
| `scope` | `Scope` | StrEnum: `GLOBAL_ONLY`, `GLOBAL_ORG`, `GLOBAL_ORG_USER` |
| `label_key` | `str` | An i18n key, not English prose |
| `description_key` | `str` | An i18n key |
| `options` | `tuple[str, ...]` | Required when `data_type` is enum |
| `minimum` / `maximum` | `int \| None` | Integer and decimal bounds |
| `org_admin_visible` | `bool` | Default true |
| `user_visible` | `bool` | Default true, and refused unless the scope is the three-level one |
| `sensitive` | `bool` | Value redacted in audit details |
| `system` | `bool` | Never shown in a customer surface |
| `status` | `Status` | available or deprecated — this replaces the brief's active flag |
| `order` | `int` | Display order within a category |
| `ui` | `UiHint` | select, toggle, number, text, chips — a hint, never behaviour |

The post-init refuses, at import:

- a key that is not dotted lower-case;
- an enum with no options, or a default not among them;
- an integer or decimal default outside its own bounds;
- `user_visible` on anything that is not `GLOBAL_ORG_USER` — this is the brief's
  section 3 rule, enforced where it cannot be forgotten;
- a missing label or description key.

### The registry

`SettingsRegistry.add` raises on a duplicate key. `build_catalogue()` is called
once at import and a bad catalogue is a traceback with a stack rather than a 500
for a customer — `koras_reporting/registry.py:1-6` states that reasoning and it
holds here unchanged.

Iteration is ordered by `(category order, order, key)` so two runs of one build
agree.

### Where the catalogue is assembled

Same two-part shape reporting uses:

- `services/api/koras_api/settings_catalogue/standard.py` — the foundation
  catalogue from the brief's section 6.
- `services/api/koras_api/settings_catalogue/product.py` — ships empty, with a
  worked example in its docstring, exactly as `reporting/reports.py` does.

### Why not a table, and why not a TypeScript mirror

Both are answered in `audit.md` C1. In one line each: a table edited from a form
is a list of keys nobody tests, and a second catalogue is a second thing to keep
level. The frontend reads the catalogue from the API and renders from the
metadata, so labels, types, bounds and options exist once.

The one exception is a **narrow TypeScript union of setting keys**, so
`useSetting<number>('grid.pageSize')` is typed. It is kept level by a structural
test that reads both files as text, the way
`product-ai.test.ts:101-102` compares the two permission catalogues. A union of
strings is not a second catalogue; it carries no labels, no defaults and no
rules.

---

## 3. Values

### Three tables, one row per key

```sql
-- global_settings        key, value jsonb, version int, updated_at
-- tenant_setting_values  tenant_id, key, value jsonb, updated_at   PK (tenant_id, key)
-- member_setting_values  tenant_id, user_id, key, value jsonb, updated_at
--                                                       PK (tenant_id, user_id, key)
```

**The names changed on building it, 2026-09-17.** This said
`organization_settings` and `member_settings`. `organization` is the wrong word
in this schema -- `current_organization_id()` returns a ZITADEL organization and
migration `00004` exists because that key and the tenant's are not the same --
and `tenant_settings` already exists holding branding, domains and features as
documents, so `_values` keeps the two a word apart rather than a letter. ADR
0007 decision 3 carries the amendment.

Row-per-key rather than a JSONB blob per scope, for four reasons that each cost
something otherwise:

1. A reset is a `DELETE`, not a read-modify-write of a document.
2. "Is this overridden" is the existence of a row, not a key test inside a blob.
3. An audit event names one key and carries one before and one after value.
4. Two administrators saving different categories at the same time cannot
   clobber each other.

The value column is `jsonb` and not a text column with a type tag, so an
integer is an integer, a list is a list, and the definition's `data_type` is
what decides how it is read back.

### What the tables refuse

Every one of them carries the check constraint the Control Plane's policy tables
already use — a top-level key matching secret, token, password, access key,
private key or credential is rejected by the database
(`00009_policy.sql:19-21`). The brief's section 27 says secrets never enter the
settings framework; a constraint is how that survives the person who did not
read the brief.

### RLS

`tenant_setting_values` follows `tenant_settings`: policies keyed on
`current_tenant_id()`, RLS enabled **and forced**, and **no delete policy** --
a tenant resets by taking the platform's current value, and deleting the row
would restore the dynamic inheritance the snapshot prevents.

`member_setting_values` follows `member_preferences` exactly, and does have a
delete policy, because a person resetting means "stop deciding this for me": per-verb policies keyed
on **both** `current_tenant_id()` and `current_user_id()`, so a member cannot
read a colleague's preference and a request that declares no subject — the
worker, a platform call — sees and writes nothing.

`global_settings` has no tenant column. It is readable by any declared caller
and writable only under the provisioning context, the same way
`00003_platform_provisioning.sql` admits the platform.

Three numbered isolation suites ship with the migration.

### The snapshot

At `core/tenant_store.py:180-182`, after the owner membership upsert and before
the single commit:

```
for definition in catalogue where scope is not GLOBAL_ONLY:
    value = global_settings[definition.key]  or  definition.default
    insert into tenant_setting_values (tenant_id, key, value)
        on conflict (tenant_id, key) do nothing
```

`on conflict do nothing` for the reason `apply_ai_routing_template` uses it: a
retried provisioning must not overwrite what somebody has since edited.

Provenance goes on the tenant row — the global version it was copied from, when,
and which actor. The brief's section 10 asks for all three.

**A setting whose absence carries meaning needs a value that says so.** Seeding
gives every organisation-scoped key a row, so any behaviour that keyed off "no
row" stops happening the moment the framework arrives. `general.language` is the
one such setting today, as of 2026-09-17: it resolves through a chain that falls
through to `Accept-Language`, and a seeded language would end that. It defaults
to `auto`, which the API maps back to null. A future setting with the same shape
does the same thing rather than opting out of the snapshot.

`GLOBAL_ONLY` settings are deliberately **not** copied. They have no
organisation value by definition, so a row would be a value nobody may change
and every reader would have to ignore.

---

## 4. Resolution

```python
def resolve(key, *, tenant_id, user_id) -> Resolved
def resolve_all(*, tenant_id, user_id) -> dict[str, Resolved]
```

`Resolved` carries `key`, `value`, `source` (`user`, `organization`, `global`,
`default`) and `can_override` — the brief's section 8 metadata, unchanged.

`resolve_all` is the one the request path uses. It is **three queries, not one
per key**: all member rows for this person, all organisation rows for this
tenant, all global rows. The catalogue supplies the keys and the defaults, so a
key with no row anywhere still appears in the answer with `source = default`.

A row whose key is not in the catalogue is ignored rather than returned. A
definition removed in a deploy must not make an old row into an unknown setting
a page then tries to render.

A row whose value no longer validates against its definition — a bound
tightened, an option withdrawn — resolves to the next level down and is reported
in the answer's `invalid` list. The alternative is a page that will not render
because somebody narrowed a range.

---

## 5. Writing

One coercion path, borrowed wholesale from
`koras_reporting/filters.py:140`: the definition decides, an enum must be among
its options, an integer must parse and respect its bounds, an unknown key is
**refused rather than ignored**.

Three refusals are the brief's mandatory test scenarios 9, 10 and 11:

| Attempt | Answer |
|---------|--------|
| A person writes a key whose scope is not the three-level one | 403, and the scope is the reason |
| An organisation writes a `GLOBAL_ONLY` key | 403 |
| Any scope writes a value the definition refuses | 422, with the definition's own bound in the message |

Each is a code in `ApiErrorCode` with a sentence in all three i18n catalogues.

---

## 6. The API

Product, on `/api/v1`, all behind the authenticated rate limiter:

| Route | Permission | Answers |
|-------|-----------|---------|
| `GET /settings/definitions` | `settings.read` | The catalogue, filtered to what this caller may see |
| `GET /settings/effective` | none beyond product access | Every resolved setting for this caller, with source and override metadata |
| `GET /settings/organization` | `settings.read` | The organisation's own rows, with the global value beside each |
| `PATCH /settings/organization` | `settings.manage` | Writes several keys in one transaction |
| `POST /settings/organization/{key}/reset` | `settings.manage` | Copies the **current** global value in — never restores inheritance |
| `GET /settings/preferences` | none | This person's own rows |
| `PATCH /settings/preferences` | none | Writes this person's own rows |
| `DELETE /settings/preferences/{key}` | none | Removes one row, so the organisation value resolves again |

Platform, on `/internal/platform/v1`, machine identity only:

| Route | Answers |
|-------|---------|
| `GET /settings/definitions` | What this product declares, for the console to render |
| `GET /settings/global` | What the product holds as platform defaults |
| `PUT /settings/global` | Replaces them, and bumps the stored version |

`PUT /settings/global` is the first contract route admitted by the
may-only-act-in-the-direction-that-keeps-data rule. It can reach `global_settings`
and nothing else; the route does not accept a tenant and there is nowhere in it
to name one, which is the same property `routers/tenant.py:24-30` relies on.

Reset deserves its own sentence, because it is the brief's section 13 warning:
**reset copies the current global value into the organisation row.** It does not
delete the row and it does not re-establish inheritance. A customer who resets
and a customer who never configured anything are in different states, and only
one of them tracks the platform.

---

## 7. The frontend

### One load per request

`apps/web/src/app/dashboard/layout.tsx.hbs` already resolves the signed-in
context, the locale and the tenant settings for every page in the area. The
effective settings join that load, wrapped in React `cache()` like its
neighbours, and are passed into a `SettingsProvider` around the shell.

No page fetches settings. No component fetches settings. `revalidatePath('/dashboard', 'layout')`
after a write is the established invalidation and is what
`dashboard/settings/actions.ts.hbs:55` already does for the same reason.

### The hooks

```tsx
const settings = useSettings()                       // the whole resolved map
const pageSize = useSetting<number>('grid.pageSize') // one value, typed
```

`useSetting` reads from context and never fetches. A component rendered outside
the provider gets the definition's default rather than throwing, because a
settings lookup must not be able to take a page down — the same position
`lib/tenant-settings.ts.hbs:29-46` takes for branding.

---

## 8. The grid

`KorasDataTable` is new, in
`profiles/product/template/packages/ui/src/data-table/`. It is the product's
first general table; the reporting table stays where it is and keeps its job.

```tsx
<KorasDataTable data={records} columns={columns} />   // pages at grid.pageSize
<KorasDataTable data={records} columns={columns} pageSize={20} />  // 20, explicitly
```

Resolution order for every grid setting, and the brief's section 7 requires
exactly this:

```
explicit component prop   ->   resolved setting   ->   definition default
```

The component reads `grid.pageSize`, `grid.pageSizeOptions`,
`grid.paginationEnabled`, `grid.stickyHeader`, `grid.allowColumnResize`,
`grid.allowColumnReorder`, `grid.rememberFilters`, `grid.rememberSort`,
`grid.rememberColumns` and `grid.rowDensity` from context. The first three drive
behaviour on day one; the remainder are consumed and honoured where the
component can honour them, and the ones that describe persistence
(`remember*`) are wired to the URL, which is where the Control Plane's
`TableToolbar` already keeps such state.

Accessibility is not optional here: a real `<table>`, `scope="col"` headers, a
screen-reader caption, keyboard-operable pager controls with visible focus, and
an empty state that is a sentence rather than an empty grid — every one of those
is what `report-table.tsx` already does, and the new component inherits the
conventions rather than inventing new ones.

Default page size is **50**, paging **on**, options 10 / 25 / 50 / 100 / 250.

### The Control Plane's table

It gets the same capability by a different route: pagination is added to
`apps/admin/src/components/ui/DataTable.tsx` in that repository, taking its page
size from the platform's own resolved settings. It is not given
`KorasDataTable`, because nothing flows from the starter into that repository
but the contract.

---

## 9. Authorization

Server-side, always. The product's convention is an explicit guard called as the
first statement of the handler (`routers/audit.py:91-97`), and this router
follows it.

- `settings.read` and `settings.manage` already exist in both catalogues and are
  already granted per role. Nothing is added.
- A person's own preferences need no permission. Writing one is the same act as
  choosing a language today, which requires none; the RLS policy keyed on the
  caller's own subject is what makes it safe, not a permission string.
- The Control Plane gets one new `AREA_ROLES` key, `settings`, and the endpoint
  dependency is set from that list — the rule `docs/CONSOLE_UI.md:466-477`
  records after the two lists once drifted.

Hiding a control is presentation. Every page re-checks, every server action
re-establishes the caller, and the middleware gates the route.

---

## 10. Audit

Six actions, registered in the settings module's own file at import, the way
`core/reporting.py.hbs:47-80` registers reporting's:

| Action | Class |
|--------|-------|
| `settings.global_changed` | administrative |
| `settings.organization_initialized` | administrative |
| `settings.organization_changed` | administrative |
| `settings.organization_reset` | administrative |
| `settings.user_changed` | activity |
| `settings.user_reset` | activity |

The details carry the key, the scope, the before value and the after value. A
definition marked sensitive has its values replaced by a marker rather than
omitted, so the record still says a change happened. `_FORBIDDEN_DETAIL` in
`koras_audit` already refuses a detail key that looks like a secret, and the
table's check constraint already refuses a secret-shaped value, so there are two
independent guards and neither is the only one.

The organisation initialisation event is emitted once, from the snapshot, under
the provisioning context.

---

## 11. Caching

None is added.

Section 18 of the brief asks for the existing infrastructure to be reviewed
first. The review is in `audit.md`: there is no cache layer in either
repository, the one declared cache knob is read by nothing, and the frontend
convention is per-render de-duplication plus path revalidation. Three indexed
queries per request, on tables with a handful of rows per tenant, does not
warrant a Redis round trip on the request path — the same argument
`core/security.py:101` makes for the rate limiter.

What is built now so that a cache is possible later without a redesign: a
monotonic settings version per tenant, bumped on every write. A future cache key
of tenant, person and version needs no schema change.

---

## 12. What the Control Plane holds

Two tables in migration 00045: the platform's default value per
`(product, key)`, and the monotonic global version per product.

Three pages under one new Settings section, following the console's existing
five-step procedure for adding one:

- **Global Settings** — grouped by category, each field showing its label,
  description, current value, the definition's default, its scope, its
  validation and when it last changed.
- **Setting Definitions** — read-only, per product, rendered from what that
  product publishes.
- **Change History** — the platform's own `audit_events` filtered to the
  settings actions.

The console never writes an organisation's settings. It has no route to do so
and the contract has no shape for it.

---

## 13. Versioning, and what is deliberately not built

The global version is a monotonic integer per product, bumped on every write of
a platform default. An organisation records the version it was initialised from.

That is all. There is no bulk propagation, no "apply to organisations still on
the previous default", no selective push. The brief's section 11 asks for the
architecture to permit them later and asks for none of them to be implemented,
and the version column plus the snapshot provenance is exactly what a later
propagation would need.

Also deliberately absent, as of 2026-09-17: a settings import or export, a diff
between an organisation and the current global, per-environment defaults, and
any scheduled reconciliation. Each is recorded as a deferred item rather than
half-built.
