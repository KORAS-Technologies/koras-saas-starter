# AI Foundation Assessment — what the starter already has, and what a shared AI layer needs

> Scope: `koras-saas-starter` only. This document is the Phase 0 deliverable of
> the Koras AI Foundation work: a reading of the repository as it stood on
> 2026-09-13, before any AI code was written. It records what exists, what can
> be reused, where the request conflicts with decisions already made, and the
> least disruptive design that fits. `docs/AI_FOUNDATION_PLAN.md` turns the
> recommendation into phases; `docs/AI_ARCHITECTURE.md` describes what was then
> built. Nothing here changes `koras-control-plane` or any generated product.

**Status.** Written 2026-09-13 from the code and every document in `docs/`, the
Claude skills under `.claude/skills/`, and the product profile overlay. Where
this document names a file, the file exists and `tests/docs/file-references.test.ts`
checks it. Where it names a decision, the decision is quoted from the file that
made it.

## 1. What this repository is, for this purpose

The starter's root `apps/`, `packages/` and `services/` directories are empty.
Everything a product receives lives in two template layers,
`profiles/_shared/template/` and `profiles/product/template/`, rendered by
`generators/create-koras-app` through Handlebars and filtered by the profile's
`template_map`. An AI foundation for generated products is therefore template
files in the product profile, generator changes where the manifest has to
express a new component, structural tests in `generators/create-koras-app/tests/`
that read those templates, and documents here. There is no runtime in this
repository to run the foundation against; Generator Integration builds a product
from the templates and runs its suites, and that is where the foundation is
exercised.

## 2. Existing architecture

### 2.1 Authentication and identity

A product API verifies ZITADEL tokens in `python-packages/koras-auth/src/koras_auth/__init__.py`:
`verify_token` checks signature, audience and issuer, and returns `JWTClaims`
with `sub`, `email`, `roles` (a frozenset of `OrganizationRole`), `organization_id`
and `used_mfa`. `services/api/koras_api/core/auth.py` wraps it as `AuthDep`.
A verified caller lacking authority is 403; an unverifiable one is 401, and
the two are never collapsed.

The web tier holds a session cookie the application signed itself and the
provider's own token beside it. `apps/web/src/lib/session.ts` reads the session
into `MemberSession`; `providerToken` returns the ZITADEL token that every call
to the product's API and to the Control Plane's portal carries. A product holds
no machine credential at runtime; the argument is in `apps/web/src/lib/entitlements.ts`
and FOLLOW_UPS F2b.

### 2.2 Tenant resolution and context

`python-packages/koras-tenant/src/koras_tenant/__init__.py` resolves the tenant
that a verified organization owns with a real query under an organization-keyed
policy, returning `TenantContext` with `id`, `slug`, `name` and `organization_id`.
`services/api/koras_api/core/tenant.py` wraps it as `TenantDep`. The tenant is
never read from a path, header or body: there is nowhere in a request to put one.

Row-level security is transaction-local. `python-packages/koras-database/src/koras_database/__init__.py`
refuses to open a transaction that has not declared who it is for, and
`services/api/koras_api/core/database.py` supplies `DbSession`, a session
declared as one tenant, and `PlatformSession`, the provisioning session that
one machine-only router uses. Every tenant table carries `tenant_id`, enables
and forces RLS, and has a policy per verb scoped on `current_tenant_id()`.
`supabase/tests/050_files_isolation.sql` is the shape of a negative isolation test.

There is no workspace or sub-tenant concept anywhere in the product. The prompt's
optional workspace field on an AI context has nothing to map to today.

### 2.3 Roles, permissions and access

Organization roles are a closed set in two places that cannot import each
other: `OrganizationRole` in `python-packages/koras-platform/src/koras_platform/roles.py`
and `ORGANIZATION_ROLES` in `packages/permissions/src/index.ts`. Product
permissions exist only on the TypeScript side: `PRODUCT_PERMISSIONS` and the
role-to-permission map `ROLE_PERMISSIONS`, both closed, both typed so a typo
fails to compile. `productAccessFromOrganizationRoles` is the one function that
turns roles into product access and is the seam a per-product assignment store
would replace.

The API mirrors the mapping by role rather than importing it. In
`services/api/koras_api/routers/files.py` deletion is refused unless the caller
holds an owner or admin role, and `generators/create-koras-app/tests/product-files.test.ts`
asserts the two sides agree. There is no Python permission catalogue; a
server-side check is written against roles today.

### 2.4 Entitlements and plans

