# AI Security — the assistant as an untrusted subsystem

> Scope: the boundaries the Koras AI Foundation enforces in a generated
> product, where each is enforced, and the test that proves it. The model is
> treated as an untrusted caller that can propose and cannot decide.
> `docs/AI_ARCHITECTURE.md` describes the pieces; this is the argument that
> they hold.

## Tenant enforcement

The tenant is resolved from the verified token by `TenantDep`, never from a
request. The AI request models forbid extra fields, so a body naming a
tenant or an organization is 422; `tests/unit/test_ai_api.py` sends both.
`AIContext` refuses to be built with an empty tenant. Every table in
`supabase/migrations/00006_ai.sql` carries a tenant column, enables and
forces RLS, and scopes every verb on the tenant helper; every statement in
`SqlStore` names the tenant as well. `supabase/tests/060_ai_isolation.sql`
proves a second tenant sees no conversation, message, action or usage row,
cannot write one, and cannot approve the first tenant's waiting action.
`python-packages/koras-ai/tests/test_runtime.py` proves the same through the
runtime with the in-memory store, and that a message asking for another
tenant's data still runs the tool under the caller's.

## Authorization

Deterministic and in code. `decide` in
`python-packages/koras-ai/src/koras_ai/policy.py` compares the tool's
declared permission with the permissions the verified roles grant; `may_decide`
adds the approve permission, the tool's own, and for a destructive operation
an owner or administrator role. The model is offered only the tools the
caller may use, and a proposal for anything else, offered or not, is refused
and audited without an action row. Nothing the model says is an input to
either decision. The Python permission catalogue mirrors the TypeScript one
and the structural test keeps them level.

## Tool controls

Every tool is registered with a dotted id, a permission, an operation class
and a pydantic schema. A proposal names a tool by id; an unregistered id, a
tool not in the agent's list, or one the caller may not use is refused. The
arguments are validated against the schema before anything runs; invalid
arguments are refused and told to the model as data. Read executes at once;
write, destructive and external become an action with a state machine that
refuses a skipped step, and execute only through the approve route by a
person the policy admits. A tool may add approval and cannot remove it. The
agent's turn limit bounds how many model calls one message can cause.

## Prompt injection

The text a model reads includes text a customer typed and text a tool
returned. Neither can authorize anything, because authorization reads
neither. Beyond that: the system prompt says tool results are data; the
runtime prefixes every tool result with the same statement; a prompt template
cannot reach into an object from a string; the model's answer is rendered as
text and never as markup; and the page context a browser sends is
informational and scopes nothing. A model persuaded to propose a destructive
tool proposes it into an approval queue that a person reads.

## Secrets

The gateway holds the provider keys. The API holds the gateway's master key,
in settings declared in `local/config/secrets.manifest` and refused at the
first AI request when empty. Nothing under `apps/` or `packages/` names
either; `generators/create-koras-app/tests/product-ai.test.ts` asserts the
panel and the launcher carry no API address, no token and no master key, and
the platform's response schemas are checked by `tests/security/test_api_surface.py`
for any field named like a credential. The runtime's error type keeps the
upstream body in a `detail` that is logged and a `message` that is shown;
`python-packages/koras-ai/tests/test_gateway.py` asserts a key-shaped
upstream body never reaches the message. Audit events refuse a detail named
like a secret.

## Direct provider access

There is none. The only client of the gateway is `GatewayProvider`, built
once per process inside the API's dependency. No route reaches it without
the tenant, the plan and the context; no browser code reaches the API's
address; the gateway README says so and the structural test holds it to
that. The catalogue may not name a vendor route.

## Entitlement and usage

`ai.assistant` gates every route with 402 before a model is called.
`ai.tools` off means the model is offered no tools. `ai.requests` is a
calendar-month allowance counted from usage rows, failed attempts included,
refused with 429. A configured platform that does not answer is 503, so an
outage cannot become free usage; a product with no platform runs ungated and
says so in its status.

## Audit and retention

Every refusal, proposal, execution, approval and rejection emits an
`AuditEvent` through `koras_audit`, with actor, tenant, target and outcome
and no content. The action row is the durable record of a proposal's life.
Usage rows carry dimensions and counts and no content, and no policy lets
anyone the policies apply to change or delete one. Messages hold content and
are the one place it lives; retention is a product decision and the tables
carry the timestamps a sweep needs.

## What is not yet covered

- Rate limiting per tenant beyond the API's tier-2 limiter and the monthly
  allowance. A per-minute AI quota is an extension point on `Limits`.
- A durable audit table. The sink is a log line today.
- Approval notification. A waiting action is visible in the assistant and
  nowhere else.
- Content moderation of what a model returns. Rendered as text; not
  screened.
