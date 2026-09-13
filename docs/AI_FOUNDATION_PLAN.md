# Koras AI Foundation Implementation Plan

> Scope: `koras-saas-starter` only. This is the plan `docs/AI_FOUNDATION_ASSESSMENT.md`
> recommends, in phases, with the files each phase touches and the test that
> closes it. `docs/AI_ARCHITECTURE.md` describes the result; `docs/AI_DEVELOPER_GUIDE.md`
> says how a generated product uses it; `docs/AI_SECURITY.md` records the
> boundaries; `docs/AI_CONTROL_PLANE_CONTRACT.md` names what `koras-control-plane`
> would have to satisfy and is built nowhere here.

**Status.** Written 2026-09-13, before implementation. Each phase below records
its state as it closes.

## 1. Current state

Summarised from the assessment. The product profile has an optional LiteLLM
gateway that holds the provider keys, an empty `koras-ai` package that depends
on the proxy library, and an unused Control Plane routing read. Nothing in a
product calls a model. Tenant, permission and entitlement models are complete
and tested; audit and usage do not exist; approvals have no prior art.

## 2. Reusable existing components

The table in section 3 of the assessment. In short: `AuthDep` and `TenantDep`
supply the context; `read_portal` and `ai_routing` supply the Control Plane's
answers; `parseEntitlements` and `isEntitled` gate the web tier and the
`_grant_from` pattern gates the API; `PRODUCT_PERMISSIONS` and `ROLE_PERMISSIONS`
are the permission catalogue; the navigation registry and `canOpenModule` are
the module gate; `packages/api-client` is the transport; the primitives and
the shell drawer are the UI; migration 00005 and its isolation test are the
schema pattern.

## 3. Architecture decisions

Each is a decision this plan makes; the assessment's conflict section is the
argument.

1. **The runtime is Python, in the API.** Every model call, tool execution,
   approval and usage record happens in `services/api`, where the tenant
   session, the caller's token and the database already are. The web tier is a
   surface over it through `packages/api-client` and server actions.
2. **The gateway is the only provider.** `koras-ai` speaks the OpenAI-compatible
   protocol to `AI_GATEWAY_URL` with `LITELLM_MASTER_KEY`, over httpx. No
   provider SDK, no provider key and no provider model name reaches application
   code. LiteLLM is a dependency of the gateway service and of nothing else.
3. **Product code names aliases.** Five aliases, resolved to gateway model
   names by a catalogue the product owns, overridden per customer by the
   Control Plane's routing policy where one exists.
4. **Fail closed on a silent platform, use the product catalogue when there
   is no platform.** A Control Plane that is configured and does not answer
   is a refusal, the same decision `ai_routing` already makes. A product with
   no Control Plane configured resolves aliases from its own catalogue,
   which is the documented bootstrap order.
5. **Registries are code.** Agents, tools, prompts and knowledge sources are
   declared in a generated extension point and registered at import time.
   Only runtime state gets tables.
6. **Authorization is deterministic and never the model's.** A tool declares
   the product permission it needs and its operation class. The runtime
   checks the permission against the caller's verified roles, the operation
   against the approval policy, and the entitlement against the plan, before
   anything executes. A model can propose; it cannot authorize.
7. **The approval policy is fixed by operation class.** Read executes; write,
   destructive and external wait for a person holding both the tool's
   permission and the approve permission; destructive additionally requires
   an owner or administrator role.
8. **Usage is a row per model call**, written by the runtime, carrying the
   dimensions the request lists and no content. The monthly request limit is
   an entitlement limit counted from that table.
9. **Audit is the action table plus a structured log line.** Proposed,
   approved, rejected, executed and failed are states on the action row with
   who and when; `koras_audit` gains a minimal emitter used for the same
   events, the seam a durable audit table later replaces.
10. **AI is a capability, off by default, requiring the gateway.** A product
    generated without it carries no router, page, migration, test or
    extension point, and every other module is untouched.
11. **No vector store, no streaming route, no approval notification** in
    this iteration. Each is an interface or a documented follow-up.

## 4. Proposed package and service structure

