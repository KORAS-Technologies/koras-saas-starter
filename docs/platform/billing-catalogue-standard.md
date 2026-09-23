# The standard billing catalogue — audit, architecture and plan

| | |
|---|---|
| **Written** | 2026-09-22 |
| **Status** | Phase 1: inspection and architecture. **No implementation beyond what is recorded under "What already exists in the working tree" below.** |
| **Repositories** | `koras-saas-starter` (owner of the catalogue declaration and the provisioning command), `koras-control-plane` (owner of the platform catalogue representation) |
| **Read first** | `docs/platform/execution/CAT-03-stripe-billing.md`, `docs/BILLING_DESIGN.md`, and in `koras-control-plane`, its billing, commercial catalogue and go-live documents |
| **Written for** | The platform owner deciding this, and the engineers who will build it. It assumes the two repositories but not this week's context. |

## What this is

A request to make "create a product, then sell it" one reusable platform
capability, with a standard commercial structure every product inherits and can
override without touching provisioning code.

This document is the inspection that had to come first, the architecture it
implies, and the plan. It is deliberately more about **what does not fit** than
about what does: eight of the ten pieces the request assumes are already there,
and the value of an audit is in the two that are not.

## The headline

**Three of the requirements cannot be met by a catalogue at all**, because they
are not catalogue problems. They are named here rather than absorbed quietly
into a plan that would then appear to deliver them. The first was reassessed on
2026-09-22 once the pricing model was clarified, and it shrank:

1. **The seat count is wired to the exact inverse of the intended model.**
   Clarified 2026-09-22: a plan is a **flat fee including a number of users** —
   $99 for three — and not a price per seat. The seat count is sent to the
   provider as the subscription's quantity, so Starter at $99 with five seats
   bills **$495**. It multiplies the price, which it must not.

   **Corrected 2026-09-22, before Phase 2 began.** The first version of this
   document said the seat count was also enforced nowhere, and that is wrong.
   `_refuse_beyond_the_seats` in the Control Plane's portal router refuses a
   member the subscription has no seat for, takes the *smallest* seat count
   across the products an organization holds because a member is a member of
   all of them, skips a product with no subscription and one whose
   subscription is over, and says which product and how many. It is careful
   work and it was there all along.

   The claim came from searching the entitlement modules, where seat
   enforcement would plausibly live and does not, and concluding from their
   silence. That is inference from absence presented as a finding, which is
   the failure this repository keeps a register for — and it reached a
   committed document and the file every session reads first before a search
   of one more router found it.

   **The correction makes Phase 2 smaller rather than larger**, which is the
   part worth acting on: the enforcement half is built and correct, so the
   work is to stop the quantity multiplying the price and to make the seat
   count come from the plan rather than from a number the customer types.

   **This is the smaller half of a fix, not a rewrite** — see the revised
   ordering below. The quantity becomes one, permanently; the seat count
   becomes state this platform keeps rather than a number read back from a
   provider; and the included-user count becomes an enforced limit of exactly
   the shape storage already uses. No second subscription line and no proration
   work is needed to make a plan correct and sellable.

   **What it does mean is an ordering change.** Provisioning a price is what
   *arms* this defect. Until a plan has a price reference nothing can be sold
   self-serve at all, so the overcharge is latent; the moment a catalogue
   writes $99 onto Starter, the signup page can sell it and will multiply it.
   The correction therefore comes **before** provisioning rather than after,
   and the two are one piece of work rather than a defect and its later fix.
2. **Per-product limits have no home.** Included storage and AI allowances are
   platform-wide constants shared by every product, so the Docoris table in the
   request — 10 GB on Starter — cannot be expressed at all today, where every
   product's Starter is 5 GB.
3. **There is no plan versioning.** As of 2026-09-22, grandfathering is
   implicit in the fact that an old provider price keeps existing. That works,
   and is not modelled, and nothing can answer "what did this customer agree
   to".

Everything else — registration, ordering, idempotency, reconciliation,
environments, secrets, entitlement sync — is either already built or is a
modest extension of something built.

