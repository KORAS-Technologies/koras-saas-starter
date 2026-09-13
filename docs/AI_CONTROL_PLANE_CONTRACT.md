# AI Control Plane Contract — what a product reads today, and what the platform would need to offer

> Scope: the interface between a generated product's AI runtime and
> `koras-control-plane`. Two halves. The first is what exists and is
> consumed, read out of the platform's routes rather than assumed. The
> second is a requirement on the other repository, written here and built
> nowhere here: `koras-control-plane` is not touched by the AI foundation
> work, and this document is the whole of what it is asked for.

**Status.** The consumed half is in the code and tested with stubs. The
required half is a proposal, dated 2026-09-13, for the Control Plane's own
roadmap to take up or decline. Two parts of it were taken up the same day,
in `koras-control-plane` rather than here: a plan-tier routing template
written to a new customer's rows at provisioning, and a staff-only
catalogue of providers, aliases and default models behind the admin's AI
page. Both are described under *Routing* below, because they change what a
product reads, not what it has to offer.

## The separation

```text
Control Plane          decides, per organization and product:
                       whether AI is licensed, how much, and which
                       providers answer which alias

Koras AI runtime       enforces those decisions and runs the model call,
(the product's API)    with the provider keys the gateway holds

Doppler                holds every secret; the platform stores references
                       by name and never a value
```

A product never learns a provider key, never needs a provider's model name
unless it debugs one, and never holds a Doppler token for the platform's
secrets. The Control Plane never calls a model.

## What exists and is consumed

### Entitlements

`GET /api/portal/v1/products/{code}/entitlements`, with the customer's own
token; the organization comes from the token and there is nowhere to name
another. The product reads three codes:

```text
ai.assistant   boolean   the assistant may be used at all
ai.tools       boolean   proposals may become actions
ai.requests    quota     model calls per calendar month; limit_value is the ceiling
```

They are ordinary entries in the commercial catalogue, authored the way
every entitlement is, and a plan grants or overrides them the way it grants
storage. Nothing about them is special to the platform. `grant_from` in
`services/api/koras_api/core/ai.py` is the reader.

### Routing

`GET /api/portal/v1/products/{code}/ai-routing/{capability}`, the same token
and the same argument, read by `ai_routing` in
`services/api/koras_api/core/platform.py`. The capability key is the model
alias: a policy for `koras-balanced` for one organization names the ordered
providers to try and, in its secret-free configuration, may name the primary
model as `model` and the fallback's as `fallback_model`. `ControlPlaneRouting`
in `services/api/koras_api/core/ai.py` turns it into an `AliasPolicy`;
`ModelCatalogue.resolve` merges it with the product's defaults, a named model
applying to the provider it was named for and to no other.

The platform writes those rows itself for a new customer on Pro, Business or
Enterprise, from a template per tier, at provisioning; a row staff have
already set is never moved back to the template, and Starter gets none,
because Starter has no assistant. The provider names it offers are the four
the product's gateway serves -- `openai`, `anthropic`, `gemini`,
`openrouter` -- each a reference to a key by name in the product's Doppler
config, the last two optional. A customer's policy may still name a provider
outside that list, with the consequence the next paragraph describes.

What the two decisions already made there mean for a product: there is no
platform default provider, so a configured platform holding no policy for
an alias refuses that alias for that customer; and providers are free text,
so a policy may name a provider the product's gateway does not serve, which
the runtime skips, and a policy naming only such providers is a
configuration error for that customer rather than a fall-through to the
default.

### What the product does with silence

A platform configured and not answering is a refusal for AI, for both
routes. A product with no platform configured runs on its own catalogue,
ungated, which is the bootstrap order.

## What the platform would need to offer

Each is a requirement, with the reason and the product-side seam it would
plug into. None is built here.

### A configuration route

One read per product per organization carrying everything the runtime
resolves today from two routes and its own settings:

```text
GET /api/portal/v1/products/{code}/ai-configuration

{
  "enabled": true,
  "providers": [
    { "name": "openai",    "secret_ref": "OPENAI_API_KEY" },
    { "name": "anthropic", "secret_ref": "ANTHROPIC_API_KEY" }
  ],
  "aliases": {
    "koras-balanced": { "providers": ["anthropic", "openai"], "model": "claude-3-5-sonnet" }
  },
  "limits": { "monthly_requests": 5000, "requests_per_minute": 60, "monthly_budget_cents": null },
  "tools": { "enabled": true, "denied": ["files.delete"], "approval_required": ["files.rename"] },
  "agents": { "assistant": { "model": "koras-fast" } },
  "prompts": { "assistant.system": { "version": 2 } }
}
```

A secret reference is a name in the product's Doppler config and never a value.
The product-side seam is `RoutingSource` and `Limits` in
`python-packages/koras-ai/src/koras_ai/config.py`: a second source reading
this route replaces `ControlPlaneRouting` and fills `Limits` without the
runtime changing.

### Tool policies

A platform-side deny list and an approval-required list per organization,
as above, so a customer's security team can forbid a tool the product ships
without the product redeploying. The seam is `visible_tools` and `decide` in
`python-packages/koras-ai/src/koras_ai/policy.py`, which would take the
policy as a further input and never a weaker one: the platform can add
approval and cannot remove it.

### Usage reporting

A write from the product, per calendar month or per day, of what
`ai_usage_events` holds aggregated by alias and provider, so the platform
can bill and show a customer their consumption:

```text
POST /api/platform/v1/products/{code}/organizations/{org}/ai-usage
```

This is the one call that would need a machine identity, which a product
does not hold at runtime by decision (FOLLOW_UPS F2b). Until that is
resolved, usage stays in the product's database and is read there.

### A budget

The monthly budget above, resolved by the platform from a price list per
provider and model that the product never sees. The runtime meters calls,
not money; a budget needs the platform to say what a call cost.

### Prompt versions

Which version of a product's registered prompts a customer runs, so a
prompt can be promoted per organization before it is promoted for all. The
seam is `PromptRegistry.get` with a version.

### An audit sink

The Control Plane already owns an audit domain. A product's AI audit events
could be forwarded there through the registration relationship, with the
same identity question as usage reporting.

## What the platform must never do

- Hold a provider key value. References by name only, as it does for
  storage.
- Route a customer's data to a provider nobody chose. No platform default
  provider; a missing policy is a refusal.
- Call a model. Enforcement and execution are the product's.
