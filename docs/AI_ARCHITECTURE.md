# AI Architecture — one runtime in the API, aliases in product code, the gateway as the only provider

> Scope: the Koras AI Foundation as built in `koras-saas-starter` on
> 2026-09-13, for the product profile. `docs/AI_FOUNDATION_ASSESSMENT.md`
> records what existed before and why this shape was chosen;
> `docs/AI_FOUNDATION_PLAN.md` the phases; `docs/AI_DEVELOPER_GUIDE.md` how a
> product uses it; `docs/AI_SECURITY.md` the boundaries; and
> `docs/AI_CONTROL_PLANE_CONTRACT.md` what the platform answers and what it
> would need to. Nothing here is product-specific, and
> `docs/adr/0001-koras-shared-ai-foundation.md` is the record of the decision.

**Status.** Built and tested in the templates on 2026-09-13. Generator
Integration builds a product with `--with marketing,ai_gateway,scheduler,ai`
and runs its Python, Node, RLS and browser suites. No model has been called
through a deployed gateway by this repository; see the final section.

## The shape

```text
                       KORAS CONTROL PLANE
                  entitlements   routing per alias
                        │              │
                        ▼              ▼   (portal routes, the customer's token)
┌──────────────────────────────────────────────────────────────────────────┐
│ services/api                                                             │
│                                                                          │
│  core/ai.py        TenantDep + AuthDep ─▶ AIContext                       │
│                    entitlements ─▶ AiGrant (402 / 429 / 503)             │
│                    ai_routing per alias ─▶ ControlPlaneRouting           │
│                    DbSession ─▶ SqlStore                                 │
│                    GatewayProvider (one per process)                     │
│                                                                          │
│  routers/ai.py     status · conversations · messages · approve · reject │
│                                                                          │
│  koras_api/ai/     the extension point: agents, tools, prompts,          │
│                    knowledge, the model catalogue                        │
└──────────────┬───────────────────────────────────────────────────────────┘
               │ koras_ai (python-packages/koras-ai)
               │   AIRuntime: the turn, the policy, the approvals, the meter
               │   ModelCatalogue + AIConfiguration: alias ─▶ routes
               │   registries: tools, agents, prompts, knowledge
               ▼
       services/ai-gateway        the LiteLLM proxy: holds the keys,
       (OpenAI-compatible)        answers by gateway model name
               │
      OpenAI · Anthropic · whatever the gateway lists

┌──────────────────────────────────────────────────────────────────────────┐
│ apps/web                                                                 │
│  dashboard/assistant/   page · panel · launcher · server actions         │
│  dashboard/layout       the header trigger, the page-context provider    │
│ packages/api-client     the AI functions, ApiError with a code           │
│ packages/ui/src/ai      the eleven components, plain data in             │
│ packages/branding       the assistant module in the registry            │
│ packages/permissions    ai.use, ai.approve                               │
└──────────────────────────────────────────────────────────────────────────┘
```

## Request flow

A person types in the composer. The panel calls a server action; the action
re-establishes who is calling and what they may do, then calls the product's
API with the person's own token. The API's dependency in
`services/api/koras_api/core/ai.py` resolves the tenant and the caller the
way every route does, reads the plan from the platform, refuses before any
model is called when the plan lacks the assistant, and hands the runtime a
context built from the verified token and nothing from the request body.

The runtime, in `python-packages/koras-ai/src/koras_ai/runtime.py`, stores
the message, assembles the agent's instructions and the history, offers the
model only the tools the caller holds the permission for, and calls the model
under the agent's alias. The alias resolves to routes: the platform's policy
for this customer and alias where one exists, the product's catalogue
otherwise. Each attempt writes a usage row. The answer is stored. Every tool
call the model proposed is looked up, validated against the tool's schema
and authorized in code: a read executes now, anything else becomes an action
awaiting a person, and the turn ends there. The API answers with the messages
this turn added, the actions left waiting, and the usage.

Approval is a second request by a person. The runtime checks they hold the
approve permission and the tool's own, and for a destructive operation an
owner or administrator role, then executes and records the result as a tool
message the next turn can see.

## Providers and models

`AIProvider` in `python-packages/koras-ai/src/koras_ai/providers.py` is the
protocol; `GatewayProvider` is the one implementation a product ships, over
httpx to the gateway with the master key as its bearer. It translates the
OpenAI-compatible wire shape into messages and tool calls and every failure
into a code with a safe sentence. `FakeProvider` and `FailingProvider` are for
tests. Nothing in a product imports a vendor SDK.

Product code names an alias from `ModelAlias`: `koras-fast`, `koras-balanced`,
`koras-reasoning`, `koras-embedding`, `koras-vision`. The product's catalogue
in `services/api/koras_api/ai/models.py` lists, per alias, the routes that can
serve it, each a provider name in the platform's vocabulary and a model name
the gateway lists in `services/ai-gateway/litellm_config.yaml`. The
starter's `generators/create-koras-app/tests/product-ai.test.ts` keeps the
two files level and refuses a vendor route in the catalogue.

