# CAT-03 — Stripe product and price provisioning

| | |
|---|---|
| **Category ID** | CAT-03 |
| **Feature name** | Commercial catalogue to provider provisioning |
| **Owner** | CAT-03 lead |
| **Written** | 2026-09-19 |
| **Status** | Phase 0 built and Phase 1 mostly built, 2026-09-19. Phases 2 to 4 planned |
| **Read first** | `docs/platform/master-platform-plan.md` §5.1, §7, §9.4; `docs/BILLING_DESIGN.md`; and in `koras-control-plane`, its billing document, its commercial catalogue document and its go-live runbook |

## The finding that defines this category

**This is not a starter category.** All billing code lives in
`koras-control-plane`. The starter holds the design document, the signup and
checkout frontend templates, the entitlement reader, and a `packages/billing`
that is three lines long and which `docs/BILLING_DESIGN.md` says may be removed.

That is a decision, not an omission. The same document states that no product
ever holds a provider credential and no product ever calls the provider.
Applying the starter-first rule here would put a payment secret in every
generated repository, so the rule is set aside for this category and the reason
is recorded in the master plan §5.1 rather than left to be rediscovered.

**The ownership principle stands unchanged.** The Koras product catalogue is the
system of record. The provider holds a representation of it. Provisioning writes
one direction only.

## Objective

Make the commercial catalogue able to create and maintain what it describes at
the provider, deterministically and idempotently, and to detect when the two
have drifted — replacing a manual sequence in which a person creates a product
and its prices in a dashboard and pastes the ids into a console form.

## Repository scope

| Repository | Allowed | What |
|---|---|---|
| `koras-control-plane` | **Yes — owner** | Everything in this category |
| `koras-saas-starter` | Yes, Phase 0 only | Two documentation corrections |
| `docoris` | **No** | Validation against a real product may be offered later and is not in this plan |
| Any product repository | **No** | No provider credential, no price id and no amount may reach one |

## Dependencies

| Dependency | Class | State |
|---|---|---|
| Koras product catalogue — plans, entitlements, subscriptions | HARD | Satisfied |
| Provider adapter, a protocol naming no vendor | HARD | Satisfied; two operations to add |
| Environment guard — a live key refused outside production | HARD | Satisfied; the provisioner inherits it |
| Reconciliation engine with a check registry and a repair policy | HARD | Satisfied |
| Audit | HARD | Satisfied |
| Webhook and event log | OPTIONAL | Provisioning is outbound; they meet only at the subscription row |
| Terraform | **Not a dependency, deliberately** | No Terraform in either repository manages the provider, and none should |
| Generator provisioning | **Not a dependency, deliberately** | The registration payload carries no commercial field. Adding one would put pricing in a product repository |
| CAT-01 notification contract | SOFT, OPTIONAL | Implemented there against the contract; the Control Plane is not code-synced |
| Live mode | Not a code dependency | `docs/FOLLOW_UPS.md` F21: a person at a dashboard |

**Hard blockers: none.** This category can start immediately, in parallel with
everything else, in a repository nothing else in this plan touches.

## Shared contracts

**The billing catalogue contract (§9.4).** The Koras catalogue is the system of
record. A lookup key is derived deterministically from product, plan, interval
and currency. The provisioner creates and updates; **it never deletes**, and it
never reads the provider as truth. Reconciliation classifies every finding as
safe to repair automatically, requiring review, or manual.

## Phases

### Phase 0 — Corrections

Four claims that the two repositories make and cannot support:

- The starter's billing design records Phase 3 as never run in a browser and the
  test-mode catalogue as absent. Both stopped being true on 2026-09-15
  (**BILL-DEF-003**). Correct it, or make it point at the Control Plane's
  document rather than restate it — the second is better, because one fact in
  two documents is how they come to disagree.
- The Control Plane's self-serve signup document says in its header that nothing
  in it is built. It has run six times in a browser (**BILL-DEF-004**).
- The two entitlement-seeding migrations granting against a renamed plan code
  (**BILL-DEF-002**) — recorded here, fixed in Phase 1.
- The split entitlement catalogue (**BILL-DEF-001**) — recorded here, fixed in
  Phase 1.

### Phase 1 — Lookup keys, idempotency, one catalogue

**1a — Deterministic lookup keys (BILL-GAP-001).**
A key per product, plan, interval and currency, minted by the catalogue and sent
on price creation. Prices stop being addressed by a hand-pasted opaque id. The
currency segment is present **from the first key**, before multiple currencies
exist, so that Phase 3 is additive rather than a re-key.

**1b — Outbound idempotency (BILL-GAP-002).**
An idempotency key on every outbound provider call, derived from the operation
and its subject. Inbound idempotency is already sound — the event id is stored
before the event is acted on — so this closes the one-directional gap. Without
it a retried checkout can create a second subscription for one customer, which
is a money defect rather than a data defect.