Product → plan → entitlement → subscription → organization is Control Plane
state. A product reads the resolved set from the portal route
`/api/portal/v1/products/{code}/entitlements` with the customer's own token.
On the web tier `parseEntitlements` in `packages/branding/src/index.ts` turns
the wire shape (`plan_code`, rows of `code`, `enabled`, `limit_value`) into an
`EntitlementSet`, and `isEntitled` answers a gate; an unresolved set entitles
nothing. On the API `services/api/koras_api/core/platform.py` reads the same
route through `read_portal`, cached for a minute per organization, and
`services/api/koras_api/core/storage.py` turns the row for `storage.files`
into a grant with a ceiling.

Entitlement keys are dotted where the API enforces them (`storage.files`) and
declared once on each side, with a starter test keeping the names level. A
commercial refusal is 402 and names the plan; an authorization refusal is 403
and names nothing. A provider a product cannot serve is 503 with the reason.

The failure direction differs by read and each is argued in its file: an
unresolved entitlement set on the web is not entitled; an unreachable platform
for storage is no gate; and the existing AI routing helper fails closed on both
no policy and no answer, because "an AI capability has no platform default, on
purpose".

### 2.5 Subscriptions and billing

Read-only from the product. The shell renders the subscription state as a
sentence and decides nothing from it. `packages/billing/src/index.ts` is empty
and `docs/BILLING_DESIGN.md` says it may be removed. Usage-based pricing is
explicitly out of that design's scope until a customer asks.

### 2.6 API clients and service patterns

`packages/api-client/src/index.ts` is the one place a JSON call is made from
the web tier: base URL, bearer token, timeout, `ApiError` with a status, and
`cache: 'no-store'`. It is free of React and of the branding package. Every
function names which API it reads and none takes an organization identifier.

A feature on the API is a router module under `services/api/koras_api/routers/`,
mounted in `services/api/koras_api/main.py` behind the authenticated rate
limiter, with pydantic request models that forbid extra fields, SQL text
statements rather than an ORM, and dependencies assembled in `core/`. The
Files module is the reference and `docs/PRODUCT_APP_SHELL.md` names it as such.

### 2.7 Background jobs

`services/worker/koras_worker/worker.py` is an arq worker with one placeholder
task, polling every five seconds. The scheduler is optional. Neither carries
tenant context into a job today; `koras-multitenancy` requires that any job
that touches tenant data does.

### 2.8 UI packages and the product shell

`packages/ui/src/index.ts` is the design system: primitives (`Button`, `Card`,
`Container`, `TextField`, `SelectField`, `SubmitButton`, `Icon`), the brand
scope, the marketing sections, the auth frame and the authenticated shell.
The shell renders a decision it did not make; the navigation registry in
`packages/branding/src/index.ts` is resolved on the server against permissions,
capabilities, entitlements and features, and `apps/web/src/middleware.ts` gates
the URL from the same registry. The header has a `headerActions` slot that is
empty in every generated product, on purpose. The small-screen drawer in
`packages/ui/src/shell/product-shell.tsx` is a hand-written dialog with a
focus trap, Escape and focus return; there is no dialog or sheet primitive
to reuse, and no third-party component library.

Components that import the branding package are `.hbs` templates, which
forbids an inline object literal in a JSX prop. Colours are tokens; a hex
literal in `packages/ui` fails a starter test. Labels reach client components
either through `createTranslator(locale)` or as already-translated props, the
way `FilesPanel` takes its labels.

### 2.9 Observability and logging

`services/api/koras_api/core/observability.py` installs OpenTelemetry tracing
for FastAPI. `python-packages/koras-logging/src/koras_logging/__init__.py` and
`python-packages/koras-observability/src/koras_observability/__init__.py` are
one-line stubs. Logging is the standard library, structured by the log line's
own arguments, and never carries a token or a key.

### 2.10 Audit

`python-packages/koras-audit/src/koras_audit/__init__.py` and
`packages/audit/src/index.ts` are one-line stubs. No audit table exists in any
product migration. `docs/DEPENDENCY_MAP.md` already assigns "AI request/response
audit" to `koras-audit`, which is the closest thing to a decision.

### 2.11 Database access

Five product migrations, `supabase/migrations/00001_initial.sql` through
`supabase/migrations/00005_files.sql`; policies live in numbered migrations and
never in `supabase/policies/`. The isolation suite under `supabase/tests/` runs
in Generator Integration as a role RLS applies to, and the job then removes
`force` and requires the suite to fail. No vector extension, no embeddings
table, no ORM models.