## What already exists in the working tree

Before the standard above was specified, a first cut of the provisioning step
was built in this repository on 2026-09-22, from an earlier and narrower brief.
It is **staged and uncommitted**. It is described here because a plan that
ignored it would be planning against the wrong starting point.

What it does: a generator flag that reads a catalogue file from the generated
project, creates a provider product and a price per declared interval, and
writes the price references and the recorded intent onto the product's plans in
the Control Plane. It refuses a live provider key outside production, refuses a
plan code the Control Plane does not hold, never deletes or archives a price,
and resolves a changed amount by creating a second price and moving the lookup
key. Forty-one tests drive it against a fake estate; four assertions were
mutation-checked.

**Three things in it conflict with the standard now specified**, and are
addressed in the plan rather than defended:

| Built | Standard requires | Resolution |
|---|---|---|
| Lookup keys are dot-separated and carry a currency segment | Underscore-separated, product-prefixed, no currency: product code, plan, interval | Adopt the standard. The currency segment was insurance against a second currency; the standard's stability requirement outranks it. A second currency becomes a second key rather than a re-key, which is what the segment was protecting against and is an acceptable cost |
| The catalogue file is generated **empty**, and provisioning refuses it | Platform-standard defaults, overridable per product | Adopt the standard. The empty file existed because no defaults had been decided; they have now |
| Prices only. No included users, storage, entitlements, add-ons or versioning | All of those | Extend the schema. See below |

## 1. The existing product-registration workflow

A product registers itself with the Control Plane after `terraform apply`, from
the generator's registration module, and — where a repository variable enables
it — again after each deployment, from a script in the shared template. The
deploy-time job is off by default, because the only identity that can register
today is the estate-wide registrar, and putting it in one product's CI gives
that product write access to every other product's registry entry.

What authorises it is the registrar service-account key from Doppler, from
which the generator mints a token per call. The address comes from Doppler.
An unconfigured Control Plane is a **skip**, not a failure — the documented
bootstrap order — while a misconfigured one is a failure.

**The response carries the Control Plane's product id**, and has since
2026-09-15, along with the stored references read back inside the registration's
own transaction. So the identifier the request wants in provider metadata is
already available to the caller at exactly the moment it is needed, with no
second lookup.

**Registration already seeds the plan catalogue.** Every registered product
receives four plans — starter, pro, business, enterprise — and the platform
entitlement catalogue, both inserted on-conflict-do-nothing so an administered
estate is never reset. A worker backfill does the same for products registered
before those existed.

## 2. The existing provisioning pipeline

Ten steps today, of which the runbook documents nine and the tenth is the
subject of this document:

1. Preflight checks.
2. Generate.
3. Provision infrastructure, then register.
4. Retry after partial failure, which skips generation and keeps state.
5. Create the restricted database role, once per environment.
6. See what Doppler will be asked for.
7. Populate Doppler for dev, test and stg, then prod separately.
8. Confirm every environment holds every setting.
9. *(new)* Provision the commercial catalogue.

Terraform never auto-applies. The generator never silently overwrites. A
registration failure never unwinds infrastructure. These are the constraints any
new step inherits.

**There is no hook mechanism**, and there does not need to be one. The CLI calls
the registration step and receives a report that distinguishes registered from
skipped from failed. Gating a billing step on that report is four lines at one
call site, and it is the only call site. A generic hook registry would be a
second framework for one subscriber.

## 3. The existing provider architecture

All of it is in `koras-control-plane`. The starter holds the design document,
the signup and checkout frontend, the entitlement reader, and a three-line
package the billing document says may be removed.

That is a decision, not an omission: no product ever holds a provider
credential and no product ever calls the provider. The starter-first rule is
set aside for this category for that reason.

What the adapter can do today: read prices, create checkout sessions, create
and update subscriptions, drive subscription schedules, verify webhooks. It
carries an environment guard that refuses a live key outside production. **It
cannot create a product or a price** — those two operations are the gap.

