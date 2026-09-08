# Billing Design — card at signup, charge at trial end

> Scope: both repositories. The subscription lifecycle, the payment provider
> adapter and the webhook live in `koras-control-plane`. The signup surface,
> the trial-ended state and plan gating live in this factory's product
> template. Where a plan is described, `koras-control-plane/docs/COMMERCIAL_CATALOGUE.md`
> is authoritative for what a plan *is*; this document adds what a plan
> *costs* and how a customer comes to pay it.

Status: **all five phases built** — Phases 1 to 4 on 2026-09-05 and the
code half of Phase 5 on 2026-09-06, on `develop` in both repositories. What
remains is not code: the live Paddle account, and the browser run against the
real sandbox. `koras-control-plane/docs/runbooks/paddle-go-live.md` is the
walk from sandbox to live. FOLLOW_UPS F13
records the decision this document extends: trial-only self-serve shipped
first, and `subscriptions.status` was made to mean something before a card is
taken (`koras-control-plane` R-93). This is the payment work F13 said would
"have a field to land on". What the Control Plane holds of it is
`koras-control-plane/docs/BILLING.md`.

The sandbox exists. Paddle sandbox account `koras`, product `koras-e2e-shop`
with tax category SaaS, two prices each with a 14-day trial, and a client-side
token named `koras-control-plan`. Price ids are references and safe to
record; the token and the API key are not, and live in Doppler only.

```text
product  pro_01m1sfr6w479m12zekmv3ckmbb   koras-e2e-shop
price    pri_01m1sg26mdqf1r4raam87rfkw5   $399 monthly, 14-day trial
price    pri_01m1sg4ppttw8edjdheyvqe1sj   $4,500 yearly, 14-day trial
```

Two things changed between the proposal and the build, both recorded in the
sections they touch: the customer reference is a table rather than a column
on `organizations`, because of what the webhook's authority may write; and
the Paddle adapter speaks to the HTTP API through `httpx` rather than through
Paddle's SDK, because five calls did not justify an untyped dependency under
strict mypy.

## The decision

Self-serve signup collects a card **before** provisioning and charges it
**after** a 14-day trial. The payment provider is **Paddle**, acting as
Merchant of Record. The Control Plane remains the only authority on who is
subscribed to what, in which status, and what that grants. No product ever
holds a provider credential, and no product ever calls the provider.

Three choices sit inside that sentence.

**Card at signup rather than trial first.** The alternative — provision a free
trial, ask for a card inside the product later — is what Linear, Notion and
Vercel do, and it produces more trials that convert less often. Card at signup
produces fewer trials that convert far more often, and the subscription record
in the Control Plane mirrors a real provider subscription from its first row
rather than being retrofitted on upgrade. The plan and seat count are known on
day one. The customer has already decided; the form only asks them to prove it.

**Charge at trial end rather than at signup.** No money moves on the signup
day. Paddle supports a trial period on a price, so checkout completes with a
zero-value transaction and the first charge is scheduled for day 15. A customer
who cancels inside the trial is never charged, which is what "trial" has to
mean for the card-upfront model to be honest.

**Paddle rather than Stripe.** KORAS is a German entity selling into the US
first, with subscribers from any country, and has no finance function. Under
Stripe, KORAS is the seller and owes sales tax registration in every US state
whose threshold it crosses, and VAT or GST registration in every country
likewise. Under Paddle, Paddle is the seller, collects and files all of it, and
is one counterparty in the books. The fee is higher — 5% + $0.50 against
roughly 2.9% + $0.30 + 0.5% for tax — and the difference is smaller than a
filing service and an accountant until well into six figures of annual
revenue. The provider sits behind an adapter so the decision can be revisited
without touching the portal or a product.

## The flow

```
Pricing page          product marketing site, plans from GET /api/signup/v1/plans
      │
      ▼
Signup form           organisation name · owner name · work email · plan · seats · monthly|annual
      │               POST /api/signup/v1/registrations          (exists — creates nothing)
      ▼
Email verification    link → /signup/verify?token=…
      │               POST /api/signup/v1/registrations/verify  (exists — today this starts provisioning)
      ▼
Paddle checkout       overlay on /signup/verify, trial price, quantity = seats, $0 today
      │               custom_data: registration_id · organization slug · product code · plan code
      ▼
Webhook               subscription.created → Control Plane records billing ids and STARTS PROVISIONING
      │               (verification no longer starts it)
      ▼
Provisioning          unchanged — ZITADEL org, owner, grants, tenant, subscription row
      │               subscription: status='trialing', trial_ends_at from Paddle, seats from quantity
      ▼
Wait page             unchanged — polls GET /api/signup/v1/registrations/status, then /login?next=/dashboard
      │
      ▼
Day 15                Paddle charges the card
                      transaction.completed + subscription.updated → status='active'
```

