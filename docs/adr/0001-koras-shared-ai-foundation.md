# ADR 0001 — Koras Shared AI Foundation

**Status.** Accepted 2026-09-13. The first record in this directory; the
format is the one this file uses.

**Context.** Several products are planned that will each want an assistant,
agents, tools and retrieval. Without a shared layer each would call a
provider from its own code, hold its own keys, meter nothing, and decide
authorization in whatever way its author chose. The starter already holds
the tenant, permission and entitlement models every product inherits, and an
optional gateway that holds provider keys.

**Decision.**

1. *AI belongs in the starter.* The runtime, the provider boundary, the
   registries, the approval workflow and the meter are generated into every
   product that asks for the `ai` capability, so a product adds agents and
   tools and never rebuilds the infrastructure.
2. *Providers are abstracted, and the gateway is the only one.* Product code
   never imports a vendor SDK or holds a vendor key. The runtime speaks the
   OpenAI-compatible protocol to the LiteLLM gateway, which holds the keys
   and lists the models.
3. *Product code names aliases.* Five aliases, resolved to gateway model
   names by a catalogue the product owns and overridden per customer by the
   platform's routing policy. A vendor model name in product code is refused
   by a test.
4. *The Control Plane owns centralized configuration.* Entitlements and
   routing are the platform's, read with the customer's own token. A silent
   platform is a refusal; no platform is the bootstrap order.
5. *Doppler owns secrets.* Provider keys and the gateway's master key live
   there and reach the gateway and the API as settings. No table, manifest
   or generated file holds a value; the platform stores references by name.
6. *Products own their domain.* Agents, tools, prompts and knowledge sources
   are declared in a generated extension point in the product. The starter
   ships one generic assistant and one read tool and nothing of any product.
7. *Tools use deterministic permission checks.* A tool declares the product
   permission it needs and its operation class; the runtime checks the
   permission against the verified roles and never reads the model's output
   to decide. Unregistered tools are refused by name.
8. *Human approval is required for sensitive actions.* Write, destructive
   and external operations become an action a person approves, in a state
   machine that refuses a skipped step; destructive operations need an owner
   or administrator. A tool may add approval and cannot remove it.

**Consequences.** The runtime is Python, in the API, because that is where
the tenant session and the trusted checks already are; the web tier is a
surface over it. Every AI table is tenant-scoped and RLS-forced. A product
without the capability carries none of the routes, tables or pages. Usage
is metered per call in the product's database until the platform offers a
place to report it. Streaming, approval notification, a vector store and
retention are staged, not built. The first real model call through a
deployed gateway is the next thing to do, and nothing is extended before it.