Amounts for the pricing page are fetched live and held for ten minutes, so the
provider is not a dependency of the homepage. The request's requirement that
the Control Plane not need live provider calls to render a catalogue is
therefore **not met today** for amounts, and is met for everything else.

## 4. The existing plan and catalogue architecture

The plans table, built up across four migrations, holds: id, product, code,
name, status, self-serve flag, the two provider price references, seat bounds,
and — since 2026-09-20 — the expected monthly and yearly amounts and currency,
which are an *intent* compared by reconciliation and rendered nowhere.

Entitlements are three tables: a catalogue of capabilities, what each plan
grants, and per-subscription overrides. Resolution reads subscription status,
trial end and the grace window, so a cancelled customer resolves nothing.

**The plan catalogue and the entitlement catalogue are Python constants in a
shared package**, imported by both services precisely so there is one answer to
what plans a product has. Plan limits — storage in gigabytes, AI requests per
month — are a dictionary keyed by entitlement code then plan code.

**That dictionary is the per-product gap.** It is not keyed by product, so every
product's Starter includes the same storage. The *data model* underneath is
per-product, because a plan entitlement row points at a plan which points at a
product. Only the seeding is global.

## 5. The best insertion point

Immediately after the registration step reports success, at the single call site
in the generator CLI, and also reachable as a standalone flag on an existing
project.

The reasons this is the right seam rather than a convenient one:

- Registration is what **creates the plans** the catalogue writes onto. Before
  it, there is nothing to price.
- Doppler bootstrap is what supplies the credentials. Before it, there is
  nothing to authorise with.
- The registration report already distinguishes the three outcomes, so "do not
  provision billing if registration failed" is expressible without inventing a
  state machine.
- The same function serves the automatic path, the manual re-run, recovery and
  CI, because it takes a project directory and a product code and nothing else.

## 6. Recommended CLI option

**A distinct flag, not a capability.** The recommendation is the flag that
already exists in the working tree, plus an opt-out.

**Do not use `--with billing`.** A billing capability already exists in the
product manifest and gates a package in the generated tree. Overloading it would
mean one word selecting both a code path in the product and an action against a
payment account, and `--without billing` would silently mean two things.

The flag follows the conventions of the two existing flags that operate on an
already-provisioned project: neither implies infrastructure work, both read what
is on disk, both refuse a project directory that is not there.

For the manual command the request asks for, the recommendation is **not** to
add a second implementation in the other CLI. The generator flag already
operates on an existing project by directory, which is what the manual case is.
A second entry point would be a second thing to keep correct. If a shorter alias
is wanted later it should delegate, not reimplement.

## 7. The billing configuration schema

YAML in the generated project, beside the project manifest, because that is
where the project's own declarations already live and it is what a diff reviews.

**Amounts in minor units, with the field named so nobody has to remember.** The
request's example shows 99 for $99. Ninety-nine minor units is ninety-nine
cents. This is the factor-of-a-hundred error, and it is the version that
survives review because the number looks plausible either way. The
recommendation is that the file carries minor units and says so in the key name
itself, so that a reader who knows nothing still reads it correctly.

The schema must carry, per plan: the two amounts, the number of included
internal users, the per-product limits (storage, AI, API, workflows — an open
map rather than fixed keys, so a product with a limit nobody anticipated does
not need a schema change), the entitlement grants, and a plan version. At the
file level: currency, tax code, catalogue version, and the additional-user
amounts.

**Enterprise is declared as custom and produces no price.** It is on the
catalogue as the tier to ask about, and a price nobody can buy would be a
catalogue entry that misleads.

**The defaults ship filled in**, with the standard structure, because the
platform now has one. The first cut shipped an empty file on the grounds that a
product does not know what it costs; that reasoning was correct when no standard
existed and is wrong now that one does. Overriding is editing a number.

## 8. Control Plane catalogue sync design

Two options, and the recommendation is the second.

**Extend the plans table.** Add included users, the additional-user price
references, a plan version, effective dates, a catalogue version, and a limits
map. Cheapest, and it puts a growing amount of commercial structure into a table
whose stated job is to be an entitlement bundle.