What moves, in one line: **the provisioning trigger moves from verification to
the provider's `subscription.created` webhook.** Everything downstream of it is
untouched, which is the point of putting the card where it is.

**The pricing page, which this flow assumed and which did not exist.** Built
2026-09-07 as a section on both public homepages, `/#pricing`, in the header
and footer navigation in all three languages. The plans are the Control
Plane's public catalogue, read on the server by the page — the same list the
signup form offers, so a card cannot name a plan that is not on sale. The
prices are the provider's: Paddle.js renders a price preview in the browser
with the public token, in the visitor's currency and tax, so no amount is
typed anywhere in this repository. Where the product takes no card, or the
provider does not answer, a card says the price is shown at checkout rather
than inventing one. Each card links to `/signup?plan=…&interval=…`, and the
form preselects both. What a plan is *for* — the bullet points under its
name — is configuration per language, keyed by plan code.

**As built.** Verification creates the organisation and, where the Control
Plane holds a provider key and the plan is priced for the chosen interval,
answers `awaiting_payment` with the price id, seat count, address and the two
ids the checkout carries in its custom data. The product's verify page opens
Paddle.js with `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN` and polls the status endpoint
by registration id; the Control Plane answers `AWAITING_PAYMENT` until the
webhook has started the run. Where no key is configured, or the plan has no
price, verification starts the run itself — a trial without a card, which is
what every environment sold before and what `test` and `stg` still sell until
they are given a sandbox key. The product's CSP admits `https://*.paddle.com`
in `frame-src`, `connect-src` and `img-src` exactly when the token is set, and
`NEXT_PUBLIC_PADDLE_ENVIRONMENT` is the sandbox unless it says `production`,
so a token with no environment cannot charge a real card.

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

| KORAS | Paddle | Cardinality |
|---|---|---|
| organisation | customer | one to one |
| organisation × product | subscription | one to one |
| plan | product | one to one |
| plan × billing interval | price | one plan has a monthly and an annual price |
| seats | quantity on the subscription item | an integer between the plan's minimum and maximum |

The Paddle customer is created at checkout and its id written to the
organisation on `subscription.created`. A second product bought later by the
same organisation reuses the customer and creates a second Paddle
subscription; the portal opens checkout with the existing customer id so the
card on file is offered.

Payouts arrive from Paddle monthly as a single settlement. Reconciling that
against the Control Plane's `active` subscription count is the only recurring
finance task this design creates.

## Annual plans and seats

**Interval.** Each plan carries two Paddle price ids, monthly and annual, held
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
Paddle's own portal through a one-time URL and reimplements none of it. On
the product side the entitlement read now carries the subscription's status
and two dates, and the shell says what they mean: a trial counting down and a
failed charge are a line above the page with the way to the portal for an
administrator; an ended trial or a cancelled subscription replace the page. The
shell decides nothing from them — the platform already resolves those states
to no entitlements — and the two plan-gated modules the template shipped close
with the rest.

**Seats.** Seats are the quantity on the Paddle subscription item and the
`limit_value` of a `seats` entitlement in the Control Plane, so products read
the seat count the way they already read every other limit. The plan row
carries `min_seats` and `max_seats`; the signup form and the portal enforce
them, and the Control Plane enforces them again before calling Paddle.

Seat changes are a Control Plane endpoint, never a product call. Increasing
seats is immediate and prorated. Decreasing seats takes effect at period end
and is refused while the organisation has more active members than the new
count, with the response naming the number to remove.

**Trial.** The trial is a property of the price in Paddle, 14 days on every
self-serve price. The Control Plane copies `trial_ends_at` from the provider
rather than computing its own, so the two can never disagree about the day the
card is charged.

## Status, and what drives it

`subscriptions.status` is written by exactly two things: the webhook handler,
and the nightly sweep. Nothing in a portal action, a product, or an admin
console form writes it directly; an admin who needs to cancel a subscription
does so through the Control Plane, which does so through Paddle, which tells
the Control Plane through the webhook. One path in, so the record and the
provider cannot diverge by design.