```text
python-packages/koras-ai/src/koras_ai/
  __init__.py          the public surface
  types.py             Message, ToolCall, GenerateRequest, GenerateResult, Usage, Embed*
  errors.py            AIError and the error codes
  models.py            ModelAlias, ModelRoute, ModelCatalogue
  context.py           AIContext
  config.py            AIConfiguration, ConfigurationSource, StaticConfiguration
  providers.py         AIProvider protocol, GatewayProvider, FakeProvider
  tools.py             define_tool, ToolDefinition, Operation, ToolRegistry, ToolContext
  agents.py            define_agent, AgentDefinition, AgentRegistry
  policy.py            approval policy and permission checks
  actions.py           ActionStatus, ProposedAction, the state machine
  store.py             ConversationStore protocol, InMemoryStore
  runtime.py           AIRuntime: the agent loop
  prompts.py           define_prompt, PromptRegistry, rendering
  knowledge.py         RAG contracts and the knowledge-source registry
  usage.py             UsageEvent, UsageRecorder protocol
python-packages/koras-ai/tests/
python-packages/koras-audit/src/koras_audit/__init__.py   AuditEvent, emit
python-packages/koras-auth/src/koras_auth/permissions.py  the Python permission catalogue

services/api/koras_api/core/ai.py          the dependency, the SQL store, the gate
services/api/koras_api/routers/ai.py       the routes
services/api/koras_api/ai/                 the extension point: agents, tools, prompts,
                                           knowledge, models
supabase/migrations/00006_ai.sql
supabase/tests/060_ai_isolation.sql
tests/unit/test_ai_api.py                  router tests with dependency overrides

packages/permissions/src/index.ts          ai.use, ai.approve
packages/api-client/src/index.ts           the AI functions
packages/ui/src/ai/                        AITrigger, AIDrawer, AIConversation, AIMessage,
                                           AIComposer, AISuggestedActions, AICitations,
                                           AIToolResult, AIActionApproval, AIUsageNotice, AIError
packages/branding/src/index.ts             the assistant module, the sparkle icon name
packages/i18n/src/messages/{en,de,es}.ts   the assistant catalogue
apps/web/src/app/dashboard/assistant/      page, panel, actions, the drawer, the page context
apps/web/src/app/dashboard/layout.tsx      the header trigger
e2e/assistant.spec.ts

profiles/product/manifest.yaml             capability ai, template_map, requires
profiles/product/defaults.yaml             ai: false
generators/create-koras-app/src/profiles/types.ts       list-valued template_map, requires
generators/create-koras-app/src/profiles/validator.ts   the requires rule
generators/create-koras-app/tests/product-ai.test.ts    the structural test
.github/workflows/generator-integration.yml             --with ai on the full row
```

## 5. Database impact

One migration, four tables, all with `tenant_id`, RLS enabled and forced, a
policy per verb scoped on `current_tenant_id()`, and one isolation test in the
shape of `supabase/tests/050_files_isolation.sql`.

```sql
ai_conversations   id, tenant_id, created_by, agent_id, title, context_type, context_id,
                   created_at, updated_at
ai_messages        id, tenant_id, conversation_id, role, content, tool_call_id, tool_name,
                   created_at
ai_actions         id, tenant_id, conversation_id, message_id, tool_id, operation,
                   input, status, proposed_by, decided_by, decided_at, result, error,
                   executed_at, created_at
ai_usage_events    id, tenant_id, user_id, conversation_id, agent_id, model_alias,
                   provider, model, input_tokens, output_tokens, total_tokens,
                   latency_ms, status, error_code, created_at
```

Content lives in messages only. Usage events carry no content. Action input
is stored because it is what executes after approval, and it is bounded by
the tool's schema. Retention is a documented follow-up: the tables carry
timestamps so a sweep can be written without a second migration.

## 6. API impact

Seven routes under the customer surface, mounted like Files behind the
authenticated limiter:

```text
GET  /api/v1/ai/status                          enabled, entitled, usage this month
GET  /api/v1/ai/conversations                   the caller's tenant's conversations
POST /api/v1/ai/conversations                   start one, optionally with page context
GET  /api/v1/ai/conversations/{id}              messages and pending actions
POST /api/v1/ai/conversations/{id}/messages     send a message, run the agent turn
POST /api/v1/ai/actions/{id}/approve            execute a waiting action
POST /api/v1/ai/actions/{id}/reject             refuse it
```

Refusals map the error codes to status: the plan lacks it 402, the monthly
limit is spent 429, the caller lacks the permission 403, the platform did not
answer or the gateway is unreachable 503, an unknown alias or an unregistered
tool 400, a provider error 502, a timeout 504, AI not generated 404 by absence.
No response field name contains a forbidden word; usage crosses the wire as
`input`, `output`, `total`.

## 7. Generator impact

- `capabilities.ai: true` in the product manifest, `ai: false` in defaults.
- `template_map.capabilities` accepts a string or a list of paths; `ai` lists
  every AI subtree.
- A `requires` map in the manifest: `ai` requires `ai_gateway`. Enabling `ai`
  without the gateway is refused with the flag to pass.
- `.koras/project.yaml` records `ai` under `components.capabilities` with no
  schema change.
- The full row of Generator Integration adds `ai` to its `--with` list, so the
  router, the migration, the isolation test, the package tests and the browser
  suite run against a generated product.

## 8. Manifest impact

None to `.koras/project.yaml`'s schema. The prompt's proposed features block
is not added: the components list already answers "was AI generated", and the
runtime answers "is AI enabled for this customer" from the plan, which is not
a fact a generated file should record.