**A catalogue table beside it, and plans keeps its job.** A plan stays the
entitlement bundle a subscription points at; a catalogue row is a *version* of
what that plan costs and includes, effective between two dates, carrying the
provider mappings. Grandfathering becomes a question with an answer: the
subscription points at a plan, the catalogue says which version was effective
when it started.

The second is recommended because plan versioning and grandfathering are
explicit requirements, and bolting effective dates onto a table with a unique
constraint on product and code cannot express two versions at once.

**Per-environment mappings need no new mechanism.** Each environment has its own
Control Plane database, so a price reference stored in the dev database is a dev
price by construction. The requirement is already met by the deployment
topology, and a column naming the environment would be a second answer able to
disagree with the first.

**Entitlement sync** uses the two write endpoints that already exist, one
defining a capability and one setting what a plan grants. No new surface.

## 9. Idempotency strategy

Four questions, four answers, none of them new invention:

| Question | How it is answered |
|---|---|
| Does the provider product exist? | Addressed by a **deterministic id**, so it is a direct read. Not by search — the provider's search index is eventually consistent, so a provisioner that searched would duplicate on a quick re-run |
| Does the price exist? | Looked up by its stable lookup key |
| Is it the right amount? | Compared. A provider price is immutable in amount, so a difference creates a **new** price and moves the lookup key; the old one is left active and unreferenced, never deleted or archived |
| Does the Control Plane already hold the mapping? | Read back before writing, and the write is skipped when nothing would change |

**Outbound idempotency keys** go on every create, derived from the operation and
its subject — **including the amount**, because the same plan at a corrected
amount is a different operation and must not replay the first attempt's answer.

**A hazard worth stating once.** The plan write endpoint is an upsert that
overwrites the whole row, including name, self-serve and seat bounds. Anything
writing to it must read the row first and round-trip every field it does not
own, or pricing a plan silently resets somebody's administration.

## 10. Recovery and re-run strategy

The partial-failure case in the request — Starter and Professional succeed,
Business fails — is handled by the idempotency above rather than by a state
machine, and that is the recommendation.

A re-run finds Starter's and Professional's prices by their lookup keys, creates
nothing for them, writes nothing to the Control Plane for them, and retries
Business. There is no partial state to record because the provider *is* the
record: an object either carries the lookup key or it does not.

**What must be added is the report**, not the state. Every outcome is printed
per plan and per interval — created, reused, superseded — so an operator can see
which half succeeded. A summary count is not something anybody can check.

Audit history lives in the Control Plane, which already records a plan change as
an audited event.

## 11. Migration strategy for existing products

Docoris and Lexveria are registered and have the four plans. They need the
catalogue file, filled in, and one run of the command.

**The steps are written down** rather than left to be reconstructed:
`docs/PROVISIONING_RUNBOOK.md`, under "Provisioning the catalogue for a product
that already exists". The one thing that differs from a new product is the
first step — the catalogue file is generator-written, so a product generated
before it existed has to be given one with `--refresh`.

**Docoris needs something else first, and it is unrelated to billing.** Its
starter-range migrations stop well short of the current template, so it lacks
several foundation features. That does not block catalogue provisioning, which
touches only the Control Plane and the payment provider, but it should not be
discovered midway.

**The Docoris storage numbers in the request cannot be expressed until the
per-product limits gap is closed.** Ten gigabytes on Starter is not a value the
platform could hold for one product on 2026-09-22: the limits are constants
shared by every product, and Starter is five gigabytes for all of them.

## 12. Gaps and defects found

