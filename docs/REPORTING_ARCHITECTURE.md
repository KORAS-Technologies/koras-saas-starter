# Reporting & Analytics — one registry, three levels, every report server-authorized

> Scope: the reusable reporting framework in `koras-saas-starter`, the
> platform analytics it lets `koras-control-plane` build, and the way a
> generated product such as `koras-e2e-shop` registers its own reports.
> Designed 2026-09-14 after the discovery recorded in the first section;
> `docs/adr/0002-koras-reporting-framework.md` is the decision record and
> `docs/FOLLOW_UPS.md` F25 is what this deliberately leaves out.

**Status.** Built in the templates on 2026-09-14 as the product capability
`reporting`, on by default. Generator Integration builds a product with it
and runs the Python, Node, RLS and browser suites. Platform analytics is
built in `koras-control-plane` against the same package. The sample shop
reports are registered in `koras-e2e-shop` through the extension point.

## Purpose

Three audiences ask three different questions of the same estate, and until
now nothing answered any of them:

| Level | Audience | Asks | Lives in |
|-------|----------|------|----------|
| 1 — Platform | KORAS staff | how is the business and the estate doing | `koras-control-plane` |
| 2 — Tenant | a customer's administrators and members | what is my organization doing in this product | every generated product |
| 3 — Product | the same people | what is happening in my domain (orders, cases, appointments) | the product's own repository |

One framework serves all three. It is a registry of metrics and reports, a
resolver that runs each report's query under the caller's trusted context,
an authorization rule that decides before any query runs, and a small set of
components that render whatever the registry answered. The framework knows
nothing of orders or cases; a product teaches it by registering definitions,
never by editing it.

## What existed before

- **Two placeholder modules.** `reports` locked on `advanced_reporting` and
  `insights` hidden on `insights`, each a heading and a sentence, shipped to
  demonstrate the lock and hide behaviours of the navigation registry.
- **One roll-up query.** `usage_days_since` in the product's `core/ai.py`,
  aggregating `ai_usage_events` per tenant and day for the platform's
  collector; and the month and model aggregates in the Control Plane's
  AI usage repository, the only time series in either API.
- **No data-display primitives in a product.** `packages/ui` ships a card, a
  container, buttons, fields and an icon set. The Control Plane console has
  `DataTable`, `StatCard`, `StatGrid`, `Panel` and the state components.
- **No chart library in any repository.**
- **No money stored anywhere.** Plans hold Stripe price references; amounts
  live in Stripe and in the raw payloads of `billing_events`.
- **No general audit table in a product.** `ai_audit_events` is the one
  durable sink; `koras_audit` names the shape and a logging sink.
- **No shop domain in `koras-e2e-shop`.** It is the product template,
  rendered, plus infrastructure.

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ apps/web  (product)                     apps/admin  (Control Plane console)  │
│  dashboard/analytics/            ◀──▶    analytics/                          │
│   the list, one page per report          the executive dashboard and one     │
│   filters in the URL                     page per platform report            │
│  api/reports/[key]/export                                                    │
│   the CSV proxy, the token stays here                                        │
│ packages/ui/src/reporting        ◀──▶    components/ui (DataTable, StatCard) │
│   MetricCard · MetricGrid · ReportChart · ReportTable · ReportFilters …       │
└──────────────────────────────────────────────────────────────────────────────┘
                 │ packages/api-client                     │ PlatformApiClient
                 ▼                                        ▼
┌──────────────────────────────────────┐   ┌──────────────────────────────────┐
│ services/api (product)               │   │ services/api (Control Plane)     │
│  routers/reporting.py                │   │  routers/analytics.py            │
│   GET /api/v1/reports                │   │   GET /api/platform/v1/analytics │
│   GET /api/v1/reports/{key}          │   │       /reports[/{key}[/data]]    │
│   GET /api/v1/reports/{key}/data     │   │  repositories/analytics.py       │
│   GET /api/v1/reports/{key}/export   │   │   the platform's resolvers       │
│   GET /api/v1/metrics/{key}          │   │  reporting/  the platform's       │
│  core/reporting.py                   │   │              catalogue           │
│   TenantDep + AuthDep ─▶ permissions │   └──────────────────────────────────┘
│   entitlements ─▶ ReportingGrant     │                   │
│   DbSession (RLS forced)             │                   │
│  reporting/  the extension point:    │                   │
│   standard.py  the six tenant reports│                   │
│   reports.py   the product's own     │                   │
└──────────────────┬───────────────────┘                   │
                   │ koras_reporting (python-packages/koras-reporting, shared)
                   ▼                                       ▼
        MetricDefinition · ReportDefinition · FilterDefinition · Visibility
        ReportRegistry · MetricRegistry · resolve_filters · visibility_for · to_csv
