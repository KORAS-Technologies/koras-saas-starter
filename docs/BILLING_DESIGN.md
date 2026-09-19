# Billing Design — card at signup, charge at trial end

> Scope: both repositories. The subscription lifecycle, the payment provider
> adapter and the webhook live in `koras-control-plane`. The signup surface,
> the trial-ended state and plan gating live in this factory's product
> template. Where a plan is described, `koras-control-plane/docs/COMMERCIAL_CATALOGUE.md`
> is authoritative for what a plan *is*; this document adds what a plan
> *costs* and how a customer comes to pay it.

Status: **all five phases built in code** — Phases 1 to 4 on 2026-09-05 and
the code half of Phase 5 on 2026-09-06, on `develop` in both repositories — and
**the provider switched from Paddle to Stripe Managed Payments on
2026-09-09**, before any customer existed to migrate. What remains is not
code: the Stripe account with Managed Payments enabled, the test-mode
catalogue, and the browser run against it.
`koras-control-plane/docs/runbooks/stripe-go-live.md` is the walk from test
mode to live. FOLLOW_UPS F13 records the decision this document extends:
trial-only self-serve shipped first, and `subscriptions.status` was made to
mean something before a card is taken (`koras-control-plane` R-93). This is
the payment work F13 said would "have a field to land on". What the Control
Plane holds of it is `koras-control-plane/docs/BILLING.md`.

**That paragraph and the phase table below were written on 2026-09-06 and
overtaken on 2026-09-15, and said otherwise until 2026-09-19.** What used to
stand here is that the test-mode catalogue did not exist and the fixtures
carried placeholder price ids. By 2026-09-15 the Stripe test-mode account,
the catalogue, the webhook endpoint and six completed browser checkouts all
existed, and the fixtures were re-recorded from real deliveries — recorded in
`koras-control-plane/docs/BILLING.md` and in FOLLOW_UPS F21, and not here.

One fact, two documents, one of them updated: the `SYNC_BACKLOG.md` shape,
landing on the document that calls itself authoritative for both repositories.
So the phase table below now says where to look rather than what is true, and
`koras-control-plane/docs/BILLING.md` is the single place the built state is
recorded. What stays here is the *design* — the decisions, the data model, the
adapter's six operations and the rules — which is what this document is for
and what does not change when a box is ticked.

Price ids are references and safe to record; the secret key and the webhook
secret are not, and live in Doppler only.

Three things changed between the proposal and the build, each recorded in
the section it touches: the customer reference is a table rather than a
column on `organizations`, because of what the webhook's authority may
write; the adapter speaks to the provider's HTTP API through `httpx` rather
than through an SDK, because six calls did not justify an untyped dependency
under strict mypy; and the provider itself, below.

## The decision

Self-serve signup collects a card **before** provisioning and charges it
**after** a 14-day trial. The payment provider is **Stripe**, with **Managed
Payments** on every checkout, which makes Stripe the Merchant of Record. The
Control Plane remains the only authority on who is subscribed to what, in
which status, and what that grants. No product ever holds a provider
credential, and no product ever calls the provider.

Three choices sit inside that sentence.

**Card at signup rather than trial first.** The alternative — provision a free
trial, ask for a card inside the product later — is what Linear, Notion and
Vercel do, and it produces more trials that convert less often. Card at signup
produces fewer trials that convert far more often, and the subscription record
in the Control Plane mirrors a real provider subscription from its first row
rather than being retrofitted on upgrade. The plan and seat count are known on
day one. The customer has already decided; the form only asks them to prove it.

**Charge at trial end rather than at signup.** No money moves on the signup
day. The trial is stated on the checkout session, so checkout completes with
nothing charged and the first invoice is scheduled for day 15. A customer who
cancels inside the trial is never charged, which is what "trial" has to mean
for the card-upfront model to be honest.