`ModelCatalogue.resolve` is where a policy meets the catalogue: the policy
names the providers in order and may name the primary's model; the catalogue
supplies the rest; a provider the catalogue cannot serve is skipped, and a
policy that leaves nothing is a configuration error rather than a fall-through.
The runtime tries the routes in order and moves to the next on an unavailable
provider, a timeout or an upstream error, never on a refused credential.

## Context

`AIContext` in `python-packages/koras-ai/src/koras_ai/context.py` carries the
product code, the environment, the tenant, the organization, the user, the
roles the token carried and the permissions they grant. It refuses to be
built with any identity field empty. The permissions come from
`python-packages/koras-auth/src/koras_auth/permissions.py`, the Python mirror
of the TypeScript catalogue, and the structural test keeps the two level.
The only client-supplied field is the page context, which names a screen and
scopes nothing.

## Agents, tools, prompts, knowledge

All four are code registries, declared in the generated extension point and
built once at import by `services/api/koras_api/ai/__init__.py`, which also
refuses an agent naming a tool or a prompt nobody registered. A registry is
configuration, the way the navigation registry is; only runtime state gets
tables.

A tool is a `ToolDefinition`: a dotted id, a sentence for the model, the
product permission it needs, its operation class, a pydantic input model and
an executor that is handed a `ToolContext` with the context, the tenant
session and whatever services the product chose to expose. The operation
classes and their policy are in `python-packages/koras-ai/src/koras_ai/policy.py`
and are fixed: read runs; write, destructive and external wait; destructive
additionally needs an owner or administrator to approve. A tool may add
approval to a read and cannot remove it from anything else.

An agent is an `AgentDefinition`: an alias, instructions or a prompt id, the
tools it may propose and a turn limit. The reference agent is `assistant`
with the one reference tool `files.list`, which reads the tenant's files
through the tenant session.

A prompt is a `PromptDefinition` with a version and declared variables,
rendered strictly in both directions with a template syntax that cannot reach
into an object. The runtime supplies `product` and `page`.

Knowledge is contracts: documents, chunks, citations, a scope that cannot be
built without a tenant, and the extractor, chunker, embedder, index and
retriever protocols, with a default chunker and an embedder over the provider
boundary. No index ships; no source is declared; nothing is crawled.

## Entitlements

Three platform entitlements, read from the portal route with the customer's
token and turned into an `AiGrant` by `grant_from`:

```text
ai.assistant   whether the assistant may be used at all; 402 without it
ai.tools       whether proposals become actions; without it the model is offered no tools
ai.requests    the calendar-month allowance of model calls; 429 when spent
```

A configured platform that does not answer is a 503, unlike storage, for
the reason `docs/AI_FOUNDATION_ASSESSMENT.md` gives. No platform configured
is the bootstrap order: the product runs on its own catalogue, ungated, and
the status route says the plan is unresolved.

## Approvals and audit

`ProposedAction` in `python-packages/koras-ai/src/koras_ai/actions.py` is
the state machine; the `ai_actions` table repeats its vocabulary in a check
constraint. Every transition is checked, and a skipped or reversed step is
refused. Who proposed, who decided, when, the input, the result and a safe
error are on the row.

`koras_audit` gained its first implementation: an `AuditEvent` that refuses a
detail named like a secret, and a logging sink. The runtime emits an event
for every proposal it refuses, every action it parks, executes, approves or
rejects, denials included. Since 2026-09-14 that sink is durable:
`SqlAuditSink` in `services/api/koras_api/core/ai.py` keeps the request's
events and writes them to `ai_audit_events` when the route flushes -- after
the answer and after a refusal alike -- and `GET /api/v1/ai/audit` reads
them back for anyone with `ai.approve`; the assistant page shows the list
to those people. Rows are never updated or deleted by anyone the policies
apply to; the nightly sweep removes them after `AI_AUDIT_RETENTION_DAYS`.

An action that waits for approval is also announced: `core/notify.py` tells
the organization's owner and every active member whose role carries
`ai.approve`, after the response, naming the tool and who proposed it and
never the proposal's input, over SMTP to whichever provider the
environment's SMTP_* settings name. Where none is set the notice is recorded
and logged.

## Usage

One row in `ai_usage_events` per model call, attempts that failed included,
with the tenant, the user, the agent, the alias, the provider and model that
answered, the counts, the latency and the status. No content. The monthly
allowance is a count over this table by tenant and calendar month.

Each row also carries `estimated_cost_micros`, the vendor's list price for
its tokens in millionths of a dollar, when the route that answered carried a
price from the platform's routing policy, and null when it did not. The
platform collects this table as daily aggregates through the private
router's read on the provisioning session, which the `070_ai_usage_platform_read.sql`
isolation test bounds to reading; `AI_CONTROL_PLANE_CONTRACT.md` describes
that half.

## Data

Migration `supabase/migrations/00006_ai.sql`: four tables, every one with a
tenant column, RLS enabled and forced, and a policy per verb scoped on the
tenant helper; usage rows have no update or delete policy. The isolation
test `supabase/tests/060_ai_isolation.sql` proves a second tenant sees,
writes and approves nothing. Later migrations add the cost column and the
platform read (00007), the retention policies (00008), the audit table
(00009) and the knowledge table (00010, pgvector); the isolation tests 070
to 100 bound each.

