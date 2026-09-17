# ADR 0007 — Settings & Preferences Framework

**Status.** Accepted, 2026-09-17. The framework package and the schema are
built; the API, the frontend and the Control Plane are not. The audit it rests
on is `docs/features/settings-framework/audit.md` and the design is
`docs/features/settings-framework/architecture.md`. Two decisions were amended
on building it, both marked below.

**Context.** Every KORAS surface needs values a customer can change — how many
rows a grid shows, which date format, whether a digest is emailed — and there is
nowhere to put them. Read across all three repositories on 2026-09-17, there is
no settings framework at any scope: no definition registry, no key/value table,
no platform defaults, no settings router, no Settings section in the console.
What exists is five ad-hoc columns on `tenant_settings`, one column on
`member_preferences`, and a `feature-flags` package that is two lines long.

The absence has a visible cost. There is no general table component in a
generated product at all — every dashboard surface hand-rolls its markup, only
the audit panel paginates, and each does it differently. A grid that reads its
page size from a setting cannot exist before the setting can.

Three constraints shaped the answer more than the requirements did.

- **The Control Plane is not kept in sync from the starter.** It was generated
  once and built out independently; `docs/features/PROFILE_SYNC_MATRIX.md:36-45`
  records that exactly one artifact is genuinely shared,
  `contracts/product-platform.v1.json`. Any design that assumed a code sync
  would produce work nobody could apply.
- **The contract forbids the platform writing product tables.** The 2026-09-16
  decision recorded in the same file admits platform action through contract
  routes under one mechanical test — the platform may only act in the direction
  that keeps data — and says a write route needs its own ADR first. This is that
  ADR.
- **Entitlements deliberately do not snapshot.** The provisioning step at
  `services/worker/koras_worker/provisioning/steps.py:365-374` exists to record
  that they resolve on read, every time. A settings framework that copies at
  provisioning is doing the opposite of the nearest thing in the estate, and the
  difference has to be justified rather than discovered.

**Decision.**

1. *Definitions are declared in code and registered at import; values live in
   the database.* The split is the whole design. A definition is a frozen
   dataclass with a mandatory default, a scope, validation bounds and i18n keys;
   the registry refuses a duplicate key, an enum default outside its options, and
   `user_visible` on a scope that does not admit a person. All of it fails at
   import, where it is a traceback with a stack, rather than at request time,
   where it is a 500 for a customer.

   This follows every comparable catalogue here — `koras_reporting`'s registry,
   `koras_audit`'s action registry, `MODEL_ALIASES`, `PLAN_CATALOGUE` — and
   `koras_platform/ai.py:1-21` states the reasoning plainly: a table edited from
   a form is a list of names nobody tests.

   The consequence, and it is the reason this decision is first: the Control
   Plane cannot know a product's settings by reading its own database. It must
   read what the product publishes. That is what makes the contract extension
   in decision 6 necessary rather than convenient.

2. *A new organisation receives a copy, and later platform changes never reach
   it.* Written inside the single transaction at `core/tenant_store.py:180-182`,
   with `on conflict do nothing` so a retried provisioning cannot overwrite an
   edit somebody has since made — the property `apply_ai_routing_template`
   already relies on.

   **Why this is the opposite of entitlements, deliberately.** An entitlement is
   what a customer bought; changing their plan must reach them immediately, so
   resolving on read is correct and materialising it would be a bug. A setting is
   a default somebody was handed; changing the platform default must *not*
   silently change what a customer has been running on. The two look alike and
   are not: one tracks a contract, the other preserves a choice. The next reader
   will ask, which is why it is written here.

   Global-only settings are not copied. They have no organisation value by
   definition, and a row nobody may change is a row every reader must learn to
   ignore.

3. *One value per row, at all three scopes.* Not a JSONB document per scope. A
   reset becomes a delete, "is this overridden" becomes the existence of a row,
   an audit event names one key with one before and one after, and two
   administrators saving different categories cannot clobber each other. The
   cost is three queries per request instead of one, on tables holding a few
   dozen rows per tenant.

   **Amended 2026-09-17 on building it.** The tables are `global_settings`,
   `tenant_setting_values` and `member_setting_values`. The design said
   `organization_settings` and `member_settings`, and `organization` is the
   wrong word in this schema: `current_organization_id()` returns a ZITADEL
   organization, `tenants.zitadel_org_id` holds one, and migration `00004`
   exists precisely because that key and the tenant's are not the same. The
   customer is a *tenant* in `tenant_settings`, `tenant_members` and
   `tenant_plans`, and a table named for the organization and keyed by the
   tenant would read as the other one on the day somebody is hunting a
   cross-tenant leak.

   `_values` rather than `_settings` because `tenant_settings` already exists
   and holds something else: one row per tenant carrying branding, domains and
   features as documents. Two tables one letter apart would be two tables
   people confuse.

4. *Resetting copies the current platform value in; it does not restore
   inheritance.* A customer who resets and a customer who never configured
   anything are in different states, and only one of them tracks the platform.
   Making reset a delete would quietly reintroduce the dynamic inheritance
   decision 2 exists to prevent.