**A Merchant of Record rather than a processor.** KORAS is a German entity
selling into the US first, with subscribers from any country, and has no
finance function. Under a plain processor, KORAS is the seller and owes sales
tax registration in every US state whose threshold it crosses, and VAT or GST
registration in every country likewise. Under a Merchant of Record, the
provider is the seller, collects and files all of it, and is one counterparty
in the books. The fee is higher — a few points above processing — and the
difference is smaller than a filing service and an accountant until well
into six figures of annual revenue.

**Stripe Managed Payments rather than Paddle**, decided 2026-09-09. Paddle
was chosen on 2026-09-05 because it was the Merchant of Record on offer.
Stripe's Managed Payments is the same offer — Stripe as the seller, sales
tax, VAT and GST filed in more than eighty countries, disputes and
transaction-level support handled — for a business in one of its supported
locations selling an eligible digital product, and a German SaaS company is
both. The account opens in hours rather than after a one-to-two-week review,
the customer portal and the Checkout page are the ones most customers have
already used, and the developer surface is the one most people at KORAS
already know. No subscription existed on the day, so nothing was migrated;
the Paddle adapter was deleted rather than kept behind a flag, since a
provider nobody flips to is a second codebase that only rots. The provider
still sits behind an adapter so the decision can be revisited without
touching the portal or a product.

Managed Payments has three constraints the design absorbs. It admits Stripe
Checkout and Payment Links only, so the checkout is a hosted page the
browser is sent to, not an overlay drawn over the product. It has no
browser-side price preview, so the Control Plane reads amounts from Stripe
and serves them beside the plans, through a sixth adapter operation. And it
keeps eligibility conditional on a low dispute rate, which makes customer
support a billing concern.

## The flow

```
Pricing page          product marketing site, plans from GET /api/signup/v1/plans
      │
      ▼
Signup form           organisation name · owner name · work email · plan · seats · monthly|annual
      │               POST /api/signup/v1/registrations          (exists — creates nothing)
      ▼
Email verification    link → /signup/verify?token=…
      │               POST /api/signup/v1/registrations/verify  creates the organisation and a Checkout Session
      ▼
Stripe Checkout       hosted page the browser is sent to; trial on the session, quantity = seats, $0 today
      │               metadata: registration_id · organization_id · product code · plan code
      │               returns to /signup/verify?registration=…&checkout=done|cancelled
      ▼
Webhook               customer.subscription.created → Control Plane records billing ids and STARTS PROVISIONING
      │               (verification no longer starts it)
      ▼
Provisioning          unchanged — ZITADEL org, owner, grants, tenant, subscription row
      │               subscription: status='trialing', trial_ends_at from Stripe, seats from quantity
      ▼
Wait page             unchanged — polls GET /api/signup/v1/registrations/status, then /login?next=/dashboard
      │
      ▼
Day 15                Stripe charges the card
                      invoice.paid + customer.subscription.updated → status='active'
```

What moves, in one line: **the provisioning trigger moves from verification to
the provider's subscription-created webhook.** Everything downstream of it is
untouched, which is the point of putting the card where it is.

**The pricing page, which this flow assumed and which did not exist.** Built
2026-09-07 as a section on both public homepages, `/#pricing`, in the header
and footer navigation in all three languages. The plans are the Control
Plane's public catalogue, read on the server by the page — the same list the
signup form offers, so a card cannot name a plan that is not on sale. The
prices are the provider's: the Control Plane reads them from Stripe with its
secret key, holds them for ten minutes, and serves them beside the plans as
minor units per seat, which the page formats in the visitor's language. No
amount is typed anywhere in either repository. Tax is added by Stripe on its
own page, in the visitor's own country, so the card shows the price before
tax and says so by showing nothing else. Where the product takes no card, or
the platform could not vouch for an amount just now, a card says the price is
shown at checkout rather than inventing one. Each card links to
`/signup?plan=…&interval=…`, and the form preselects both. What a plan is
*for* — the bullet points under its name — is configuration per language,
keyed by plan code.