**1c — One entitlement catalogue (BILL-DEF-001, BILL-DEF-002).**
The five reporting entitlements exist in a migration and not in the in-code
catalogue that seeds a newly registered product, so a product registered today
is not granted the reports it ships with — and nothing goes red, because an
ungranted entitlement looks exactly like a plan that does not include it. Two
sources become one, or the seed reads the table. The renamed plan code is fixed
in the same pass, since it is the same class of defect.

**Exit:** a newly registered product resolves every entitlement its plan should
grant, asserted by a test. A retried checkout creates one subscription.

### Phase 2 — The provisioner and catalogue drift

**2a — The provisioner (BILL-GAP-003).**
Read the Koras catalogue; for each active plan, ensure a provider product and a
price per interval and currency exist and match. Three outcomes, and only three:

| Situation | Action |
|---|---|
| Exists and matches | Reuse. Write nothing |
| Absent | Create, with the lookup key and the idempotency key |
| Exists and the configuration changed | **Create a new version**, archive the old appropriately, update the active mapping |

Never mutate the meaning of an existing recurring price. A dry run is the
default, and an apply is explicit — the same shape as the generator's Terraform
runner, which never auto-applies.

**2b — Catalogue drift detection (BILL-GAP-004).**
A second check in the reconciliation registry, beside the subscription check
that already runs every fifteen minutes. Detected conditions: a catalogue price
with no provider price; a provider price with no catalogue mapping; a mismatched
amount, currency or interval; an archived product still referenced; an inactive
price still sold; a duplicate lookup key; a resource in the wrong environment.

Classified, never silently repaired:

| Class | Example | Policy |
|---|---|---|
| Safe to repair | The catalogue holds no mapping for a price the lookup key identifies unambiguously | Automatic |
| Requires review | An amount mismatch | Reported, repaired on approval |
| Destructive or manual | An archived provider product still sold by an active plan | Reported only. **Never automatic** |

**No provider resource is ever deleted to repair drift.** The engine's existing
policy vocabulary already distinguishes automatic from manual repair; this adds
a check, not a second engine.

### Phase 3 — Versioning, currencies, the free plan

- **Price versioning and grandfathering (BILL-GAP-005).** The mapping becomes a
  history rather than a column pair: which price was active when, and which
  subscriptions were sold at it. Existing subscriptions keep their price at the
  provider regardless, so the exposure being closed is the catalogue's memory of
  what was sold rather than the amount charged — worth stating precisely,
  because it sets the urgency.
- **Migrating a subscription to a new price is a separate, controlled
  operation**, never a consequence of publishing a new price.
- **Multiple currencies (BILL-GAP-006).** A price set per currency, keyed by the
  Phase 1 lookup key that already carries the segment.
- **The free plan and the custom price (BILL-GAP-009).** Decide whether a free
  plan is a plan with a zero price or a plan that skips checkout, and whether an
  enterprise custom price is a catalogue row at all. The existing fallback —
  provisioning with no card when a plan has no price — is the current answer by
  accident rather than by decision.

### Phase 4 — Console and go-live

- A console view over the billing event log (**BILL-GAP-007**): the API lists
  events and nothing renders them.
- Provisioning diagnostics: what the provisioner would do, what it did, what
  drifted.
- The go-live runbook exercised: activate the account, build the live catalogue
  **through the provisioner rather than by hand**, mint a narrow live key,
  register the production webhook endpoint, configure the customer portal, and
  sign up once with a real card. This half is `docs/FOLLOW_UPS.md` F21 and is a
  person at a dashboard; Phases 1 to 3 do not wait for it.

## User stories

| ID | As a | I want | So that | Phase |
|---|---|---|---|---|
| BILL-US-001 | billing administrator | a price created from the catalogue rather than the dashboard | the two cannot disagree by a typo | 2 |
| BILL-US-002 | billing administrator | to see what provisioning would do before it does it | I am not learning from the result | 2 |
| BILL-US-003 | billing administrator | to re-run provisioning safely | a failed run is retried, not feared | 1, 2 |
| BILL-US-004 | billing administrator | to be told when the catalogue and the provider disagree | I find it before a customer does | 2 |
| BILL-US-005 | billing administrator | to raise a price without changing what existing customers pay | a price change is not a repricing | 3 |
| BILL-US-006 | billing administrator | to sell in more than one currency | a European customer sees euros | 3 |
| BILL-US-007 | platform administrator | a newly registered product granted the entitlements its plan includes | a customer is not missing features nobody can see are missing | 1 |
| BILL-US-008 | platform administrator | a retried operation not to create a second provider object | one customer is billed once | 1 |
| BILL-US-009 | platform administrator | development never to reach live mode | a test never charges anyone | 1, 2 |
| BILL-US-010 | support user | to see the delivery and outcome of each billing event | I can answer what happened to this subscription | 4 |
| BILL-US-011 | billing administrator | a free plan that works through the same path | the exception is not a special case in the code | 3 |
| BILL-US-012 | security reviewer | every provisioning action audited | a change to what we sell is attributable | 1 |