| Paddle event | Control Plane effect |
|---|---|
| `subscription.created` | record billing ids, seats, `trial_ends_at`; **start provisioning** |
| `subscription.activated` | `status='active'` |
| `subscription.updated` | copy status, seats, interval, `current_period_end` |
| `subscription.trialing` | `status='trialing'`, copy `trial_ends_at` |
| `subscription.past_due` | `status='past_due'`; the seven-day grace window R-93 built applies from `current_period_end` |
| `subscription.paused` | `status='suspended'` |
| `subscription.canceled` | `status='cancelled'`, `cancelled_at` |
| `transaction.completed` | record the transaction id and amount for reporting; no status change |

The grant policy is unchanged from F13 and lives in the resolver. `trialing`
past its end date grants nothing; `past_due` grants for the grace window;
`suspended` and `cancelled` grant nothing. A card that fails on day 15 is a
`past_due` subscription with seven days of access while Paddle's dunning runs.

Every webhook request is verified against the `Paddle-Signature` header,
stored in `billing_events` keyed by Paddle's event id **before** it is acted
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

Column names say `billing_`, not `paddle_`. The adapter is the only code that
knows which provider a value came from.

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

One interface in the Control Plane API, one implementation to begin with.

```python
class BillingProvider(Protocol):
    async def checkout(self, *, customer_id: str | None, price_id: str,
                       quantity: int, custom_data: dict[str, str]) -> CheckoutSession: ...
    async def portal_session(self, *, customer_id: str) -> PortalSession: ...
    def verify_webhook(self, *, body: bytes, signature: str) -> BillingEvent: ...
    async def subscription(self, *, subscription_id: str) -> ProviderSubscription: ...
    async def update_subscription(self, *, subscription_id: str,
                                  price_id: str | None, quantity: int | None,
                                  effective: Literal['immediately', 'period_end']) -> ProviderSubscription: ...
```

Five operations. Anything a portal page wants that is not one of these — an
invoice list, a card update, a receipt — is a link to the provider's customer
portal, not a new operation.

`koras-control-plane/services/api/koras_api/billing/paddle.py` implements all five against Paddle's HTTP API
with `httpx`, which the API already depends on; the SDK would have brought an
untyped client under strict mypy for five calls and one HMAC. Which Paddle a
key opens is derived from the key, since a sandbox key carries `_sdbx_`, and
`billing.provider()` refuses a live key outside `prod` and a sandbox key
inside it before any request goes out. The API key and the webhook secret
live in Doppler for the Control Plane's `api` service only, as
`PADDLE_API_KEY` and `PADDLE_WEBHOOK_SECRET`. The client-side token, which
Paddle.js needs in the browser, is the single provider value a frontend ever
sees, and it is scoped to opening checkout.

**The webhook** is `POST /api/billing/v1/webhooks/paddle`, the third
anonymous route on the Control Plane API after health and signup, on its own
prefix for the same reason signup is. `GET /api/billing/v1/events` lists the
delivery log to the billing role, without payloads, and
`?outcome=unmatched` is the read to start from when a customer says they paid
and see nothing.

## What lives where

| Piece | Repository | Where |
|---|---|---|
| Migration, adapter, webhook endpoint, reconciliation half | `koras-control-plane` | `services/api`, `services/scheduler` |
| Provisioning trigger moved to `subscription.created` | `koras-control-plane` | `koras-control-plane/services/api/koras_api/onboarding.py`, called by the signup router and the billing webhook |
| Plan prices and seat bounds in the console forms | `koras-control-plane` | `apps/admin`, the F9 forms |
| Portal Billing section replacing `NotYet` | `koras-control-plane` | `apps/portal` |
| Abandoned-checkout reminder | `koras-control-plane` | `services/scheduler` |
| Interval and seats on the signup form | this factory | `profiles/product/template/apps/web/src/app/signup/SignupForm.tsx.hbs` |
| Paddle.js checkout on the verify page | this factory | `profiles/product/template/apps/web/src/app/signup/verify/` |
| Trial-ended and past-due states in the shell | this factory | `profiles/product/template/apps/web/src/app/dashboard/` |
| First module declaring `requiredEntitlements` | this factory | the navigation registry, `docs/PRODUCT_APP_SHELL.md` |

`packages/billing` in the product profile stays `export {}` and may be removed.
A product's entire relationship with billing is reading entitlements, which it
already does, and rendering two states it does not yet have.

## Phases