### 2.12 Feature configuration and the manifest

Three gates, kept apart: a capability is what the repository was generated
with (`profiles/product/manifest.yaml`, recorded in `.koras/project.yaml` under
`components`), an entitlement is what the plan sold, a feature is what the
tenant switched on in `tenant_settings.features`. A capability maps to exactly
one template subtree through `template_map`, which is how `packages/billing`
disappears under `--without billing`. The generated `productConfig.product.capabilities`
list is what `requiredCapabilities` on a module resolves against.

`.koras/project.yaml` is written by `generators/create-koras-app/src/generation/project-manifest.ts`,
carries `schema_version`, `project`, `generator` and `components`, and its schema
version is not to move without a migration design. It already records every
enabled capability and service, so a new component is recorded with no schema
change.

### 2.13 The generator

`generators/create-koras-app/src/generation/engine.ts` walks the shared layer
then the profile layer, renders `.hbs`, drops excluded subtrees, copies
`shared_assets` verbatim and appends the project manifest. Selections come from
`profiles/product/defaults.yaml` and `--with` / `--without`, validated in
`generators/create-koras-app/src/profiles/validator.ts`. Component names are
manifest keys; there is no dependency rule between components today, so
nothing stops `--with ai_gateway --without api` except the required flag on
`api`.

### 2.14 Control Plane communication

Two directions. The generator registers a product after `terraform apply`
through `generators/create-koras-app/src/registration/`. At runtime the product
reads the platform's portal routes with the customer's token: entitlements and
branding from the web tier, entitlements and the storage policy from the API,
and, since 2026-09-12, AI routing through `ai_routing` in
`services/api/koras_api/core/platform.py`, which nothing calls yet.

## 3. Existing reusable functionality

| Concern | Reuse | Where |
|---------|-------|-------|
| Caller identity | `AuthDep`, `JWTClaims` | `services/api/koras_api/core/auth.py` |
| Tenant context | `TenantDep`, `TenantContext`, `DbSession` | `services/api/koras_api/core/tenant.py`, `core/database.py` |
| RLS declaration guard | `declare`, `Tenant` | `koras_database`, `koras_tenant` |
| Platform reads with the customer's token | `read_portal`, `ai_routing`, `PortalAnswer` | `services/api/koras_api/core/platform.py` |
| Entitlement grant shape | the `_grant_from` pattern and 402 | `services/api/koras_api/core/storage.py`, `routers/files.py` |
| Web-tier entitlement gate | `isEntitled`, `EntitlementSet`, `signedInContext`, `can` | `packages/branding/src/index.ts`, `apps/web/src/lib/access.ts` |
| Permissions catalogue | `PRODUCT_PERMISSIONS`, `ROLE_PERMISSIONS` | `packages/permissions/src/index.ts` |
| Navigation and route gate | a module entry, `resolveNavigation`, `canOpenModule` | `packages/branding/src/index.ts`, `apps/web/src/middleware.ts` |
| Typed API client | `request`, `ApiError`, `RequestOptions` | `packages/api-client/src/index.ts` |
| Server actions pattern | `ActionResult`, `session`, `explain` | `apps/web/src/app/dashboard/files/actions.ts` |
| Design system | `Button`, `Card`, `Container`, `SubmitButton`, `Icon`, tokens | `packages/ui/src/primitives/`, `packages/ui/src/styles/tokens.css` |
| Focus-trapped overlay | the drawer in the shell | `packages/ui/src/shell/product-shell.tsx` |
| Translations | `createTranslator`, the catalogues | `packages/i18n/src/index.ts` |
| Rate limiting | `limit_authenticated`, tier 2 per subject | `services/api/koras_api/core/ratelimit.py` |
| Migration and isolation test shape | `00005_files.sql`, `050_files_isolation.sql` | `supabase/migrations/`, `supabase/tests/` |
| Structural test shape | `product-files.test.ts`, `product-shell.test.ts` | `generators/create-koras-app/tests/` |
| Settings declaration | `Settings`, `secrets.manifest` | `services/api/koras_api/core/settings.py`, `local/config/secrets.manifest` |
| Model provider boundary | the LiteLLM proxy | `services/ai-gateway/` |

## 4. Existing AI functionality