| # | Finding | Severity |
|---|---|---|
| 1 | The seat count is sent as the subscription quantity, so a flat-fee plan is multiplied by its seats. Latent while plans have no price; armed by the first provisioning run | **Critical** |
| 1b | ~~The seat count is enforced nowhere.~~ **Withdrawn 2026-09-22: wrong.** It is enforced, carefully, in the portal's member route. Left in the table rather than deleted, because a finding that quietly disappears is indistinguishable from one that was fixed | — |
| 1c | The seat count is chosen by the customer at signup, where under a flat fee it should come from the plan's included count. A customer picking one seat on a plan including three pays for three and receives one | High |
| 1d | The message refusing a member says to add a seat under Billing. Under a flat fee with a hard cap that advice cannot be followed, and the answer is to move up a tier | Medium |
| 2 | Included storage and AI allowances are platform-wide constants; no product can differ | High |
| 3 | No plan versioning, effective dates or grandfathering model | High |
| 4 | The plan write endpoint overwrites the whole row; a caller sending only prices resets name, self-serve and seat bounds | High |
| 5 | The registrar identity **cannot** write plans, and granting it the role that would let it **breaks registration** — the endpoint admits machines only and a platform role reclassifies the token as staff. A second service account is required | High |
| 6 | The standard names a Professional tier; the platform's plan code is `pro`. A subscription points at a plan row, so this is a naming decision with a migration behind it | Medium |
| 7 | The billing capability in the product manifest gates a three-line package the billing document says may be removed. It makes `--with billing` ambiguous | Medium |
| 8 | The Control Plane fetches amounts live from the provider for the pricing page, so it does need provider calls to render prices | Medium |
| 9 | No mechanism keys behaviour off a product being a test product; the protection is the environment guard alone | Low |
| 10 | The documentation tests refuse an identifier named in a document that does not exist in the code, which constrains how a design document may name things it proposes. This document is written to that constraint | Low |

## 13. Implementation plan

Phases, each of which leaves the estate working.

**Phase 0 — decisions. Taken 2026-09-22, and recorded here rather than left in
a conversation.** All four went the way this document recommended.

**The plan code stays `pro`; the display name becomes Professional.** A
subscription points at a plan row, and the platform has renamed a tier once
before — the migration that turned premium into business is the precedent that
it works and also the record of what it costs. Three letters in a lookup key
did not justify repeating it across every registered product. The display name
is already staff-editable and the upserts that seed a catalogue never overwrite
one, so this costs nothing at the surface a customer sees.

**Amounts are in minor units, and the key name says so.** The unit lives in the
field name rather than in a comment, so a reader who has never seen the file
reads it correctly, and what is written is exactly what the provider receives —
there is no conversion anywhere to get wrong. The alternative that reads most
like a price list, a decimal, is a float in YAML, which is the other classic way
money goes wrong.

**The Control Plane gets a new versioned catalogue table**, and the plans table
keeps its job. A plan stays the entitlement bundle a subscription points at; a
catalogue row is a dated version of what that plan costs and includes. This was
not a preference: the plans table is unique on product and code, so it cannot
hold two versions of one plan at once, and plan versioning and grandfathering
are requirements rather than nice-to-haves.

**The additional-user prices are created in Phase 2, before anything can bill
them**, and the report and this document both say so. The reasoning is worth
keeping because it looks like a contradiction of the rule this repository
introduced when five grid settings shipped unsurfaced: a control that changes
nothing is worse than one that is not offered. The distinction is who meets it.
Nobody browses a provider's price list hoping to find a control; an unused price
sits in an account costing nothing and misleading no customer, whereas an
unused switch on a preferences page is a promise to the person looking at it.
What makes the difference safe is that it is stated rather than assumed — if a
later reader finds an extra-user price and concludes seats are billed that way,
this paragraph is what corrects them.

**A plan is a flat fee that includes users; the seat count never multiplies
it.** Clarified 2026-09-22. $99 includes three users on Starter, and the fourth
costs $25 rather than the first three costing $25 each — a soft cap, reached
in Phase 5 and a hard cap until then. Recorded as a decision rather than as a
clarification because the platform currently implements the opposite and a
reader of the code would reasonably conclude per-seat pricing was intended.

**The subscription quantity is one, and this is a rule rather than a default.**
Anything sending a seat count as a provider quantity is a bug from Phase 2
onward, whatever it looks like locally. The seat count is a limit; extra seats,
when they arrive, are a separate line with their own price and their own
quantity.

**The lookup key standard that follows from the first decision:**