| Phase | Repository | Content | Effort | Exit criterion |
|---|---|---|---|---|
| 1 Foundation — **built 2026-09-05** | control-plane | migration, adapter, Paddle implementation, webhook endpoint, `billing_events`, status mapping | 4 days | recorded sandbox events replay through the handler in tests and land the right status. **Half met:** the replay harness exists and runs against fixtures authored from Paddle's documented shape; recording needs a deployed API holding a secret, which no environment has yet |
| 2 Catalogue — **built 2026-09-05** | control-plane | price ids, interval, seat bounds on plans; console forms | 1 day | a plan with two prices and seat bounds is visible from `GET /api/signup/v1/plans`. Met in code; not yet exercised against a database with the migration applied |
| 3 Signup with card — **built 2026-09-05** | both | interval and seats on the form; Paddle.js checkout on verify; provisioning on `subscription.created`; abandoned-checkout reminder | 3 days | a sandbox signup with a test card ends signed in, with a `trialing` row carrying billing ids. **Not yet run:** the code is tested end to end through the API with a simulated provider, and the product template is type-checked as a generated project; the browser journey against the real sandbox needs a product deployed with the client-side token, which `koras-e2e-shop` will be once it takes this change |
| 4 In-app billing — **built 2026-09-05** | both | portal Billing section; change plan, interval, seats; manage billing link; trial-ended and past-due states; first gated module | 3 days | trial to active to seat change to cancel observed in `subscriptions.status`, and the gated module closes on cancel. **Half met:** the seat, interval and plan changes are tested through the portal API against a stand-in provider, and the two gated modules the template already shipped close when the state closes; the full cycle against the real sandbox is the same browser run Phase 3 is waiting on |
| 5 Reconciliation and go-live — **code built 2026-09-06** | control-plane | reconciliation half of the sweep; live account; live keys in Doppler; production hostnames approved in Paddle | 2 days + 1–2 weeks waiting | nightly reconciliation reports zero findings against sandbox; live account approved. **The check exists and is tested with a stand-in provider**, and runs every fifteen minutes with the estate sweep rather than nightly; the zero-findings night against the real sandbox and the live account are the two open boxes |

Three weeks of engineering. Phase 5's waiting starts on day one: apply for the
live Paddle account as soon as a public site with pricing, terms, privacy and
refund policy exists, because approval is the one step nobody at KORAS can
speed up.

## Test evidence

Four things, and a phase does not close without the ones it names.

1. **Replayed events.** A checked-in set of sandbox webhook payloads covering
   every row of the event table, replayed through the handler under test, with
   a redelivered event and an out-of-order pair among them. Phase 1.
2. **One full cycle in dev, against sandbox.** Signup with a test card, trial
   expiry forced by editing `trial_ends_at`, charge, seat increase, seat
   decrease refused over the member count, interval change, cancel. Each step
   observed as a row in `billing_events` and a value in `subscriptions.status`.
   Phase 4.
3. **A browser run.** The product template's Playwright suite gains a signup
   journey that completes Paddle's sandbox checkout overlay with a test card
   and ends on the dashboard. Generator Integration already runs that suite
   against a freshly generated product. Phase 3.
4. **A quiet night.** Reconciliation against sandbox reporting zero findings,
   then one deliberately corrupted row reported and corrected. Phase 5.

No module in any product declares `requiredEntitlements` until item 2 has
been done once. That is the rule F13 applied to the trial, applied again.

## Things that go wrong

- **Paddle.js will not open on an unapproved hostname.** Every hostname that
  serves `/signup/verify` — dev, test, staging, production, and any Vercel
  preview that needs it — has to be approved in the Paddle dashboard. Vercel
  preview URLs are per deployment; approve the stable branch alias, not the
  hash.
- **Sandbox and live are different accounts** with different keys, different
  price ids and different webhook secrets. Price ids are data on the plan row,
  so they differ per environment the way every other reference does, and
  Doppler holds the keys per environment the way it holds everything else.
- **A verified registration with no checkout is normal**, not an error. It is
  the reminder job's input.
- **A webhook that arrives before the registration exists** cannot happen in
  this flow, because checkout is opened from a verified registration and
  carries its id. The handler still refuses an event whose `custom_data` names
  no known registration, and stores it, so the case is visible if it ever
  occurs.
- **Payouts are monthly.** Cash arrives later than it would from a processor.
  This is a finance fact, not an engineering one, and it is written here so
  nobody reads a slow first payout as a failed integration.

## What this does not cover

Usage-based pricing, coupons, invoiced enterprise contracts with net terms, and
a free tier. Each is a price shape Paddle supports and none changes the
architecture. They are not in the first build because none has a customer
asking for it yet, and the design's rule for that is the same as F13's: run
the flow once before extending it.

Revisit the provider choice when annual revenue passes roughly $300,000, or
when KORAS incorporates a US entity and hires finance, whichever comes first.
At that point Stripe becomes a second implementation of the same five
operations for new customers, and Paddle subscriptions run out on their own.