```

`koras_reporting` is the framework: definitions, registries, filter parsing,
the authorization rule, the result shape and the CSV writer. It runs no
query and imports no database driver. Both profile templates receive it from
`profiles/_shared/template/python-packages/koras-reporting`, which is how the
Control Plane and every product describe a report with the same types.

## Data flow

A person opens a report page. The page, a server component, calls a server
action; the action re-establishes who is calling through `signedInContext`,
checks `reports.read`, and calls the product's API with the caller's own
token and the filters the URL carried. The API's dependency in
`core/reporting.py` resolves the tenant and the caller the way every route
does, reads the plan from the platform, and builds a `ReportContext` from
the verified token and nothing from the request. The router looks the report
up in the registry, decides visibility from the caller's permissions and the
grant, parses the filters against the report's declared filters, and only
then calls the resolver with the tenant session, on which row-level security
is forced. The resolver answers a `ReportResult`: metric values, series,
rows, and notes saying which figures are estimates. The page renders it with
the reporting components; the browser receives the answer and never the
token, the API's address or a query.

An export is the same path through a route handler instead of an action,
because a download is a response body rather than a value, with the format
gated by `reporting.export` and the caller's `reports.export`, and the fact
of the export recorded in `audit_events`.

## Tenant isolation

Every product resolver runs on `DbSession`, the request's tenant session,
under policies that are enabled and forced on every tenant table. A
resolver that forgot to filter by tenant would still see one tenant's rows,
because the policy filters for it. The resolver is nevertheless written with
the tenant id bound as a parameter, so a resolver copied into a test with no
database still says what it reads. Nothing in the request names a tenant: the
context is built from the token, the way `core/tenant.py` builds it for every
route.

A platform resolver in the Control Plane runs on the platform's own session
as the staff member who asked, under the actor declaration the platform's
role dependency makes; cross-tenant is the point of Level 1, and the caller's role is what
admits it.

## Security model

The same layers the shell standard names, applied to reports:

| Layer | Enforcement |
|-------|-------------|
| Sidebar | `resolveNavigation` hides or locks the `analytics` module |
| Route | `middleware.ts` refuses the path on `reports.read` |
| Page | `signedInContext` plus `can(context, 'reports.read')`, and the entitlement |
| Server action | the same check, before any call |
| API | `require_auth`, `require_tenant`, then `visibility_for` per report |
| Data | RLS, forced, scoped by the trusted tenant context |

Filters cannot reach a query as text. `resolve_filters` accepts only the
keys the report declared, coerces each to its declared kind (a date range, a
choice from a declared option list, a bounded integer), refuses anything
else with 422, and hands the resolver typed values it binds as parameters.
There is no free-text filter kind. A date range is bounded to 366 days and
defaults to the last thirty, so a report cannot be asked to scan a table
without limit.

Exports are bounded to `EXPORT_ROW_LIMIT` rows; a larger export is refused
with a sentence saying to narrow the range, and the asynchronous export is a
follow-up rather than a silent truncation.

## RBAC

Three permissions, added to the closed catalogue in `packages/permissions`
and mirrored in `python-packages/koras-auth`:

```text
reports.read       may open Analytics and every report whose definition names it
reports.sensitive  may open reports about people: Users, Activity
reports.export     may download a report
```

| Organization role | Reporting permissions |
|-------------------|-----------------------|
| `organization_owner`, `organization_admin` | all three |
| `security_admin` | `reports.read`, `reports.sensitive` |
| `billing_admin` | `reports.read`, `reports.export` |
| `member` | `reports.read` |

No new role. A report viewer is a member; a report that should not reach
members names `reports.sensitive`. A product that needs a finer cut adds a
permission to the catalogue, in its own repository, the way every module
does.

## Entitlements

Five, in the Control Plane's commercial catalogue, dotted like `ai.*` and
`storage.files`:

```text
reporting.basic      Analytics at all: Overview, Usage, Subscription      Starter and above
reporting.export     CSV download                                          Pro and above
reporting.advanced   the reports that name it: Users, Activity, AI Usage, Business and above
                     and any product report declared advanced