| Object | Key |
|---|---|
| A plan, monthly | product code, then plan code, then `monthly` |
| A plan, yearly | product code, then plan code, then `annual` |
| The additional internal user | product code, then the two words *extra* and *user* joined by an underscore, then the interval |

That last row is spelled out in words rather than written as a symbol on
purpose, and the reason is finding 10 in the table above: the documentation
tests refuse an identifier a document names and the code does not contain. The
key does not exist yet. Writing it as code would either fail the suite or need
an exemption claiming it is absent on purpose — and that claim would quietly
stop being true on the day Phase 2 creates it, which is the exact decay the
test exists to catch. It becomes a symbol when it becomes real.

Underscore-separated throughout, no currency segment, and the plan code is the
platform's — so the Professional tier's key carries `pro`, which is the one
place the naming decision above is visible. That is recorded here because it is
exactly the kind of small deviation that gets "corrected" later by somebody who
has read the standard and not the decision.

**Phase 1 — the configuration schema. Built 2026-09-22.** The file, its
validation, the standard defaults including the per-plan user count, and
generation into every product that registers as one. Nothing talks to a
provider.

The schema is the full shape rather than what the next phase needs, because the
brief's central requirement is that a product with different values must not
mean different provisioning code — and a field added later is a field every
existing product has to re-edit. So included users, an open limits map,
per-plan entitlements, plan and catalogue versions and the standard extra seat
are all accepted now, and most of them are acted on by nothing.

**That is the arrangement this repository has shipped wrongly twice**, four
days apart, in settings and then in notifications: a declaration rendered and
honoured by nothing. What makes it acceptable here is that the command prints
exactly which declared fields it did not act on, on **every** run and not only
a dry run. Inertness that is stated is not a promise; inertness a reader infers
from the absence of an effect is.

**One test change is worth carrying.** Two assertions that a misspelt key is
refused passed with the schema's strictness removed — because a plan with a
misspelt amount ends up with no price, and a catalogue with no priced plan is
refused for *that* reason instead. They asked what the schema said rather than
what it did, which is the FW-HARDEN-001 shape. Both now put a valid priced plan
beside the misspelt one, so only strictness can produce the refusal, and both
go red when it is removed. Found by mutation-testing rather than by review.

Exit, met: a generated product carries the standard, it parses, the amounts are
the standard's, and a hand-edited one is refused for every way of getting it
wrong — a misspelt amount key, a fractional amount, a zero, a negotiated tier
that also names a price, a bad currency, and a plan including nobody.

**Phase 2 — the flat-fee correction. Built 2026-09-22, in
`koras-control-plane`, and it is the change the ordering exists for.** The subscription quantity becomes
one; the seat count becomes state this platform keeps rather than a number
derived from the provider's answer; the included-user count becomes an enforced
limit. Control Plane only — no provider work, no new prices, no proration.

`plans.included_users` records what a plan includes, seeded from the standard
by `00047_plan_included_users.sql`. The quantity is one at both call sites. The
seat count comes from the plan rather than the form. The repository function
that applies a webhook's state no longer takes a seats parameter at all — a
column absent from the statement cannot be written by anything that reads the
provider, which is the rule rather than an instance of it. It is described
rather than named here because it is another repository's internal, and the
identifier test is right to refuse this repository vouching for one.

**The finding that cost the most to notice was in the repair, not the
checkout.** Reconciliation's repair wrote seats, reading a missing value as
one. The check no longer puts seats in the desired state, so a repair triggered
by anything else — a status, a period, an interval, none of which a customer
controls — would have silently reduced a twenty-five-seat customer to a single
seat and locked every colleague out of the product. The reconciliation tests
failing is what found it.

**And the first guard written against it did not guard.** It asserted that the
*check* leaves seats out of the desired state, and passed with the repository's
seat write put back — two layers, and the hazard is in the second.
Mutation-testing caught that; review had not.

Exit, partly met. 817 tests pass across unit, provisioning, security and
contract, and the two money assertions — the quantity is one, and the plan
decides the seat count — are mutation-proven. **What is not met is the
end-to-end half**: the billing integration tests fail identically with and
without the change, against a local database behind on migrations and carrying
37,000 plans. Pre-existing and environmental, and recorded rather than allowed
to read as a pass.