## 9. UI impact

A module in the registry, a page at the module's route, a header trigger that
opens a drawer on every signed-in page, and eleven components in
`packages/ui`. Nothing in `packages/ui/src/shell` changes; the trigger uses
the `headerActions` slot that has been empty since the shell was written.
Labels arrive translated from the server, the way `FilesPanel` takes them.
The drawer follows the shell's own drawer: a dialog, a focus trap, Escape,
focus return.

## 10. Security model

Recorded in full in `docs/AI_SECURITY.md`. In one paragraph: the context is
built from the verified token and the resolved tenant and never from the
request; every table is RLS-forced; every query also names the tenant; the
model proposes tool calls that are validated against the registry and the
tool's schema, then authorized against the caller's permission and the
operation's policy, in code; nothing executes on a model's say-so; the
gateway key and the platform address stay on the server; prompts and
results are logged as dimensions, never as content; a tool result is data
to the model and nothing more.

## 11. Entitlement integration

Three keys, declared once in Python and referenced by the registry entry:

```text
ai.assistant   boolean   gates the module and every model call
ai.tools       boolean   gates tool execution; without it the agent answers and proposes nothing
ai.requests    quota     limit_value is model calls per calendar month, counted from usage
```

The web tier locks the module when the plan lacks the first. The API refuses
with 402 when the plan lacks the first or the second where a tool would run,
and with 429 when the third is spent. An unresolved plan on the API is a
refusal for AI, unlike storage, and the reason is stated in the code.

## 12. Control Plane contract

What exists and is consumed: the portal routing route per capability, with
the alias as the capability key, and the portal entitlements route. What is
documented as a requirement for `koras-control-plane` and not built here: a
configuration route carrying enabled providers and their secret references
by name, alias defaults per product, budget limits, tool policies, and usage
reporting. See `docs/AI_CONTROL_PLANE_CONTRACT.md`.

## 13. Phase AI-1 — core foundation

`koras-ai` types, errors, aliases and catalogue, context, configuration,
provider protocol, gateway adapter over httpx with a fake transport in tests,
fake provider, registry base. `koras-auth` gains the permission catalogue.
Closes when the package tests pass under ruff, mypy strict and pytest.

## 14. Phase AI-2 — client and shared UI

The API client functions, the eleven components, the page, the drawer, the
server actions, the translations, the registry entry, the permissions, the
browser test. Closes when the generated product builds, typechecks and the
Playwright suite passes at 375 and 1440 without an API, the way the Files
suite does.

## 15. Phase AI-3 — entitlements, usage and audit

The API dependency, the SQL store, the entitlement gate, the usage recorder,
the audit emitter, the routes for conversations and messages, the router
tests with dependency overrides, the migration and the isolation test.
Closes when the router tests pass and the RLS suite runs the isolation test.

## 16. Phase AI-4 — agents, tools and approvals

The registries, the operation classes, the approval policy, the action state
machine, the agent loop, the approve and reject routes, the approval UI, the
reference agent and the reference read tool. Closes when the policy and
lifecycle tests pass and the approval component renders in the browser.

## 17. Future RAG

Contracts only: documents, chunks, citations, scopes, the extractor, chunker,
embedder, index and retriever protocols, and the knowledge-source registry
with a default chunker. No index implementation ships in a product. A
product that needs retrieval implements the index against whatever store its
design chooses; the plan for that is a design document of its own.

## 18. Testing strategy

Unit tests in `python-packages/koras-ai/tests/` for aliases, context,
registries, policy, actions, prompts, knowledge and the gateway adapter.
Router tests in the product's `tests/unit/` with dependency overrides and an
in-memory store. The isolation test in `supabase/tests/`. Node tests in
`packages/permissions` and `packages/branding` for the new permissions and
the module resolution. Playwright for the page and the drawer. In the starter,
one structural test keeping every cross-language name level, the generator
tests for the capability and the requirement rule, and the docs tests.

## 19. Migration and compatibility

A product generated before this work has no `ai` capability recorded and
receives nothing. `--check-drift --all` reports the new files as missing only
when `ai` is enabled. The `koras-ai` manifest changes its dependencies, which
an existing product picks up on refresh; nothing imported the stub, so
nothing breaks.

## 20. Risks

- A provider called through the gateway returns tool calls in a shape LiteLLM
  did not normalise. Mitigated by the adapter parsing defensively and a test
  per shape; a real call is still the only proof.
- The monthly count is a query per call. Acceptable at the volume of a new
  product; an index on the usage table by tenant and time keeps it cheap.
- The extension point is generated once. A product that edits it and later
  refreshes it loses the edit; the generator's refresh already requires the
  path to be named, which is the consent.
- Nothing in this repository can make a real model call. The reference
  validation phase records what was run and what was not.

## 21. Definition of done

The list in the request, checked against what shipped, is the final report.