5. *The framework is foundation, not a capability.* The rule at
   `profiles/product/manifest.yaml:170-186` is that a table is gated only when no
   foundation code and no foundation migration reaches it. The shell resolves
   settings on every signed-in request, so nothing about this can be gated. This
   is the mistake `audit_events` made by sitting inside the `reporting` gate: a
   product without analytics recorded nothing, and nobody noticed.

6. *The platform owns the defaults, and reaches them through one contract route
   that can touch nothing else.* `PUT /settings/global` is the first route
   admitted by the may-only-act-in-the-direction-that-keeps-data rule. It
   qualifies because a configuration write neither destroys nor discloses.

   The route accepts no tenant and there is nowhere in it to name one — the same
   property `routers/tenant.py:24-30` relies on for customer routes, and the
   reason it is safe is the same: a caller cannot ask for something the request
   has no parameter to ask for. It can reach `global_settings` and nothing else.
   An organisation's values remain unreachable from the console, in either
   direction.

7. *No permission strings are invented.* `settings.read` and `settings.manage`
   already exist in both product catalogues and are already granted per role. A
   person setting their own preference needs no permission — it is the same act
   as choosing a language today, which requires none, and what makes it safe is
   the RLS policy keyed to the caller's own subject rather than a string. The
   Control Plane gets one new `AREA_ROLES` key, because that is its vocabulary;
   it has no permission catalogue to add to.

   Nine permission strings collapsing onto two existing ones and one role key
   would make the catalogue parity test guard a fiction.

8. *The language preference moves into the framework rather than sitting beside
   it.* `tenant_settings.locale` and `member_preferences.locale` are backfilled
   into the new tables and both columns are dropped in the same migration, with
   `routers/tenant.py`, the member-preferences isolation suite and the language
   e2e spec changed in the same commit.

   **Amended 2026-09-17 on building it.** The move happens in migration `00031`
   and lands with the settings API rather than with the tables. Dropping the
   columns in the same phase that created the tables would have left
   `routers/tenant.py` selecting a column that no longer exists for as long as
   it took to build the router that replaces it -- a phase boundary in the
   middle of a broken read. The tables arrive first and nothing reads them;
   the columns go when there is somewhere else to read from.

   This is the largest piece of migration risk in the feature and it is taken on
   purpose. Registering a language setting while the old columns still answered
   the same question would be two sources of truth for one value, which is the
   failure this estate has already had once.

9. *No cache is built.* There is none to reuse — the review section 18 of the
   brief asks for found no cache layer in either repository, and the one declared
   cache knob, `ReportDefinition.cache_seconds`, is read by nothing. Three
   indexed queries do not warrant a Redis round trip on the request path, which
   is the argument `core/security.py:101` already makes for the rate limiter. A
   monotonic settings version per tenant is written now so a future cache key
   needs no schema change.

10. *No bulk propagation.* The version an organisation was initialised from is
    recorded, and nothing acts on it. Applying a newer default to existing
    organisations — all of them, the ones still on the previous value, or a
    chosen few — is a separate decision with a customer-visible blast radius, and
    the provenance columns are what a later one would need.

**Consequences.**

- A product generated with no Control Plane still works correctly: the fourth
  resolution level is the definition's own default, which is mandatory, so the
  first request on a fresh database resolves every key.
- The Control Plane's Setting Definitions page is a read-only inspector. Nobody
  authors a setting from a console; a setting is added in a commit, with tests.
- `KorasDataTable` becomes the product's first general table component, and the
  Control Plane's `DataTable` gains pagination separately, in its own
  repository. They will not be the same file, and the sync matrix says why.
- Adding a setting later costs: one definition, entries in three i18n
  catalogues, and a test. It costs no persistence code, which is the point.
- The three value tables each need RLS enabled and forced, per-verb policies and
  a numbered isolation suite, or `010_rls_structure.sql` fails on a table with no
  policy.

**Alternatives considered.**

- *A `setting_definitions` table, as the brief describes.* Rejected under
  decision 1. It also cannot serve the Control Plane without a second mechanism
  for learning each product's keys, so it would not have removed the contract
  work it appeared to avoid.
- *Extending `tenant_settings` with a `settings` JSONB column.* Cheapest by far
  and rejected under decision 3: per-key reset, per-key audit and concurrent
  saves all become read-modify-write of one document.
- *A TypeScript mirror of the catalogue, as the permissions catalogues do.*
  Rejected because the parity tax is real and avoidable here — the frontend can
  read labels, types, bounds and options from the API, which permissions cannot
  do because they gate the middleware before any call. A narrow union of key
  names is kept in TypeScript for typing and is checked against the Python
  catalogue as text.
- *Resolve-on-read from the platform, matching entitlements.* Rejected under
  decision 2. It is the same mechanism with the opposite meaning, and it would
  make every platform default change a silent change to every existing customer.