## Acceptance criteria — the ones that decide the phase

- **P1.** Two identical checkout calls with the same key create one provider
  object. Every price the provisioner creates carries a lookup key derivable
  from the catalogue alone. A newly registered product resolves every
  entitlement its plan grants, including the reporting ones.
- **P2.** Provisioning twice creates nothing the second time. A changed amount
  produces a new price and leaves the old one addressable. A drift finding is
  classified, and a destructive one is never repaired automatically. A dry run
  writes nothing at the provider.
- **P3.** A subscription sold at the old price still resolves the old price after
  a new one is published. A currency added produces a new price and no change to
  any existing one.
- **P4.** The go-live runbook is executed and its result recorded with a verdict.

## Security requirements

- **The environment rule is the first control.** Development, test and staging
  reach test mode; only production reaches live. The guard that refuses a live
  key outside production and a test key inside it already exists at construction
  and must be inherited by the provisioner, not re-implemented beside it.
- **Production is stronger.** A live apply is explicit, audited and attributable
  to a named person, not a scheduled sweep.
- The provider secret and the webhook secret stay in the Control Plane's Doppler
  and reach no product repository. The starter names them only to say so.
- **No amount is stored in any table.** The catalogue holds references; amounts
  are read from the provider and cached briefly. Phase 3 does not change that.
- Every provisioning and reconciliation action is audited, with the outcome, and
  never with a credential-shaped detail key.
- A drift repair that would delete or archive a provider resource is manual, and
  the policy says so rather than a reviewer remembering.
- Rate limits and provider failure handling: a provider outage renders the
  pricing page as "price at checkout" rather than a 500, which is the existing
  behaviour and must survive the change.

## Database impact

`koras-control-plane` only, in its own migration sequence. Phase 1 adds lookup
keys to the plan price mapping and reconciles the entitlement catalogue. Phase 3
turns the price mapping into a history. No product migration in any repository.

## APIs

Control Plane internal and console routes only. **No new product-facing route,
and no addition to the product platform contract**, which carries no billing
endpoint by design — entitlements reach a product only through the plan push
and the portal read.

## UI impact

The Control Plane console: the plans page gains provisioning status and a dry
run; a new page over the event log; drift findings surfaced in the existing
reconciliation surface rather than a second one.

## Background jobs

The catalogue drift check joins the existing fifteen-minute estate sweep. The
provisioner is invoked explicitly, not on a schedule — a sweep that creates
priced objects is a sweep that can spend money.

## Testing

| Kind | What |
|---|---|
| Unit | Lookup key derivation; idempotency key derivation; the three provisioner outcomes; drift classification |
| Integration | Provisioning twice creates once; a changed amount versions rather than mutates; entitlement resolution after a fresh registration |
| Replay | The recorded provider fixtures already in the repository, extended with product and price responses |
| Security | A test key in production and a live key outside it, both refused; a destructive drift finding never auto-repaired |
| Regression | The existing subscription drift check keeps working; the pricing page still degrades rather than failing |

**No test in any phase calls live mode.** The recorded fixtures and the test-mode
account are what automated tests use.

## Manual QA

The go-live runbook is the manual test plan for Phase 4, and it is a sequence
only a person can execute. Verdicts recorded as **NOT EXECUTED** until they are.

## Migration, rollout, rollback

- **Rollout.** Phase 1 is invisible to customers. Phase 2's provisioner is a
  console action, off until used. Phase 3 changes a data model and needs a
  backfill of the existing mappings into the history.
- **Rollback.** Phases 1 and 2 roll back cleanly — provider objects created are
  left in place, correctly, since deleting them is the thing this category never
  does. Phase 3's history is additive and its backfill is re-runnable.

## Cross-repository sync

None. The Control Plane is not code-synced from the starter, and this category
produces nothing the starter needs. The only starter change is Phase 0's
documentation correction.

## Definition of done

As CAT-01, scoped to this repository, plus: a dry run reviewed by a second
person before the first live apply; the go-live runbook executed and recorded;
and the entitlement catalogue proven single by a test that fails if a code
exists in one source and not the other.

## Known gaps and defects

BILL-GAP-001 to 009 and BILL-DEF-001 to 004, in
`docs/platform/gap-defect-register.md`.

## Next three features, after this category

1. Usage-based billing, which the provider's managed-payments mode forbade as
   of 2026-09-15 by the mechanisms this estate would use — three options are
   written down in the Control Plane's billing document and none is chosen.
2. Coupons and trial extensions, which the catalogue has no model for.
3. Invoiced enterprise terms, which is the one commercial shape the self-serve
   path cannot express.
