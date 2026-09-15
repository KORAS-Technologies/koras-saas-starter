# Product Domain Agent Framework

The starter ships the **contract**, the **template** and an **example**. It
ships no domain facts, and it never will: the 40 shared engineering agents are
identical in every KORAS product, and a business rule baked into one of them
would be wrong in every other product that inherits the same agent.

## What the starter provides

| File | Status |
|------|--------|
| `README.md` | This contract |
| `DOMAIN-AGENT-TEMPLATE.md` | Template to copy when creating a domain agent |
| `DOMAIN-REVIEW-CONTRACT.md` | What a domain review must establish |
| `domain-registry.example.yaml` | Example registry, not read at runtime |

## What the product creates

Everything else. Nothing below exists until the product creates it, and their
absence is not an error — a product with no domain layer simply has no domain
gate.

```text
.claude/domain/
  domain-registry.yaml          <- product-created, copied from the .example
  <domain>/                     <- one directory per domain
    domain-expert.md            <- copied from DOMAIN-AGENT-TEMPLATE.md
    knowledge/*.md              <- authoritative domain notes
```

One directory per domain, named for the domain the product actually has — for
a document-management product that might be `documents/`, for a practice
product `matters/`, for a policy product `policies/`:

```text
.claude/domain/<domain>/domain-expert.md
.claude/domain/<domain>/knowledge/<topic>.md
```

A product may define one primary domain expert and any number of specialists.

The starter names no real product here, on purpose. A product name in the
shared template is the beginning of the coupling this directory exists to
prevent.

## Naming convention

Files the starter ships that are **examples or templates** carry `.example` or
`TEMPLATE` in the name. Anything without that marker is expected to exist at
runtime. This is the rule that makes a dangling reference detectable: a
reference to a non-`.example` path that no product has created yet is
documented as product-created, here and at the reference site.

## What a domain agent does

- Advises the Business Analyst, Product Planner and Solution Architect on
  domain correctness during planning.
- Independently validates domain-heavy features against the business rules.
- Cites its sources from the product's own documentation, and flags uncertainty
  rather than inventing a rule.

## What a domain agent does not do

- It does not implement production code in the normal case.
- It does not replace the generic engineering gates. A feature that is
  domain-correct and insecure is not done.
- It does not appear in `.claude/orchestration/agent-registry.yaml`. Domain
  agents are product-owned overlays; the shared registry stays domain-neutral.

## Registration

The product's `domain-registry.yaml` tells the Orchestrator which domain agents
exist and when to activate them. Until it exists, the domain review gate simply
does not apply.