**As built.** Verification creates the organisation and, where the Control
Plane holds a provider key and the plan is priced for the chosen interval,
creates a Checkout Session — `mode=subscription`, Managed Payments on, the
trial on the session, the registration and organisation ids in the
subscription's metadata — and answers `awaiting_payment` with its URL beside
the price id, seat count and address. The product's verify page sends the
browser there. The session returns to the product's own verify page, at the
application URL the product registered for the environment and never one
the request supplied, with the registration id and one word: `done` shows
the same provisioning wait as the free-trial path, polled by registration
until the webhook has started the run; `cancelled` offers the checkout
again, through `POST /api/signup/v1/registrations/checkout`, which mints a
fresh session for a verified signup that has neither a subscription nor a
run. Where no key is configured, or the plan has no price, verification
starts the run itself — a trial without a card, which is what every
environment sold before and what `test` and `stg` still sell until they are
given a test-mode key. The product holds no provider credential, public or
otherwise, loads no provider script, and its CSP names no provider host:
`frame-src 'none'` is the policy for a page nothing may be drawn over.

### Why the card comes after verification and before provisioning

Payment before verification attaches a card to an address nobody has proven,
which is a fraud and chargeback surface. Payment after provisioning means a
customer who abandons checkout holds a fully provisioned trial with no billing
record, which is the trial-first model wearing a card-upfront label. Between
the two, the checkout has a verified human on one side and nothing created yet
on the other. A failed or abandoned checkout leaves a verified, unprovisioned
registration and nothing to unwind.

### The abandoned checkout

A registration that is verified but has no `subscription.created` within one
hour is an abandoned checkout. It is not deleted. One reminder email goes out
after 24 hours carrying a fresh verify link, since the original token was
spent. After seven days the registration expires and the email address may
sign up again. This is a scheduler job, next to `subscription_renewal_check`.

## Per-organization

The unit of billing is the organisation, and one organisation may hold one
subscription per product. That is what `subscriptions` already says with its
`unique (organization_id, product_id)`.

| KORAS | Stripe | Cardinality |
|---|---|---|
| organisation | customer | one to one |
| organisation × product | subscription | one to one |
| plan | product, with an eligible tax code | one to one |
| plan × billing interval | price | one plan has a monthly and an annual price |
| seats | quantity on the subscription item | an integer between the plan's minimum and maximum |

The Stripe customer is created at checkout and its id written to
`billing_customers` on `customer.subscription.created`. A second product
bought later by the same organisation reuses the customer and creates a
second Stripe subscription; the checkout is opened with the existing
customer id so the card on file is offered.

Payouts arrive from Stripe on the account's schedule, net of the Managed
Payments fee and the tax Stripe collected as the seller. Reconciling a payout
against the Control Plane's `active` subscription count is the only recurring
finance task this design creates.

## Annual plans and seats

**Interval.** Each plan carries two Stripe price ids, monthly and annual, held
on the plan row. The signup form offers the interval as a toggle beside the
plan, not as a separate plan — "Team, yearly" is not a different bundle of
entitlements from "Team, monthly", and `COMMERCIAL_CATALOGUE.md` is right that
a plan is an entitlement bundle.

Changing interval is a subscription update through the Control Plane.
Monthly to annual takes effect immediately with proration. Annual to monthly
takes effect at the end of the current period, because refunding eleven months
of a discount is not a change the customer meant to make.

**As built.** The portal's Billing page shows each product's plan, interval,
seats and next date, never an amount, and one form changes any of the three.
The API applies the rules below and the row follows what the provider answers,
never the request: an immediate change lands now, a scheduled one lands when
the provider's webhook says it did. "Manage payment method and invoices" opens
Stripe's customer portal through a one-time URL and reimplements none of it;
the portal is configured in the dashboard to allow the card, the invoices and
cancellation, and not plan or quantity changes, which belong to this
platform's rules. On
the product side the entitlement read now carries the subscription's status
and two dates, and the shell says what they mean: a trial counting down and a
failed charge are a line above the page with the way to the portal for an
administrator; an ended trial or a cancelled subscription replace the page. The
shell decides nothing from them — the platform already resolves those states
to no entitlements — and the two plan-gated modules the template shipped close
with the rest.

