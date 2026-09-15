# ADR 0002 — Koras Reporting Framework

**Status.** Accepted 2026-09-14.

**Context.** Three audiences need reports: KORAS staff over the estate, a
customer's administrators over their organization, and the same people over
a product's own domain. Nothing answered any of them. Two placeholder modules
demonstrated plan gates and rendered nothing; the only aggregate queries fed
the AI collector. Without a shared layer each product would write its own
pages, decide its own authorization, and compute the same metric three ways.
The starter already holds the tenant, permission and entitlement models every
product inherits, and a navigation registry resolved from them.

**Decision.**

1. *Reporting belongs in the starter, as the capability `reporting`, on by
   default.* The registries, the resolver contract, the authorization rule,
   the router, the pages and the components are generated into every
   product; a product adds definitions and never rebuilds the infrastructure.
2. *One framework for all three levels.* `koras_reporting` lives in the
   shared template layer so the Control Plane describes a platform report
   with the same types a product uses for a tenant report. The queries
   differ; the contract does not.
3. *Definitions are code, not rows.* A report and a metric are registered at
   import, the way agents, tools and navigation modules are. Only runtime
   state gets a table, and today reporting has none beyond the audit rows it
   writes.
4. *Every report is server-authorized and every tenant report is
   tenant-scoped.* Visibility is decided in the API from the verified token's
   permissions and the platform's entitlements before a resolver runs, and
   every resolver runs on the tenant session under forced row-level
   security. The web tier renders a decision; it never makes one.
5. *Filters are typed, declared and bound.* A report names the filters it
   accepts and their kinds; anything else is refused; values reach a query
   only as bound parameters. There is no free-text filter.
6. *Entitlements control premium reporting.* Five dotted codes in the
   platform's catalogue, read the way every entitlement is read. An
   unresolved plan shows the basic reports and refuses export.
7. *Calculations are never in React.* The API answers numbers with units;
   components format them. A metric key means one thing everywhere.
8. *No chart library.* Line and bar charts are inline SVG in `packages/ui`,
   with a table equivalent beside every chart. The repository draws its own
   icons for the same reasons: no dependency, no client bundle, no runtime
   fetch, and accessibility that is ours to guarantee.
9. *Revenue is derived and labelled, never stored.* MRR is live
   subscriptions times the provider's price; invoiced revenue is the paid
   invoices the webhook already stored. `docs/BILLING_DESIGN.md` stands.
10. *Products own their domain.* The shop's tables, seed and reports are in
    `koras-e2e-shop` and nowhere in the starter.

**Consequences.** The framework is Python, in the API, because that is where
the tenant session and the trusted checks already are. The placeholder
`reports` module is replaced by `analytics`; `insights` remains as the
hidden-module example. A product generated without the capability carries
none of the routes, pages or tests. A general `audit_events` table arrives
with reporting because exports and sensitive views have to be recorded and
nothing durable existed outside the assistant. CSV is the only export;
scheduled delivery is scaffolded; pre-aggregation waits for a volume that
needs it. Every derived figure in the Control Plane says it is derived.