| Piece | Where | Classification |
|-------|-------|----------------|
| AI gateway service, optional component `ai_gateway`, off by default | `profiles/product/template/services/ai-gateway/` | **Reusable.** An OpenAI-compatible proxy holding the provider keys. It is the provider boundary; the foundation calls it and nothing else. |
| Gateway model list | `services/ai-gateway/litellm_config.yaml` | **Reusable, incomplete.** Two models named by provider model name. Aliases the product can depend on do not exist yet. |
| Gateway settings | `AI_GATEWAY_URL`, `LITELLM_MASTER_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` in `local/config/secrets.manifest` | **Reusable.** All gated on the service. The API's `Settings` has no AI field, so the API cannot reach the gateway today. |
| Local LiteLLM config | `local/ai/litellm.yml` | **Duplicate.** A second model list beside the service's own, differing by an Ollama entry. Not read by the generated service, whose dev command loads the service directory's file. |
| `koras-ai` Python package | `python-packages/koras-ai/src/koras_ai/__init__.py` | **Incomplete.** A one-line stub that declares `litellm` as a dependency, so every product installs LiteLLM into its API image for a package that does nothing. |
| AI routing read from the Control Plane | `ai_routing` in `services/api/koras_api/core/platform.py` | **Reusable, unused.** Per capability, ordered providers plus secret-free config, fail-closed. Zero callers. |
| Control Plane routing table and admin page | `koras-control-plane` | **Out of scope.** Per (organization, product, capability), providers are free text, no platform default. The contract this repository consumes. |
| Gateway README usage example | `services/ai-gateway/README.md` | **Deprecated by this work.** It shows a product calling the gateway directly with an OpenAI SDK, which puts the master key and the provider call in application code. |
| Agents, tools, prompts, approvals, usage, RAG | — | **Missing.** No prior art in any template or document; "agents" means Claude Code agents and "approval" means `terraform apply` everywhere they appear. |

## 5. Gaps

What the requested foundation needs and the repository does not have:

1. A typed provider abstraction in the product that reaches the gateway, so
   application code never holds `LITELLM_MASTER_KEY` or a provider model name.
2. Model aliases, with a product default catalogue and the Control Plane's
   per-customer routing layered above it.
3. An AI context assembled from `TenantDep` and `AuthDep` on the server, and a
   dependency that refuses when AI is disabled, unlicensed or unconfigured.
4. Entitlement keys for AI and a server-side gate that follows the 402 rule.
5. A conversation and message store, tenant-scoped and forced.
6. A usage record per operation. Nothing counts today, `koras_ratelimit` is
   documented as not for billing, and the gateway has no database by decision.
7. An audit trail for proposed, approved, rejected and executed actions.
8. Registries for agents and tools, a risk classification, and an approval
   state machine with server-side approve and reject routes.
9. A Python permission catalogue, so a tool's declared permission can be
   checked on the API rather than by role alone.
10. AI components in `packages/ui`, a page and a contextual drawer in
    `apps/web`, and the translations for them.
11. Prompt definitions with versions and variables.
12. Knowledge-source and retrieval contracts.
13. A generated extension point where a product defines its own agents, tools,
    prompts and knowledge sources.
14. A generation-time switch so a product without AI carries none of the
    router, the page, the migration or the tests.
15. Documentation, and the structural tests that keep names level across
    TypeScript, Python and SQL.

## 6. Conflicts

Each is a place where the request and a documented decision, or two documented
decisions, pull apart. The resolution chosen is stated with each.

**C1. Registries as tables versus registries as code.** The request describes
agent and tool registries; the shell design refuses a per-product grant store
because it "would mean new tables, a new API and a new authority the Control
Plane does not know about", and product metadata has one source. Resolution:
agents, tools, prompts and knowledge sources are code registries populated at
import time from a generated extension point, the way the navigation registry
is configuration in `packages/branding`. Only runtime state, which is
conversations, messages, actions and usage, gets tables.

**C2. Three failure directions for an unresolved platform read.** Unresolved
entitlements are not entitled on the web; an unreachable platform is no gate
for storage; the AI routing helper fails closed. Resolution: AI follows the
routing helper and fails closed when the platform is configured and does not
answer, because a model call costs money and routes customer data, and a
product without a Control Plane configured at all uses its own default
catalogue, which is the documented bootstrap order (R-001). The three
directions stay apart and this document says why.

**C3. Who counts usage.** The gateway README shows the product calling the
gateway directly, and nothing in that path has a database. Resolution: the
product stops calling the gateway from application code. Every model call goes
through the API's AI runtime, which is where the tenant, the token and the
database already are, and the usage row is written there. The README example
is replaced.