Retrieval is pgvector in this database. `ai_knowledge_chunks` holds one row
per chunk of one document, 1536-wide, under the tenant policies; a file
that finishes uploading and is text-like and under a megabyte is read back,
chunked, embedded under the embedding alias and stored after the upload's
response, and its chunks go when the file goes. `knowledge.search` is the
tool the assistant calls; `core/knowledge.py` is the index. The reference
agent also carries `files.delete`, the one destructive tool, so the approval
flow has something real to approve: proposed by the model, parked by the
runtime, decided by a person with `files.manage`, and then run the way the
Files page deletes. PDFs give their
text layer and workbooks their cells. An image, or a PDF with no text
layer, is read instead: its pages are rendered (pypdfium2) and each is
transcribed by the vision alias, one metered call per page under the
agent id `knowledge.ocr`, up to twenty pages a file. The text layer
always wins when there is one, because it is exact and costs nothing.
The Files page says which happened: *searchable*, *pending*, or *no*
with the reason the indexer recorded.

## The web tier

The module `assistant` sits in the navigation registry with the permission,
the entitlement and the capability that gate it, locked rather than hidden
when the plan lacks it. The page at `apps/web/src/app/dashboard/assistant/page.tsx`
checks the permission and the plan again server-side. The header trigger
mounts through the shell's `headerActions` slot from the dashboard layout,
for a caller who may use the assistant, and opens a drawer holding the same
panel the page renders, with the page context the current screen declared
through `AIPageScope`. The eleven components in `packages/ui/src/ai/` take
plain, translated data and know nothing of the API.

## Pay as you go beyond the allowance

Built 2026-09-15. The monthly allowance stays the plan's; what changes is
what happens when it is spent. An owner or administrator turns pay as you
go on in the portal from a consent screen that is the whole contract: the
approximate price of a hundred requests (from their own last thirty days,
or from the plan's routing template and a typical message while there is
not enough history, and the card says which), the rate per alias, a
monthly limit on charges they choose, and the sentence that says actual
charges depend on the model and the message. The rate card they saw is
copied onto the row with who agreed and when. Staff set the rate
(`rate_percent`, 400 is four times list-price cost) and may block it; a
customer cannot price their own plan, and staff cannot agree on a
customer's behalf.

The product learns of it through the entitlements it already reads:
`ai.overage` with the limit in cents and the rate in `config`. Past the
allowance the runtime makes the call and stamps the usage row -- over the
allowance, the list-price cost, the rate in force, and the billable
amount -- so a later rate never rewrites a past month; the customer's
limit is then the stop, with a refusal that names it. Successful calls are
what count toward the allowance; a provider that failed did not serve the
customer. The assistant page shows the charges so far beside the
allowance, the platform's daily aggregate carries overage calls and the
billable sum, the customer's billing page shows charges as they accrue,
staff see cost, rate and margin, and the owners are mailed once per
level at 80% and 100% of the limit by the hourly collection.

Not built: reporting the month's charges to Stripe. The Control Plane's
billing branch uses Stripe Managed Payments and has not been run live,
and whether metered lines or invoice items work through it is the check
that comes before that design.

## What is deferred, and where it goes

- **Streaming.** Built 2026-09-14. The runtime tells a turn as events --
  text as it is produced, each message once stored, an action when parked,
  the finished turn last -- and `send` is that stream kept to the end, so
  the two routes cannot disagree. `POST .../messages/stream` writes them as
  server-sent events on a session of its own, declared for the tenant,
  because a stream outlives the request session. The web tier reaches it
  through its own `/api/assistant/stream` route handler, which decides who
  is calling the way the server actions do and pipes the bytes through;
  the browser never sees the API's address or the token. A refusal inside
  the stream is an `error` event carrying the status the whole-answer
  route would have had.
- **Tracing.** Every gateway call is a client span named by the GenAI
  conventions (`ai.chat`, `ai.embeddings`; provider, model, alias, tokens)
  with the trace context forwarded to the gateway. The exporter is chosen
  by `OTEL_EXPORTER_OTLP_PROTOCOL`, which the SDK does not read when the
  exporter is built in code; the dev API spent eight days sending gRPC to
  Grafana's HTTP gateway for that reason.
- **Approval notification.** Built 2026-09-14: the approvers are mailed
  after the response, with the requester and the action in words.
- **A vector store.** Built 2026-09-14 on pgvector; see the knowledge
  section above.
- **Retention.** Built 2026-09-14: the worker's nightly sweep removes
  conversations untouched for `AI_RETENTION_DAYS` (ninety unless set),
  messages and actions cascading, usage rows kept, on the provisioning
  context that migration 00008 admits for that delete alone.
- **A real call.** This repository cannot make one. The first product to
  enable the capability with keys in Doppler runs the assistant once before
  building on it, which is the rule every design here follows.