reporting.scheduled  scheduled delivery — scaffolded, not delivered        Business and above
reporting.api        the reports API called by something other than the   Enterprise
                     product's own web tier — declared, not yet enforced
```

The product reads them the way it reads every entitlement, through the
portal route with the customer's token, into `ReportingGrant` in
`core/reporting.py`. An unresolved plan follows the Files rule rather than
the assistant's: the product answers with its basic reports and the page
says the plan could not be read, because a report over the customer's own
data is not something an outage should hide, and nothing is spent by
showing it. `reporting.export` is the exception and is refused when
unresolved: a download leaves the product.

The old placeholder codes `advanced_reporting` and `insights` are gone from
the registry. `insights` stays as the hidden-module example; `advanced_reporting`
survives only as a fixture string in the entitlement parser's test.

## Report registry

A `ReportDefinition` in `python-packages/koras-reporting/src/koras_reporting/definitions.py`:

```text
key                   dotted, unique: usage.overview, shop.orders_by_status
name, description     shown as given; a product translates in its own page if it wants
category              overview · usage · people · billing · ai · activity · product
permission            the product permission that opens it
entitlement           the platform entitlement that includes it, or None for always
metrics               the metric keys it reports; every one must be registered
dimensions            the dimensions its series and rows may be grouped by
filters               the FilterDefinitions it accepts; anything else is refused
resolver              the coroutine that answers it, given a ReportContext and filters
default_visualization one of kpi · line · bar · table
visualizations        which of those the page may offer
export_formats        csv today; xlsx and pdf are declared kinds with no writer
cache_seconds         how long a page may reuse an answer; 0 for never
status                available · preview · deprecated
version               an integer a product bumps when the shape changes
capability            the generated capability the report's data needs, or None
```

`ReportRegistry.register` refuses a duplicate key, a metric nobody
registered, a filter kind the framework does not know, and a default
visualization not in the offered set. The registry is built once at import
by `services/api/koras_api/reporting/__init__.py`, which is also where the
product's own definitions are added — the extension point, mirroring
`koras_api/ai/__init__.py`.

## Metric registry

A `MetricDefinition`:

```text
key           snake case: active_users, ai_requests, storage_used_bytes
name, description
unit          count · bytes · micros · milliseconds · percent · seconds
format        integer · bytes · money · duration · percent
aggregation   sum · count · average · max · latest
dimensions    what it may be broken down by
scope         tenant · platform
```

A metric is a name with a unit and a meaning. The resolver that computes
it lives with the report; the definition is what lets two reports say
`ai_requests` and mean the same thing, what a metric card formats against,
and what a future BI export lists. A metric's calculation is never in a
React component: the API answers numbers, the component formats them.

## Product report extensions

`services/api/koras_api/reporting/reports.py` is generated with one
sentence and an empty list, and a product fills it:

```python
from koras_reporting import FilterDefinition, MetricDefinition, ReportDefinition