**C4. Three provider abstractions at three layers.** The gateway's model list,
the Control Plane's provider list per capability, and the requested provider
interface. Resolution: one adapter protocol in `koras_ai` with one gateway
implementation; the alias is what product code names; the Control Plane's
routing decides the ordered providers for an alias per customer; the gateway
model list is what a provider and alias resolve to. Nothing is named after a
provider, following the billing rule that a column is named for the role it
plays and not for the vendor that fills it.

**C5. Approvals by notification.** `packages/notifications` and
`packages/email` are empty and mail is sent server-side in Python only.
Resolution: approvals are in-product only, listed in the assistant surface and
acted on there. Notification is a documented follow-up, not a shortcut.

**C6. The Control Plane owns AI configuration.** "AI" is a Control Plane
administration domain, and the routing table is already its. Resolution: this
repository documents the contract and consumes what exists; the one portal
route it needs today already exists; everything it would want next is written
as a requirement for the other repository and built nowhere here.

**C7. The gateway is optional.** Anything in `packages/*` or `services/api`
that imports AI unconditionally breaks the default generation. Resolution: a
capability `ai` in the product manifest, off by default, that gates every AI
subtree; the generator refuses `ai` without `ai_gateway`; `koras-ai` is a
framework package that imports nothing at import time it cannot satisfy.

**C8. The template map gates one path per key.** The AI foundation spans a
router, a page, a migration, a test and an extension point. Resolution: the
`template_map` capability schema accepts a list of paths as well as one, a
backward-compatible generator change with a test.

**C9. Response field names.** `tests/security/test_api_surface.py` refuses any
response field whose name contains "token", so a usage report cannot say
`total_tokens` on the wire. Resolution: usage crosses the wire as `input`,
`output` and `total` inside a usage object; the database columns keep the
honest names.

**C10. TypeScript examples in the request, trusted execution in Python.** The
request sketches registries in TypeScript. Tools need the tenant session and
the API is where trusted work runs. Resolution: registries and execution are
Python in `koras_ai` and the API; the web tier is the surface, through
`packages/api-client` and server actions, as every other module already is.

**C11. Streaming through server actions.** A Next server action cannot stream.
Resolution: the provider protocol carries an optional stream operation and the
gateway adapter implements it; the product surface is request and response in
this iteration, and a streaming route is a documented follow-up.

**C12. Forms.** The `koras-forms` skill names React Hook Form and Zod; the
product template uses neither, and every form is a server action with
`useActionState`. Resolution: follow the code.

**C13. Run it once before extending it.** Three documents say that no design
grows past the first real run. Resolution: the foundation ships one reference
agent and one reference tool, the reference validation phase records what was
run, and a real call through a real gateway with a real key is named as not
done by this repository rather than implied.

**C14. The AI package depends on LiteLLM.** The stub's manifest pulls the whole
proxy library into every product. Resolution: `koras-ai` depends on httpx and
pydantic; LiteLLM stays in the gateway where it belongs.

## 7. Recommendation

Build the foundation as a product-profile capability named `ai`, off by
default, that requires the `ai_gateway` service. The runtime is Python:

```text
python-packages/koras-ai/          the framework: provider protocol and gateway adapter,
                                   aliases and catalogue, context, errors, registries
                                   for agents, tools, prompts and knowledge, the risk
                                   policy, the approval state machine, the agent loop,
                                   a store protocol
services/api/koras_api/core/ai.py  the dependency: context from TenantDep and AuthDep,
                                   configuration from the Control Plane or the product
                                   catalogue, the entitlement gate, the SQL store
services/api/koras_api/routers/ai.py
                                   conversations, messages, actions, status
services/api/koras_api/ai/         the generated extension point: a product's own
                                   agents, tools, prompts, knowledge, model catalogue
supabase/migrations/00006_ai.sql   conversations, messages, actions, usage events
supabase/tests/060_ai_isolation.sql
packages/api-client                the AI functions
packages/ui/src/ai/                the components
apps/web/src/app/dashboard/assistant/
                                   the page, the drawer, the server actions
```

The reasons, in the order they matter: the trusted work already lives in the
API; the gateway already is the provider boundary; the entitlement, tenant and
permission models are complete and tested and need extending rather than
replacing; a code registry is the pattern the shell established; and gating by
capability is the mechanism the generator already has, extended by one
backward-compatible field. The Control Plane contract is what exists today,
the routing route per capability, with the alias as the capability key, and a
written requirement for the rest.

What is deliberately not built: a vector store, a streaming route, approval
notifications, and per-product assignment of roles. Each is staged in the plan
with the reason.
