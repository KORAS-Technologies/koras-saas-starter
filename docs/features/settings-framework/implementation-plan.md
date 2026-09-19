# Settings & Preferences Framework — implementation plan

Written 2026-09-17, at the close of Phase 1. Phases 2 to 5 are done; 6 onward
are not started, as of 2026-09-19.

---

## The order, and why it is this order

Each phase leaves the three repositories green. Nothing here is a big-bang
merge, and no phase depends on a later one.

```
2  package          definitions, registry, resolver, validation   (no I/O, no schema)
3  schema           migrations, RLS suites, the provisioning snapshot
4  API              router, audit actions, error codes, i18n
5  provider         SettingsProvider, useSettings, useSetting, one load per request
6  grid             KorasDataTable
7  product UI       Organisation Settings, My Preferences
8  platform         contract extension, Control Plane implementation
9  shop             sync, plus the validating list surface
10 hardening        full automated run across all three
11 documentation    developer guide, manual test guide, boundary audit
```

Phase 2 is pure logic with no I/O, so it is fully unit-testable before a table
exists. Phase 6 depends on 5 and nothing else. Phase 8 is the only phase that
touches two repositories, and it is late deliberately: the contract should be
extended once, against a catalogue that has stopped moving.

---

## Workstreams

The brief's section 24 asks for parallel workstreams where files do not
conflict. These four do not overlap on a single file.

| Stream | Phases | Owns |
|--------|--------|------|
| **A — data and domain** | 2, 3, 4 | `python-packages/koras-settings`, `supabase/migrations`, `supabase/tests`, `services/api/koras_api/routers/settings.py`, `core/tenant_store.py` |
| **B — shared frontend** | 5, 6 | `packages/ui/src/data-table`, `apps/web/src/lib/settings.ts`, `apps/web/src/app/dashboard/layout.tsx` |
| **C — product and platform surfaces** | 7, 8 | `apps/web/src/app/dashboard/settings/**`, `apps/web/src/app/dashboard/preferences/**`, and the whole Control Plane change |
| **D — verification and documentation** | every phase | `tests/**`, `e2e/**`, `generators/create-koras-app/tests/**`, `docs/**` |

B cannot start before A's Phase 4 publishes a shape; C cannot start before B's
Phase 5. D runs alongside all of them and is not a phase at the end.

### Agents

The starter carries the four common agent definitions — `architect`,
`frontend`, `reviewer`, `tester` in `.claude/agents/` — and the common skills.
The forty-agent orchestration framework at
`profiles/product/template/.claude/` is **product-only**: it is a template
shipped into generated products, not a planner this repository runs, and
`generators/create-koras-app/tests/orchestration.test.ts` asserts it never
reaches the Control Plane. Work in the starter uses the four; work inside
`koras-e2e-shop` may use the forty, because that repository has them.

Mapping the brief's suggested roster onto what exists:

| Brief's agent | Here |
|---------------|------|
| Dev Agent 1 (database, domain, APIs) | Stream A, reviewed by `architect` |
| Dev Agent 2 (frontend, provider, grid) | Stream B, reviewed by `frontend` |
| Dev Agent 3 (Control Plane, org settings, preferences) | Stream C |
| QA/Test | Stream D, using `tester` |
| Documentation | Stream D |
| Sync | Stream C's Phase 9, by the three-way method below |

No new agent is created. The audit found no capability gap that an existing
definition does not cover.

---

## Phase detail

### Phase 2 — the package

New: `profiles/_shared/template/python-packages/koras-settings/`, modules
`definitions.py`, `registry.py`, `values.py`, `resolver.py`, `coercion.py`,
`__init__.py`, and a `tests/` suite beside the code — the layout
`koras-reporting` uses.

Exit: the package's own pytest suite passes; a duplicate key, a bad default, an
enum default outside its options and a user-visible non-three-level scope each
raise at import.

### Phase 3 — schema  *(done 2026-09-17)*

`00029_settings.sql` and `00030_settings_snapshot.sql`, isolation suites 260,
270 and 280, the settings catalogue in `services/api/koras_api/settings_catalogue/`,
`core/settings_store.py`, and the snapshot inside `tenant_store.create`.

**The locale migration moved to Phase 4.** It was to be `00030` here; dropping
`tenant_settings.locale` and `member_preferences.locale` in the phase that
created the tables would leave `routers/tenant.py` selecting a column that no
longer exists until the router replacing it was built. It is `00031` and it
lands with the API.

Exit, met: every product migration applies in order to a clean Postgres; all 26
isolation suites pass, including the structural one that requires forced RLS and
at least one policy on every table; `koras-settings` and the two new product
suites pass; ruff and mypy `--strict` are clean; the full generator suite
passes.