**Seats.** Seats are the quantity on the Stripe subscription item and the
`limit_value` of a `seats` entitlement in the Control Plane, so products read
the seat count the way they already read every other limit. The plan row
carries `min_seats` and `max_seats`; the signup form and the portal enforce
them, and the Control Plane enforces them again before calling Stripe.

Seat changes are a Control Plane endpoint, never a product call. Increasing
seats is immediate and prorated, with the proration invoiced at once.
Decreasing seats takes effect at period end and is refused while the
organisation has more active members than the new count, with the response
naming the number to remove. Stripe has no "from the next period" flag on an
update, so a period-end change is a **subscription schedule**: the current
item to the end of the current period, the new item for one period after,
and the subscription released from the schedule when that period starts, so
it continues on the new item and a later scheduled change starts clean.

**Trial.** The trial is stated on every checkout session — `BILLING_TRIAL_DAYS`,
fourteen unless a deployment says otherwise — because that is where Stripe
takes it. The Control Plane copies `trial_ends_at` from the provider rather
than computing its own, so the two can never disagree about the day the card
is charged.

## Status, and what drives it

`subscriptions.status` is written by exactly two things: the webhook handler,
and the nightly sweep. Nothing in a portal action, a product, or an admin
console form writes it directly; an admin who needs to cancel a subscription
does so through the Control Plane, which does so through Stripe, which tells
the Control Plane through the webhook. One path in, so the record and the
provider cannot diverge by design.

| Stripe event | Control Plane effect |
|---|---|
| `customer.subscription.created` | record billing ids, seats, `trial_ends_at`; **start provisioning** |
| `customer.subscription.updated` | copy status, seats, interval, `current_period_end`, `trial_ends_at` — `active` when the trial's first invoice is paid, `past_due` when a charge fails; the seven-day grace window R-93 built applies from `current_period_end` |
| `customer.subscription.paused`, `customer.subscription.resumed` | `status='suspended'`, then whatever Stripe says it is |
| `customer.subscription.deleted` | `status='cancelled'`, `cancelled_at` |
| `customer.subscription.trial_will_end` | copy the state; three days before the charge, for a product that wants to say so |
| `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed` | recorded for reporting; no status change |

Stripe's `unpaid` and `paused` both land as `suspended`: a card that failed
past every retry and a trial that ended without a card are, to a product, the
same absence of a paying subscription. `incomplete` and `incomplete_expired`
are a first payment that never happened, which a Managed Payments checkout
does not produce; the adapter passes them through untranslated and the
handler records rather than applies them.

The grant policy is unchanged from F13 and lives in the resolver. `trialing`
past its end date grants nothing; `past_due` grants for the grace window;
`suspended` and `cancelled` grant nothing. A card that fails on day 15 is a
`past_due` subscription with seven days of access while Stripe's retries run.

Every webhook request is verified against the `Stripe-Signature` header,
stored in `billing_events` keyed by Stripe's event id **before** it is acted
on, and processed idempotently. A redelivered event finds its id and returns
200 without doing anything. Events arriving out of order are resolved by
`occurred_at`: an older event never overwrites the effect of a newer one.

## Reconciliation

Webhooks are lost. The nightly `subscription_renewal_check`, which today
expires trials and closes grace windows, gains a second half: for every
subscription that is not `cancelled`, fetch the provider's view and compare
status, seats, interval and `current_period_end`. A difference is corrected in
the Control Plane's favour of the provider — the provider holds the money, so
the provider is right — and logged as a reconciliation finding, in the same
shape `RECONCILIATION_DESIGN.md` uses for infrastructure. Zero findings is the
expected nightly result and the number that appears in the console.