**Phase 3 — provider provisioning. Built 2026-09-22.** Products, prices, the
standard lookup keys, metadata, idempotency, the environment guard, and the
report.

**The lookup key was decided by the platform, not here.** The Control Plane had
already written the contract — before anything minted a key, so that the key
would be shaped by the catalogue rather than by the first thing to use it — and
it carries a currency segment the request's standard omitted. The platform's
version won on 2026-09-22: one convention in the estate beats a shorter one,
and a factory minting a shape the platform's own helper would never produce
means any later comparison between them fails.

Two consequences follow from taking somebody else's contract whole. The
interval reads *yearly* rather than *annual*, because that is the word the
contract uses. And the extra seat is one hyphenated word rather than two
underscored ones, because the contract separates segments with underscores and
allows hyphens inside them — so two underscored words would be two segments
where one is meant, and a key with five parts where four are expected is one
nothing can parse.

**It is a second implementation of one rule**, in a different language with no
seam between them, which is the arrangement this estate keeps being bitten by.
The defence is that the tests pin the exact expected strings rather than
reproducing the rule: a test that recomputed it would drift in the same
direction as the code and agree with itself forever.

The extra-seat prices are created, under their own provider product rather than
hung off a plan's — an invoice line naming a tier for an extra user is wrong in
the one place a customer reads. Nothing writes them to the platform: there is
no column to hold an add-on price, and inventing one would be the factory
deciding another repository's schema.

**One thing this phase found in its own output.** Two of the three
declared-but-inert messages had gone stale — written in Phase 1, and untrue
once Phases 2 and 3 shipped. They said the included count was enforced nowhere
and that no extra-seat price was created, both by then false, in a message
printed on every run. A stale entry in that list is the same defect as a
missing one arriving from the other side: it tells somebody a control does
nothing when it does.

Exit, partly met: 61 tests, four of the phase's claims mutation-proven, and the
whole path driven through the real CLI against a generated product. **The real
test-mode account is not done** — it needs the billing service account, which
no environment has. That is F29.

**Phase 4 — Control Plane catalogue. Built 2026-09-22.** A plan's terms over
time, in a table beside `plans` rather than on it: `plans` is unique on product
and code and so cannot hold two versions at once, which is the whole
requirement. A version carries the amounts, the currency, the included count,
the provider references it was sold with, the extra seat's terms and an open
limits map, effective between two dates.

**Grandfathering is now a question with an answer.** A subscription points at a
plan; the catalogue row whose window contains the subscription's start is what
was sold. Before this it worked — an old provider price kept existing and kept
charging — but nothing recorded the terms, so the question could only be
answered by reading a provider dashboard and guessing at dates.

**Three rules are the database's rather than Python's**, and each is exercised
against real policies: exactly one version per plan may be current, enforced by
a partial unique index, because a plan with two would be a plan whose terms
cannot be read and the failure would surface as whichever row a query ordered
first; no delete policy exists, because a version is what somebody agreed to
and a billing dispute is exactly when it is read; and only a platform billing
role may write one, the same authority as the plan itself.

**The factory records it last**, after every price the version names exists —
the plan's and the extra seat's. A version naming a price that failed to be
created is a record of terms nobody can be charged on.

**Two things the work found in itself.** The window constraint was `>` and had
to become `>=`: `now()` is the transaction's start time, so closing and opening
in one transaction puts both timestamps at the same instant, which is exactly
what recording a correction to terms written moments ago looks like — the
constraint would have blocked the fix and not the mistake. And the first
version wrote a catalogue row on every run, which is idempotent in effect and
still broke *"a second run writes nothing"*; it reads and compares first now,
because the moment that property becomes "writes something harmless" nobody can
tell a quiet run from a busy one.

**One thing was found by a test failing for the wrong reason.** A staff context
declared with actor type `user` resolves no platform role at all, so a denial
test written that way passes whatever the policy says. The contexts declare
`platform` now.