### Phase 4 — API  *(done 2026-09-17)*

`routers/settings.py` with eight routes, registered ungated; six audit actions;
three error codes with sentences in `en`, `de` and `es` and a branch in the web
mapping; `require_subject` in `core/tenant.py`; and
`00031_settings_locale_migration.sql` with the changes to `routers/tenant.py`
and the isolation suite that go with it.

**The platform routes moved to Phase 8.** They need three new entries in
`contracts/product-platform.v1.json`, which is the one artifact kept
byte-identical between this repository and `koras-control-plane` by hand.
Changing it here without its consumer would leave the two out of step across a
phase boundary, so the contract changes once, with the console that calls it.

**`e2e/language.spec.ts` did not need changing.** The response shape is
unchanged -- `locale` and `member_locale`, null when nobody chose -- because
`auto` maps back to null. The storage moved and the browser cannot tell, which
is the outcome that made the migration safe to take in one step.

Exit, met: 46 unit tests pass in a generated product, covering the eight routes,
the three refusals, the audit rows and the locale move; ruff and mypy `--strict`
clean; the structural suite pins the router outside every capability gate.

### Phase 5 — provider  *(done 2026-09-19)*

`fetchEffectiveSettings` in `packages/api-client`, `lib/settings.ts` wrapped in
React `cache()` and never throwing, and `SettingsProvider` / `useSettings` /
`useSetting` / `useSettingValue` in `packages/ui`, loaded once in the dashboard
layout beside the context and the locale.

**`useSettingValue` takes the fallback rather than knowing it.** A shared
component has to work outside a provider and while the API is unreachable, so
it needs a value it can name — and making the caller pass one keeps the
foundation's defaults in `koras_settings` rather than mirrored into a second
table in TypeScript that would drift. The one number the grid needs is a
constant in the grid, pinned to the catalogue by a test in Phase 6.

**`packages/ui` has no test runner**, so the decision that is easy to get
subtly wrong — which value a component actually uses — lives in a pure module,
`settings/value.ts`, and the starter's own suite imports and executes it. That
needed one line of vitest configuration, because a template package's
`tsconfig.json` extends a file that exists only after the two template layers
are merged.

Exit, met: one API call per navigation, asserted from the layout; a component
outside the provider, or given a value of the wrong shape, uses its own
fallback; `false` and `0` survive, which a `||` would not.

### Phase 6 — grid

`KorasDataTable`, exported from the UI barrel, with pagination, the ten grid
settings, and the explicit-prop override.

Exit: component tests for default 50, organisation value, user value, and
explicit prop beating all three; accessibility checks on the pager.

### Phase 7 — product UI

`/dashboard/settings` gains the category-grouped organisation settings with
current value, platform default, modified-or-default status and reset.
`/dashboard/preferences` is new — a nav module, a permission-free page, and the
reset-to-organisation control.

Exit: e2e over both, at 375 and 1440, with the console clean.

### Phase 8 — contract and Control Plane

Contract: three routes, byte-identical in both repositories.
Control Plane: migration 00045 (and both tables added to the expected-tables set
in `tests/rls/test_rls_coverage.py`), a settings router, one `AREA_ROLES` key,
three pages, and pagination on its `DataTable`.

Exit: the contract test asserts the field names, not only the route list — the
convention that repository adopted in its own commit history.

### Phase 9 — the shop

Synced by the method that worked on 2026-09-15 and again on 2026-09-16:
generate a product from the starter as it was **before** the change and as it is
**after**, and compare both against the repository, so a file the shop wrote
itself cannot be silently reverted.

The shop also gains one list page over `shop_products` — it has four shop tables
and no page that lists any of them, so section 20's page-size scenario has no
surface to run against without one. That page is shop-specific and stays in the
shop.

### Phase 10 — hardening

Full run in all three: lint, typecheck, test, build, RLS suite, generator
integration (both profiles, the with/without rows, the capability-leak
detector), Playwright.

### Phase 11 — documentation

`docs/SETTINGS_ARCHITECTURE.md` at the top level (the estate's convention for
"how a subsystem works"), `docs/adr/0007-koras-settings-framework.md`, the
developer guide's *How to add a new setting*, `manual-test-plan.md` in this
directory, `PROFILE_SYNC_MATRIX.md` extended, `STATUS.md` extended, and
`CLAUDE.md` updated.

---

## Sync matrix

Legend: **S** the starter owns it; **P** reaches the product by template; **CP**
Control Plane work in that repository; — nothing owed.