**As built.** Not a second half of the nightly job but a check in the
reconciliation engine itself, `billing.subscription`, which the estate sweep
already runs every fifteen minutes — so a lost webhook is caught within the
quarter hour, through the same engine that catches a hand-deleted grant, with
the same finding types and the same policy table. The provider adapter moved
into a shared Python package so the worker could hold one beside the API. A
provider that cannot be asked is UNREACHABLE and never repaired; an
environment whose rows name a provider the worker has no key for reports that
rather than a clean estate.

## Data model changes

`koras-control-plane`, one migration: `00028_billing.sql`.

```sql
alter table public.plans
  add column price_id_month text,
  add column price_id_year  text,
  add column min_seats      int not null default 1,
  add column max_seats      int;

alter table public.subscriptions
  add column billing_provider        text,
  add column billing_subscription_id text,       -- unique per provider
  add column billing_price_id        text,
  add column billing_interval        text check (billing_interval in ('month', 'year')),
  add column seats                   int  not null default 1,
  add column billing_synced_at       timestamptz; -- occurred_at of the last applied event

create table public.billing_customers (
  organization_id uuid primary key references public.organizations(id),
  provider        text not null,
  customer_id     text not null,
  unique (provider, customer_id)
);

create table public.billing_events (
  id            text primary key,          -- provider event id
  provider      text not null,
  event_type    text not null,
  occurred_at   timestamptz not null,
  received_at   timestamptz not null default now(),
  processed_at  timestamptz,
  outcome       text,                      -- applied · recorded · unmatched · stale · duplicate
  detail        text,
  payload       jsonb not null
);
```

Column names say `billing_`, not `stripe_`. The adapter is the only code that
knows which provider a value came from — and the switch of 2026-09-09 touched
no column, which is what the naming was for.

**Why the customer reference is a table.** The proposal put
`billing_customer_id` on `organizations`. The webhook runs its transactions
as the commercial authority, `koras.is_platform_billing()`, because that is
the policy `subscriptions` takes and a machine is asserted *out* of
`subscriptions` by the RLS suite. That authority has no operational reach by
design: `koras-control-plane/tests/rls/test_write_reach.py` proves the billing role cannot change
a row of `organizations`. A column there would have needed either a policy
widening billing into operations or a webhook running as an operator, and
`billing_customers` under the billing policies needs neither.

**`billing_synced_at`** is the out-of-order rule made concrete. An event whose
`occurred_at` is older than the last one applied matches no row in the update
and is recorded as `stale`.

## The adapter

One interface, shared by the API and the worker, one implementation.

```python
class BillingProvider(Protocol):
    async def checkout(self, *, customer_id: str | None, customer_email: str | None,
                       price_id: str, quantity: int, trial_days: int,
                       custom_data: dict[str, str],
                       success_url: str, cancel_url: str) -> CheckoutSession: ...
    async def portal_session(self, *, customer_id: str,
                             return_url: str | None = None) -> PortalSession: ...
    def verify_webhook(self, *, body: bytes, signature: str) -> BillingEvent: ...
    async def subscription(self, *, subscription_id: str) -> ProviderSubscription: ...
    async def update_subscription(self, *, subscription_id: str,
                                  price_id: str | None, quantity: int | None,
                                  effective: Literal['immediately', 'period_end', 'trial']) -> ProviderSubscription: ...
    async def prices(self, *, price_ids: list[str]) -> dict[str, ProviderPrice]: ...
```

Six operations. Anything a portal page wants that is not one of these — an
invoice list, a card update, a receipt — is a link to the provider's customer
portal, not a new operation. The sixth, `prices`, is a read that arrived with
Stripe: Paddle let a browser ask for a price with a public token, Stripe has
no such call, and a pricing page that shows an amount has to get it from
whoever holds the secret key.