METRICS = [MetricDefinition(key="orders_total", ...)]
REPORTS = [ReportDefinition(key="shop.orders_by_status", resolver=orders_by_status, ...)]
```

Nothing else changes: the router lists whatever the registry holds, the
page renders whatever the definition declares, the sidebar has one entry
for all of them. `koras-e2e-shop` is the proof: its shop domain and its
seven reports are in files the starter never ships.

## AI telemetry

`ai_usage_events` already carries every dimension the assistant's meter
records: tenant, user, agent, alias, provider, model, tokens, latency,
status, error code, list-price cost and the overage columns. The AI Usage
report reads it and adds nothing to it; the platform's collector keeps
pulling the daily aggregate through `platform_ai.py` into its daily aggregate table.
No content is ever in a usage row, so no report can expose a prompt.

## Usage metering

Three kinds of usage are kept apart:

| Kind | Source | Owner |
|------|--------|-------|
| operational | counts over the product's own tables: members, files, AI calls | the product's resolvers |
| billing | what the platform charges: the allowance, the overage, seats | the Control Plane, read as entitlements and the AI status |
| analytics | the two above, presented over time | this framework |

The Usage report shows used, included, remaining and percentage for every
quota the plan names and the product can measure: seats against
`tenant_members`, storage against `files`, AI requests against
`ai_usage_events`. It never invents a limit: an entitlement with no
`limit_value` is unlimited and says so.

## Caching

A report declares `cache_seconds`; the page honours it with React's `cache`
within one render and nothing longer, because the answers are per tenant
and the product's API is the only cache key that is safe. The Control Plane
reads billing prices through a ten-minute in-process cache that already
exists. Pre-aggregation is a follow-up: the volumes today are one product
and one tenant, and every resolver runs an indexed query bounded by a
date range.

## Export strategy

Three formats, one renderer. `render(result, format, title)` in the
package's `export.py` answers CSV, XLSX or PDF as bytes with a media type:
CSV through the standard library's writer with a leading apostrophe on any
cell that begins with a formula character, XLSX through `openpyxl` with the
same escaping, PDF through `fpdf2` as a landscape table with the report's
title and range. A definition's `export_formats` defaults to all three; a
report that should not be a PDF says so.

An export is decided once, in the router: the export permission, the
export entitlement, a resolved plan, a format the report offers. Up to
`EXPORT_ROW_LIMIT` rows it is rendered and streamed. Past the bound, or
when the caller asks with `background=1`, the router inserts a row in
`report_exports`, answers 202 with the export's id, and writes the file
after the response into the tenant's bucket at
`tenants/<tenant>/exports/<id>/<filename>` through the storage module's
`put`. The Exports list on the report page shows each export's state and
mints a five-minute download URL for a ready one, the way Files does.
Exports are retired on the way to listing, once older than
`REPORT_EXPORT_RETENTION_DAYS` (seven unless set): the object first, then
the row. The route handler in `apps/web/src/app/api/reports/[key]/export/`
streams a foreground export and redirects a queued one back to the page
with a notice.

## Scheduled reporting

A schedule is a tenant-scoped row in `report_schedules` -- the report, a
cadence of daily, weekly or monthly, a format, up to ten recipients, and
the report's declared filters other than the period. Creating one takes
the export permission, the export entitlement and `reporting.scheduled`,
and validates at creation everything the worker later trusts: the report
exists and is open to the caller, the format is one it offers, the
filters are ones it declared, the addresses are shaped like addresses.
Removing one takes the permission alone, so a customer whose plan lapsed
can still stop what it sends.

The worker's `deliver_scheduled_reports` runs hourly. On the provisioning
context it reads the schedules that are due; for each it binds the
tenant's `app.tenant_id` for one transaction, resolves the report through
the product's own catalogue for the period the cadence names -- yesterday,
the last seven days, the previous calendar month, never today -- renders
it, mails it to each recipient as an attachment through `koras_email`,
records `report.delivered` in the tenant's audit table, and records the
run and the next due time on the schedule. A schedule that fails keeps its
error and its next time. The catalogue reaches the worker by name: the
worker image carries the API's `koras_api/reporting` package and nothing
else of the API, and imports it through `importlib` so the dependency
check does not read it as an undeclared dependency on the API.

The plan at delivery time is the one the platform last told the product
of. The worker holds no customer token to resolve it live and the product
holds no identity toward the platform to ask, so the direction the estate
already allows is used: the Control Plane's worker resolves each
organization's effective entitlements for the product hourly and writes
them through the private contract, `PUT /internal/platform/v1/tenants/{id}/plan`,
into `tenant_plans` (migration `00015_tenant_plans.sql`), one row per
tenant, replaced on every sync. Before rendering, the worker reads that row
as the tenant and asks it the three gates creating the schedule asked --
`reporting.scheduled`, `reporting.export`, and the report's own entitlement
-- and a schedule the plan no longer covers is paused: no mail, the reason
on the schedule's `last_error`, the next time set, so it resumes by itself
if the plan does. A tenant the platform has never synced delivers as an
unresolved customer would, which is the basic reports. Every page still
resolves the plan live; the snapshot stands in only where nobody is signed
in.

## Audit

`audit_events`, a general tenant-scoped table added by migration
`00013_audit_events.sql`, is the second implementation of `AuditSink`.
`SqlAuditSink` in `core/reporting.py` writes to it; the reporting router
records `report.exported` for every export, `report.export_failed` when a
background write fails, `report.scheduled` and `report.schedule_removed`,
and `report.viewed` for every sensitive report, with the report key and
the range and never the rows; the worker records `report.delivered`. The
Activity report reads `audit_events` and `ai_audit_events` together. Rows
are insert-only for a tenant, swept by the worker after
`AUDIT_RETENTION_DAYS`.

The same table is what the platform collects. `routers/platform_reporting.py`
answers `GET /internal/platform/v1/activity?since=` on the private contract
with events and distinct actors per tenant, day, action and outcome for up
to 92 days -- counts only, no actor ids, targets or details -- and the
Control Plane's hourly collector keeps them in its daily activity table,
attributed to the organization each tenant belongs to, for its Usage &
Adoption report.

## Control Plane integration

The Control Plane carries `koras-reporting` as a workspace package and
registers its platform reports in `services/api/koras_api/reporting/`
against the same definitions. Its analytics router serves the catalogue
and each report's data at `/api/platform/v1/analytics`, each report gated
by the platform role its definition names through the existing
`PlatformReadDep`, `PlatformBillingDep` and `PlatformAdminDep`. The console
gains an Analytics area with an executive dashboard and one page per
report, built from `StatGrid`, `DataTable` and `Panel`.

Revenue is the one place the framework has to say what a number is:

| Figure | Kind | How |
|--------|------|-----|
| subscriptions by status, plan, product | actual | `subscriptions` |
| MRR, ARR, MRR by plan and product | derived | live subscriptions × the price the plan's Stripe price id resolves to × seats, annual divided by twelve |
| invoiced revenue | actual | `invoice.paid` payloads in `billing_events` |
| trial-to-paid conversion | actual | subscriptions that were `trialing` and are `active` |
| churned MRR | derived | subscriptions cancelled in the range, at their last derived MRR |

Every derived figure carries a note saying so, and a figure whose source is
unreachable is reported as unavailable rather than zero. No amount is
stored: `docs/BILLING_DESIGN.md` argued against a second copy of money and
this does not overrule it.

## Generated product integration

`reporting` is a product capability, on by default in `defaults.yaml`
because it needs no external service. `--without reporting` removes the
router, the extension point, the pages, the migration, the tests and the
module, and the leak test in `generation.test.ts` asserts that. The
navigation module is `analytics`, at `/dashboard/analytics`, gated on
`reports.read`, `reporting.basic` and the capability, locked when the plan
lacks it.

## Testing

| What | Where |
|------|-------|
| registry refusals, filter parsing, visibility, CSV escaping | `python-packages/koras-reporting/tests/` |
| the six standard resolvers against a stubbed session | `tests/unit/test_reporting_standard.py` |
| the router: list, definition, data, export, refusals, audit | `tests/unit/test_reporting_api.py` |
| the three formats, background exports, schedules and their refusals | `tests/unit/test_reporting_schedules.py` |
| delivery: the period, the tenant binding, the attachment, the recorded run | `tests/unit/test_reporting_delivery.py` |
| the activity contract's shape and window | `tests/unit/test_platform_activity.py` |
| the audit table's isolation and insert-only rule | `supabase/tests/110_audit_isolation.sql` |
| the schedules and exports tables' isolation | `supabase/tests/130_report_schedules_isolation.sql` |
| the names the sides share, the gated paths, the workflow | `generators/create-koras-app/tests/product-reporting.test.ts` |
| the module, the locked state, the pages with no API | `e2e/analytics.spec.ts` |
| platform reports and their role gates | the Control Plane's analytics integration test |
| the shop's registration through the extension point | the shop's own unit test for its reports |

## Observability

Every report resolution is a span named `report.resolve` with the report
key and the range as attributes, under the API's existing telemetry; a
resolver that takes longer than a second logs at warning with the key. No
row and no filter value is in a span.

## Future BI integration

The metric registry is the contract a BI tool would read: keys, units,
dimensions and scope, listable at `/api/v1/metrics`. `reporting.api` is the
entitlement that would admit a machine caller; today every call carries a
person's token. A warehouse export would be the daily aggregate per metric
and dimension, the shape the platform's AI usage table already has for one
metric.