| Capability | Starter | Product | Control Plane | Shop |
|------------|---------|---------|---------------|------|
| Setting definitions | **S** `koras-settings` | consumes | reads over the contract | consumes, may add its own |
| Settings catalogue | **S** `settings_catalogue/standard.py` | **P** | reads over the contract | **P**, plus its own in `product.py` |
| Registry and validation | **S** | consumes | — | consumes |
| Value tables and RLS | **S** migrations | receives | **CP** its own two tables | receives |
| Resolver | **S** | consumes | **CP** its own | consumes |
| Snapshot at provisioning | **S** in tenant creation | runs it | triggers it by calling the contract | validates it |
| Global defaults | code default only | code default only | **CP owns the values** | — |
| Effective settings API | **S** | serves | **CP** its own | serves |
| `SettingsProvider` / hooks | **S** | consumes | **CP** parallel implementation | consumes |
| `KorasDataTable` | **S** | consumes | **never receives it** — its own table gains paging | consumes |
| Organisation Settings UI | **S** | **P** | — | **P** |
| My Preferences UI | **S** | **P** | — | **P** |
| Global Settings UI | — | — | **CP** | — |
| Setting Definitions UI | — | — | **CP**, read-only | — |
| Change History UI | — | — | **CP** | — |
| Audit actions | **S** registry | records | **CP** its own literals | records |
| Contract routes | **S** owns the file | serves them | calls them | serves them |

The single line to remember: **nothing flows from the starter into the Control
Plane but `contracts/product-platform.v1.json`.** Every Control Plane row above
is work done in that repository against that contract.

---

## Test plan

The brief's section 21 lists eighteen mandatory scenarios. Each maps to a named
home.

| # | Scenario | Where |
|---|----------|-------|
| 1 | Global default resolution | `koras-settings/tests/test_resolver.py` |
| 2 | Organisation snapshot created | `tests/unit/test_settings_snapshot.py` |
| 3 | Organisation override | resolver suite |
| 4 | User override | resolver suite |
| 5 | User reset | API suite |
| 6 | Organisation reset copies the current global | API suite |
| 7 | Existing organisation unaffected by a later global change | `tests/unit/test_settings_snapshot.py` — the scenario the feature exists for |
| 8 | New organisation receives the latest global | same file |
| 9 | A person cannot override a two-level setting | `koras-settings/tests/test_scopes.py` **and** the API suite |
| 10 | An organisation cannot modify a global-only setting | same |
| 11 | Invalid values rejected | `koras-settings/tests/test_coercion.py` |
| 12 | Audit event created | `tests/unit/test_settings_audit.py` |
| 13 | Unauthorised update rejected | `tests/unit/test_settings_rbac.py` |
| 14 | Grid defaults to 50 | component test |
| 15 | Grid respects the organisation value | component test |
| 16 | Grid respects the person's value | component test |
| 17 | Explicit prop overrides the resolved setting | component test |
| 18 | Cache invalidation | not applicable — no cache is built; a test asserting the version bumps stands in its place |

Beyond the list, three things the estate's own conventions require and the brief
does not mention:

- **Cross-tenant isolation**, three numbered SQL suites, each asserting that a
  cross-tenant write raises with an exact message string.
- **Cross-member isolation** for `member_settings` — one member must not read
  another's row inside the same tenant. This is the property
  `160_member_preferences_isolation.sql` already asserts for locale.
- **No capability leak** — the settings framework is foundation, so
  `generation.test.ts`'s leak detector must still pass for a product generated
  `--without admin,worker,reporting,audit_governance,storage_governance`.

Structural tests to add in `generators/create-koras-app/tests/`:

- the TypeScript key union matches the Python catalogue;
- every `label_key` and `description_key` exists in all three i18n catalogues;
- every grid setting the component reads exists in the catalogue;
- the settings migrations are **not** listed under any capability in
  `template_map`.

---

## Risks

| Risk | Handling |
|------|----------|
| The locale migration (`00030`) moves live data in a deployed product | Backfill and drop in one migration, with the isolation suite and the e2e spec changed in the same commit; rehearsed against the shop's dev database before the starter's template is called done |
| The contract's first platform write route | Gated behind ADR 0007, written before the route; the route can reach global values only, and accepts no tenant |
| Three repositories drifting | The three-way generate-and-compare sync method, plus `shared-template-parity.test.ts` on the contract |
| A settings surface accidentally gated by a capability | An explicit structural test asserting no settings path appears under `template_map.capabilities` |
| Two catalogues drifting | There is only one. The TypeScript side is a key union with a text-comparison test |