`koras-control-plane/python-packages/koras-billing/src/koras_billing/stripe.py`
implements all six against Stripe's HTTP API with `httpx`, pinned to API
version `2025-03-31.basil` — the version from which the current period lives
on the subscription item and `managed_payments` exists — with the request
bodies form-encoded the way Stripe reads them. Which Stripe a key opens is
derived from the key, since a test key starts with `sk_test_` or `rk_test_`,
and `billing.provider()` refuses a live key outside `prod` and a test key
inside it before any request goes out. The secret key and the webhook secret
live in Doppler for the Control Plane's `api` and `worker` services, as
`STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`. No provider value reaches a
frontend at all: the checkout is a URL, and the URL is not a credential.

**The webhook** is `POST /api/billing/v1/webhooks/stripe`, the third
anonymous route on the Control Plane API after health and signup, on its own
prefix for the same reason signup is. `GET /api/billing/v1/events` lists the
delivery log to the billing role, without payloads, and
`?outcome=unmatched` is the read to start from when a customer says they paid
and see nothing.

## What lives where

| Piece | Repository | Where |
|---|---|---|
| Migration, adapter, webhook endpoint, reconciliation half | `koras-control-plane` | `python-packages/koras-billing`, `services/api`, `services/worker` |
| Provisioning trigger moved to the subscription-created event | `koras-control-plane` | `koras-control-plane/services/api/koras_api/onboarding.py`, called by the signup router and the billing webhook |
| Plan prices and seat bounds in the console forms | `koras-control-plane` | `apps/admin`, the F9 forms |
| Portal Billing section replacing `NotYet` | `koras-control-plane` | `apps/portal` |
| Abandoned-checkout reminder | `koras-control-plane` | `services/scheduler` |
| Interval and seats on the signup form | this factory | `profiles/product/template/apps/web/src/app/signup/SignupForm.tsx.hbs` |
| The hosted checkout on the verify page, and the return from it | this factory | `profiles/product/template/apps/web/src/app/signup/` — `Checkout.tsx.hbs`, `CheckoutClosed.tsx.hbs`, `verify/page.tsx.hbs` |
| Trial-ended and past-due states in the shell | this factory | `profiles/product/template/apps/web/src/app/dashboard/` |
| First module declaring `requiredEntitlements` | this factory | the navigation registry, `docs/PRODUCT_APP_SHELL.md` |

`packages/billing` in the product profile stays `export {}` and may be removed.
A product's entire relationship with billing is reading entitlements, which it
already does, and rendering two states it does not yet have.

## Phases

**What each phase contains is below; how far each one has got is not.** The
per-phase exit criteria this table carried until 2026-09-19 were written on
2026-09-06 and were four days stale by 2026-09-15 — Phase 3 read "not yet run"
after six browser checkouts had run. A design document that tracks progress
tracks it wrongly, because it is edited when the design changes and progress
changes without it.

`koras-control-plane/docs/BILLING.md` records what is built and what is not, in
the repository the code is in. `docs/FOLLOW_UPS.md` F21 records what is left,
which is the walk from test mode to live and is a person at a dashboard.

| Phase | Repository | Content | Effort |
|---|---|---|---|
| 1 Foundation | control-plane | migration, adapter, provider implementation, webhook endpoint, `billing_events`, status mapping | 4 days |
| 2 Catalogue | control-plane | price ids, interval, seat bounds on plans; console forms | 1 day |
| 3 Signup with card | both | interval and seats on the form; the hosted checkout on verify and the return from it; provisioning on the subscription-created event; abandoned-checkout reminder | 3 days |
| 4 In-app billing | both | portal Billing section; change plan, interval, seats; manage billing link; trial-ended and past-due states; first gated module | 3 days |
| 5 Reconciliation and go-live | control-plane | reconciliation half of the sweep; the account with Managed Payments enabled; live keys in Doppler; the customer portal configured | 2 days |