Exit, partly met: 65 factory tests and 14 database tests against real policies,
three Phase 4 claims mutation-proven, and no regression in the Control Plane —
the failing set is identical with and without the change.

**Two parts of Phase 4 were not built, as of 2026-09-22.** Entitlement sync —
the factory walking a plan's declared entitlement codes and writing them
through the two endpoints that already exist — and the reconciliation check
extended to compare the recorded terms against the provider. Both are named
here rather than left to be rediscovered, and neither blocks what was built:
the terms are recorded, and `billing.catalogue` already compares the provider
against the plan's intent.

**Phase 5 — extra seats. Built 2026-09-23**, in `koras-control-plane`. The
additional-user price is a **second line** on the subscription: the plan's own
line stays at quantity one and the add-on line carries only the users *beyond*
the included count. A customer on Starter with five users is billed $99 plus
two at $25 rather than five times $99.

**Signup is untouched.** A new customer buys the plan at its included count;
seats are bought afterwards, through the portal's seat-change path, which is
where somebody discovers they need a fourth. That keeps checkout — the one
path a stranger with a card reaches — exactly as it was.

**The two lines are told apart by lookup key**, which is the platform's own
contract and is minted by the catalogue. Not by price id, which is per
environment and would have to be threaded in from somewhere, and not by
metadata, which is the same string with an extra way to be absent. **A price
with no lookup key is not the add-on** — the safe direction, so a subscription
somebody built by hand in a dashboard bills as it always did rather than
having its only line mistaken for a seat line and deleted.

**The seat price comes from the catalogue version in effect**, not from the
plan. A seat is priced by the terms a customer was sold, which is what Phase 4
exists to record — the first thing to consume it.

**Unstated means unchanged, and that is load-bearing.** A plan change that says
nothing about seats leaves the seat line alone. The alternative reading —
absent means none — would make every upgrade silently cancel the overage a
customer had bought.

**Three refusals and a removal.** A seat asked for with no recorded price is
refused rather than given away: a seat sold at no price is revenue nobody
decided to forgo, and the catalogue is where that decision belongs. Going back
to the included count **deletes** the line rather than setting it to zero,
which Stripe would refuse anyway and which is also the honest record.

**The deferred path restates both lines.** A schedule phase carries every line,
not only the one changing, so leaving the seat line out of the *current* phase
would end it at the period boundary because something else changed — a customer
downgrading their interval would quietly stop paying for, and lose, seats they
had.

**The seat count got its own writer.** Phase 2 removed seats from the
provider-state write so that nothing reading the provider could write one; with
a hard cap nothing needed to write it at all. Now that seats can change there is
a dedicated statement for it — described rather than named here, because it is
another repository's internal — called at the one place the decision is made. The provider
knows the plan line at one and the add-on at the overage, and neither is the
number a member check compares against.

Exit, partly met: 14 tests driving the real adapter against recorded provider
payloads, four of them mutation-proven — the plan line stays at one, unstated
seats are left alone, zero deletes rather than zeroes, and the deferred phase
keeps the seat line. **Not observed on a real subscription**, which needs the
catalogue provisioned first; that is F29.

**Between Phase 2 and Phase 5 the included-user count was a hard cap**, and
that was a consequence rather than a choice. Phase 5 shipped on 2026-09-23, so
the cap is soft now: a fourth user on Starter is a charge rather than a
refusal, wherever the catalogue records what one costs. The destination decided on 2026-09-22 is
a soft cap — a fourth user on Starter costs $25 — but nothing can bill that
fourth user until Phase 5 exists. The only alternatives in the meantime are to
admit the user and not charge, which gives seats away silently, or to admit and
charge nothing while claiming to charge, which is worse. So the fourth user is
refused, with a message that says the plan includes three and names the tier
that includes more, and Phase 5 turns the refusal into a charge.

**Phase 5 is where the remaining money is**, and it is last because every phase
before it leaves the platform able to sell something correct. That is the
change the clarification bought: the model is complete without it, where the
per-seat reading of the same table would have made it a prerequisite.