Three weeks of engineering. Stripe activates an account on business details
rather than after a review, so Phase 5's waiting is hours; Managed Payments
itself is one eligibility check, and the account must accept its terms in
the dashboard before the first checkout.

## Test evidence

Four things, and a phase does not close without the ones it names.

1. **Replayed events.** A checked-in set of test-mode webhook payloads
   covering every row of the event table, replayed through the handler under
   test, with a redelivered event and an out-of-order pair among them. Phase 1.
2. **One full cycle in dev, against test mode.** Signup with a test card,
   trial expiry forced by editing `trial_ends_at`, charge, seat increase, seat
   decrease refused over the member count, seat decrease observed as a
   subscription schedule, interval change, cancel. Each step observed as a row
   in `billing_events` and a value in `subscriptions.status`. Phase 4.
3. **A browser run.** The product template's Playwright suite gains a signup
   journey that completes Stripe's hosted checkout in test mode with a test
   card, returns to the verify page, and ends on the dashboard. Generator
   Integration already runs that suite against a freshly generated product.
   Phase 3.
4. **A quiet night.** Reconciliation against test mode reporting zero
   findings, then one deliberately corrupted row reported and corrected.
   Phase 5.

No module in any product declares `requiredEntitlements` until item 2 has
been done once. That is the rule F13 applied to the trial, applied again.

## Things that go wrong

- **The checkout returns to the URL the product registered.** The success
  and cancel addresses on a session are built from the product's application
  URL for the environment, so a product that has not registered one is
  answered 409 at verification rather than sent to a checkout with nowhere to
  come back to. A Vercel preview is a different hostname and gets no
  checkout, which is right.
- **Test mode and live mode share nothing** but the account: different keys,
  different price ids and different webhook secrets. Price ids are data on
  the plan row, so they differ per environment the way every other reference
  does, and Doppler holds the keys per environment the way it holds
  everything else.
- **A period-end change lives in a subscription schedule**, and the row keeps
  today's values until the webhook says the change landed. A schedule can be
  seen and released in the Stripe dashboard; releasing one by hand is the one
  way a scheduled change disappears without this platform being told, and the
  fifteen-minute reconciliation is what notices.
- **Managed Payments is conditional.** Stripe keeps it on a low dispute rate
  and can decline a product it judges ineligible, in which case KORAS becomes
  the seller for that product with the filings that follow. A dispute is a
  support failure before it is a billing one.
- **A verified registration with no checkout is normal**, not an error. It is
  the reminder job's input.
- **A webhook that arrives before the registration exists** cannot happen in
  this flow, because checkout is opened from a verified registration and
  carries its id. The handler still refuses an event whose metadata names no
  known registration, and stores it, so the case is visible if it ever occurs.
- **`checkout.session.completed` may arrive before or after
  `customer.subscription.created`.** Neither order matters: the session
  event is recorded and moves nothing, and the subscription event is the one
  that starts the run, whenever it comes.
- **Payouts are net.** The Managed Payments fee and the tax Stripe collected
  as seller are taken before the payout, so a payout is smaller than the sum
  of the prices. This is a finance fact, not an engineering one, and it is
  written here so nobody reads a small first payout as a failed integration.

## What this does not cover

Usage-based pricing, coupons, invoiced enterprise contracts with net terms, and
a free tier. Each is a price shape Stripe supports and none changes the
architecture — though Managed Payments does not admit a one-off invoice
outside the billing period, so an invoiced contract would be sold outside it,
with KORAS the seller for that one customer. They are not in the first build
because none has a customer asking for it yet, and the design's rule for that
is the same as F13's: run the flow once before extending it.

Revisit the Merchant of Record choice when annual revenue passes roughly
$300,000, or when KORAS incorporates a US entity and hires finance, whichever
comes first. At that point turning Managed Payments off is a flag on the
checkout and a tax registration, not a new provider; the adapter stays.
