# Follow-ups — deliberately not done

> Scope: work that was identified, understood, and **left undone on purpose**,
> with the reason. One list, so that "we knew about that" is checkable rather
> than remembered.
>
> This is not a roadmap (`IMPLEMENTATION_ROADMAP.md` owns forward scope), not a
> risk register (`RISK_REGISTER.md` owns defects found in operation), and not
> the sync backlog (`SYNC_BACKLOG.md` owns the same-thing-true-in-one-place-only
> class). Where an item already has an entry in one of those, this points at it
> rather than restating it — a second description of one problem is how two of
> them come to disagree.

**Opened 2026-08-28**, from the session that applied the Control Plane's staged
promotion and added deploy-time registration.

---

## Blocked here — another repository or a person has to act

### F1 — the eight credentials from control-plane R-65 are still live

- [ ] Rotate four Supabase database passwords (dev, test, stg, prod)
- [ ] Rotate four ZITADEL OIDC client secrets
- [ ] Decide what to do about `output/sample-product`'s published history

**Severity: highest thing on this page.** Everything else here is tidiness by
comparison.

The generator committed a Terraform plan file holding a full state snapshot, and
pushed it. The factory-side defect is closed at four layers and the record is
now `SYNC_BACKLOG.md` C4 — but deleting a file does not unpublish it, and
nothing in this repository can rotate a credential.

`output/sample-product` was checked rather than assumed: the file is untracked
today and `.gitignore` names it, but commit `af81b9b` is reachable from
`develop` and the repository has a GitHub remote. The blob is still there.
Untracking a file does not remove it from history.

**Why not done here:** rotation touches Supabase and ZITADEL, and rewriting
published history is a decision with consequences for every clone. Neither is a
change to this repository.

### F2 — delete the promotion queue entries now that they are applied

- [ ] Remove `starter-promotion.patch`, its `README.md`, and `SYNC_BACKLOG_ENTRIES.md`
      from `koras-control-plane/docs/starter-promotion/`

All three are applied here: the patch as `SYNC_BACKLOG.md` A6, the three written
entries as A4, A5 and E3.

That repository's `OWNERSHIP.md` is explicit that the folder is *"a queue, not an
archive"* and that an applied entry moves upstream and is deleted — *"a promotion
folder that only ever grows is a record of things nobody did."*

**Why not done here:** `koras-control-plane` is read-only from this session.

### F2a — registration stores a token that expires in twelve hours

- [ ] Store the `registrar` service-account key instead of a finished token
- [ ] Mint the token at call time, in the generator and in
      `local/scripts/register-with-control-plane.sh`
- [ ] Decide whether the service account should be a Terraform resource

**This one is a design defect, not a missing document**, and it was found by
running the thing rather than reading it.

`KORAS_CONTROL_PLANE_TOKEN` is read from Doppler as a finished bearer string.
The credential it has to hold is a ZITADEL access token for the `registrar`
service account, and the exchange returns a lifetime of **43,199 seconds** —
measured against the dev instance on 2026-08-28. So a value stored today stops
working tomorrow. It fails loudly, as a misconfiguration rather than a skip,
which is the right failure and a daily one.

The estate already has the shape this should take.
`ZITADEL_DEV_SERVICE_ACCOUNT_KEY_JSON` and its three siblings hold a *key* that
the ZITADEL Terraform provider exchanges when it runs. Registration is the one
caller that did not adopt it: store a key, mint a token per call, store no
token anywhere.

**Two related findings from the same session**, both measured:

- **The token's form is decided by a ZITADEL setting nobody would think to
  check.** A service account left on the default access token type issues an
  *opaque* token, and the Control Plane verifies against a JWKS key set, so it
  cannot verify one at all. Using the Terraform account's key, the grant
  returned `200` and the Control Plane then returned `401`. `KORAS Product
  Registrar` is set to JWT and the other two service accounts are not, so the
  account is right and reusing either of the others would not be.
- **Neither Control Plane setting exists in `koras-platform-bootstrap` / `prod`.**
  Generation-time registration has therefore never run in this estate; every
  product so far was skipped as not-configured. That is correct behaviour and it
  means the path has never been exercised end to end against a real registry —
  see F7.

`docs/NEW_PRODUCT_WALKTHROUGH.md` §A.2 carries the whole of this, with the
values and the observed results.

**Why not done here:** minting a token at call time is a change to the
generator's configuration resolution and to the shell script, with tests for
both, and it should be decided together with F3 — a product minting its own
registration credential is the same trust question one layer down.

### F2c — every product registered before 2026-08-28 has a null callback address

- [ ] Re-register the products already in the registry

Generation-time registration never sent `platform_api_base_url`, so
`product_environments.platform_api_base_url` is NULL for every product
registered up to that date, including `koras-e2e-atlas`. It also never sent
`cloudflare_zone_id`, which the contract has always accepted and the Terraform
outputs have always carried.

Both are sent now. Nothing had broken, because the Control Plane's product
platform client does not exist yet — `ProductPlatformAdapter` is a Protocol whose
only implementation is `MockProductPlatformAdapter`. It would have broken the
moment that client was wired, and it would have read as a Control Plane defect
rather than a registration one: the tenant endpoints exist in every generated
product, and the registry simply had no address for them.

**Why not done here:** re-registering means re-running `--provision-only`
against a live estate, which is an operator action rather than a change to this
repository. References are upserted and never pruned, so a re-run fills the two
missing fields and disturbs nothing else.

### F2b — the per-product registration credential was designed and never built

- [ ] Have registration issue a per-product credential, or decide it should not
- [ ] Until then, keep deploy-time re-registration switched off

`CONTROL_PLANE_API_KEY` is declared in the product template's environment
contract and in its `secrets.manifest` as *supplied*, and
`PROVISIONING_RUNBOOK.md` describes it as "issued by the Control Plane when the
product registers". Checked: the registration response carries an id, a code, a
name, a slug, a profile, a status and a list of environments. There is no
credential in it, and no endpoint mints one.

**This matters because of what fills the gap.** The only credential that can
register a product today is the estate-wide `registrar` service account, and a
token minted from its key can rewrite *any* product's registry entry. Switching
on the deploy-time `register` job means putting that in each product's CI, which
turns a product's deployment credentials into estate-wide registry write access.

So the job added on 2026-08-28 is correct and should stay **off** until the
credential it deserves exists. That is a qualification of that work rather than
a defect in it: generation-time registration is unaffected, and re-running
`--provision-only` refreshes a product's references in the meantime.

**Why not done here:** what the Control Plane issues, and to whom, is the
Control Plane's decision. It is the same question as F3, arriving from the other
side.

### F3 — which credential should authorise a product's own re-registration

- [ ] Decide whether a product may hold a token that can rewrite its own registry entry
- [ ] If not, define the narrower machine role the contract already calls for

Deploy-time registration sends `KORAS_CONTROL_PLANE_TOKEN` from that
environment's Doppler config — the same factory-issued bearer token the
generator uses. It works, and it is the smallest number of moving parts.

It is also a trust decision nobody has made. `PRODUCT_REGISTRATION_CONTRACT.md`
§2 says registration should require a role narrower than the human admin one,
and that the narrower role does not exist yet.

**Why not done here:** authorization for the platform API is the Control Plane's
to decide, not the factory's. Recorded in `REGISTRATION_LIFECYCLE.md` under what
is not covered.

### F3a — the tenant endpoints now answer 422 and 409, and the Control Plane has not been told

- [ ] Teach the Control Plane's reference product the two refusals
- [ ] Decide whether a `409` on the tenant step should roll a job back or hold it

`services/api` used to keep tenants in a dict and could refuse almost nothing.
It persists them now, and two refusals came with that:

- **`422` when the request's `environment` is not this service's own.** A
  misconfigured caller, and correctly non-retryable — the Control Plane's retry
  policy fails a 4xx immediately.
- **`409` when a second organization asks for a slug the first holds.** Not the
  repeat case, which still answers `200`: this is two different customers asking
  for one name, and nothing on either side can resolve it without a person.

Neither is in `PRODUCT_REGISTRATION_CONTRACT.md` §6, which enumerates `200`,
`201` and the machine-identity rule and stops there. Both are refusals rather
than new behaviour a caller must invoke, so a Control Plane that has not been
updated is not broken by them — it will report a failed step, which is what
should happen in both cases. But
`koras-control-plane/tests/contract/reference_product.py` mirrors this router,
and mirroring it as it now stands is what would make the second bullet's
question concrete.

**Why not done here:** the reference product and the retry policy are the
Control Plane's. The 409 in particular is a product decision this repository
can state and a platform decision only that repository can make.

---

## Decisions this repository can make, and has not

### F4 — what `packages/control-plane-client` is for

- [ ] Decide whether the package should exist
- [ ] If it should: rewrite its types against the contract
- [ ] If it should not: remove it and the `control_plane_client` capability

Tracked as `SYNC_BACKLOG.md` A4. Its `ProductRegistration` type cannot produce a
request the Control Plane accepts — every field is either missing from the schema
or rejected by `extra="forbid"` — and nothing imports it, which is why no one has
noticed.

**Why not done here:** rewriting the types is an hour. Doing that without
deciding the first question leaves a *third* correct implementation of the same
contract that nothing calls, next to the two that everything calls. The right
order is the other way round.

### F4a — the plan catalogue was empty and had no user interface

- [x] Build the plan, entitlement and subscription forms the console is missing

**Closed 2026-08-29**, in `koras-control-plane`. Same work as F9; kept here
because this is where it was first written down.

What it needed beyond the five forms: `GET /entitlements`, which had never
existed. A form for what a plan grants has to name an entitlement, and nothing
could tell it which exist.

### F5a — `doppler-bootstrap` cannot express a legitimately empty setting

- [x] Promote the `optional` class from `koras-control-plane` into both templates

**Closed 2026-08-29.** `KORAS_CONTROL_PLANE_URL`, `KORAS_CONTROL_PLANE_TOKEN`
and the three `OTEL_EXPORTER_OTLP_*` names are `optional` in the product
manifest -- which is the set this entry listed as impossible to answer.

**The fix existed upstream.** `koras-control-plane` added a fourth manifest class
on 2026-08-29 -- `optional`: prompted like `supplied`, an empty answer accepted
as an answer, and absent from what `doppler-check` demands of a deployment. That
is exactly what this entry asks for, and it now needs copying into
`profiles/*/template/local/` rather than designing.

It was added under pressure rather than as tidying: declaring SMTP as `supplied`
blocked the Control Plane's dev deploy, because a worker whose whole design is
that an unset host selects a recording sender could no longer be deployed
without a mail provider.

Found by running it. The prompt loop treats an empty answer as `skipped, still
missing`, writes nothing, and fails the run. Four settings in the product
contract are legitimately empty until infrastructure exists that needs them —
the three `OTEL_EXPORTER_OTLP_*` names and `CONTROL_PLANE_API_KEY` — and there
is no way to answer them. The operator has to leave the script and use the
Doppler CLI directly.

`KORAS_CONTROL_PLANE_TOKEN` is the sharper case -- named
`CONTROL_PLANE_API_KEY` when this was written, see F14. It is declared
`supplied`, and nothing can supply it, because the Control Plane issues no such
credential (F2b). A manifest entry that demands a value the platform cannot
produce is a check that can only be satisfied by inventing one.

Both it and `KORAS_CONTROL_PLANE_URL` are `optional` in the class's own terms:
legitimately empty until a Control Plane exists, which is the documented
bootstrap order (R-001).

`PROVISIONING_RUNBOOK.md` claimed empty answers were recorded and counted. They
are not; that claim is corrected.

F2b is untouched by this. Whether that credential belongs in the contract at all
is still open; `optional` only means the bootstrap no longer demands a value
nothing can produce.

### F14 — two names for the Control Plane, and neither side noticed

- [x] Declare the settings under the names Doppler actually holds
- [x] Correct the runbook an operator follows
- [x] Extend `test_settings_are_declared.py` here to the Python services

**Closed 2026-08-29 apart from the last box.**

`register-with-control-plane.sh`, the generator's registration client and
`CLAUDE.md` all use `KORAS_CONTROL_PLANE_URL` and `KORAS_CONTROL_PLANE_TOKEN`.
`secrets.manifest` declared `CONTROL_PLANE_URL` and `CONTROL_PLANE_API_KEY`, and
`PROVISIONING_RUNBOOK.md` told an operator to set those. So `doppler-bootstrap`
prompted for one pair of secrets and every reader looked for another.

**Nothing failed, and that is the whole finding.** An unset URL is a documented
skip rather than an error -- R-001, the bootstrap order -- so deploy-time
registration would report *no Control Plane configured* in an estate that had
one, indefinitely. A defect whose symptom is a correct-looking skip is one
nobody goes looking for.

**This is probably what F7 would have found.** That entry says nothing has
exercised the register job in a real pipeline; this is the class of thing such a
run exists to catch, and it was found instead by a test in a different
repository rejecting a *new* setting for the same reason.

**The durable half is done.** The shared test reads pydantic `Settings` fields
now as well as `process.env`, having found upstream that scanning only `.ts`
caught one half of this defect and said nothing about the other.

It found four undeclared settings in the product template on its first run.
Two were tunables and are declared `optional`. `REQUIRE_RLS_ENFORCEMENT` is not
a tunable: a deployment with it false has correct policies, `force` on every
table, a green policy suite and no tenant isolation at all, which is R-032. It
is listed as never settable, with that reason, and the list is asserted both
ways -- an entry that becomes declared fails, and an entry nothing reads fails.

The second assertion earned itself immediately: `DOPPLER_TOKEN` was listed there
and the control-plane profile does not read it, so a fact about one profile was
being stated in a file both share. It is `PROVIDED_BY_THE_PLATFORM` instead,
which is what it is -- a credential injected at deploy time that cannot live in
Doppler.

### F5 — `apps/marketing` declares Tailwind and imports no stylesheet

- [ ] Give it a `globals.css`, or drop `tailwindcss` from its `package.json`

Noted in the promotion patch's own "not included" section and carried into
`SYNC_BACKLOG.md` A6. A PostCSS config there would compile nothing, because
there is no stylesheet for it to compile.

**Why not done here:** it is a design decision about what that application is,
not a defect with one correct fix.

### F6 — the two references deploy-time registration cannot carry

- [ ] Decide whether a newly added application should reach the registry before
      the next `--provision`

`supabase_project_ref` is only reachable through `DATABASE_URL`, which is a
credential and is not read. `vercel_projects` holds per-application repository
secrets that would have to be aggregated into one job to be sent.

Both are upserted and never pruned by the Control Plane, so omitting them ages
them rather than losing them. The single real gap is a **newly added
application**, and it is visible rather than silent — the registry goes on
listing the applications it already knew.

**Why not done here:** closing it means either reading a credential or copying
per-application secrets into a place they are not today, both for a reference
that already survives. Stated in `REGISTRATION_LIFECYCLE.md` rather than fixed
quietly.

---

## The customer-onboarding sequence

Five pieces, in the order they unblock each other, from the review on 2026-08-29
of how a customer gets from nothing to a working tenant.

**All of it closed on 2026-08-29 except F13**, which is a commercial decision
rather than an implementation. A customer can go from a product's `/signup` page
to a provisioned tenant with a welcome email, choosing from the plans that
product actually sells, without a member of staff touching anything.

One setting decides whether that works in a given environment, and it has no
value yet: without `SMTP_HOST` the sender records instead of sending. It is
`optional` in the Control Plane's manifest, so a deployment does not demand it,
which makes that failure silent — deliberately, since a product without a mail
transport is a product still being set up.

There were two. `SIGNUP_VERIFY_BASE_URL` was the second, and it was the wrong
shape: one value on a platform that runs many products. Two products meant
either a wrong domain in half the emails or a per-product setting added by hand
at every launch, and a verification link on the wrong domain is one a customer
is right not to trust.

The link is derived from `products.primary_domain` instead, which registration
already carries and upserts on every pass — a product that can be signed up for
has already told the platform this. A product without one is an error rather
than a fallback: a platform default would send a plausible link to somewhere the
customer never visited.

That derivation makes the Control Plane depend on two shapes owned here — the
`web` application is served at `app.`, and the signup page is at
`/signup/verify`. Both are asserted in `tests/docs/signup-verify-contract.test.ts`,
because the symptom of changing either is a customer who cannot finish signing
up and has no way to report why.

**This is forward scope and belonged in a roadmap**; it was written here because
the pieces began as "identified and deliberately not started", which is what
this file is for. Now that they are built, the record of *what was decided and
why* belongs in the owning repository's design documents -- and mostly is:
`SELF_SERVE_SIGNUP.md` owns the signup shape, `PROVISIONING_DESIGN.md` owns the
notify step. This section should shrink to a pointer at those once somebody is
confident nothing here is the only copy.

The design rationale is not restated here. `PROVISIONING_DESIGN.md` §1 and §3
own the sequence, `COMMERCIAL_CATALOGUE.md` owns the two-authorities split, and
`DOMAIN_MODEL.md` §5 owns entitlement precedence — all three in
`koras-control-plane`.

**The finding that orders them:** onboarding is a Control Plane responsibility
and is already designed as one. Of the thirteen provisioning steps, the product
owns exactly one — `POST /internal/platform/v1/tenants`. So the answer to "does
each product need an onboarding form" is no: one shared acquisition form, and a
first-run setup wizard per product for the part that genuinely differs.

### F9 — the plan catalogue could not be authored

- [x] Five client methods and a form per page, per `COMMERCIAL_CATALOGUE.md`
- [x] The read that was missing, so a form can name a capability
- [x] Browser coverage of each write

**Closed 2026-08-29**, in `koras-control-plane`. F4a closes with it.

One thing that document did not anticipate: `PUT /entitlements` had existed
since the entitlement work with nothing reading it back, so a form for what a
plan grants had no way to name an entitlement. `GET /entitlements` was added
with the forms.

### F10 — the tenant store was in memory

- [x] Persist tenants rather than holding them in a module-level dict
- [x] Keep the lookup by `tenant_key` first, and 200 apart from 201
- [x] Policies that let a call with no tenant context create one

**Closed 2026-08-29.** `core/tenant_store.py`, migration `00003`, and
`supabase/tests/030_provisioning_context.sql`. The last of those found a real
defect on its first CI run — an `on conflict` naming an arbiter needs the
table's select policies, and `tenant_members` had been given insert alone.

### F11 — there is no way for a customer to start signing up

- [x] An unauthenticated signup endpoint on the Control Plane
- [x] Rate limiting, and address verification before a job is created
- [x] A column on a plan saying it may be bought unattended, defaulting to false
- [x] A signup surface in the product template
- [x] An anonymous way to learn which plans are on sale

`PROVISIONING_DESIGN.md` §1 begins "customer opens product → branded signup",
and no endpoint serves that. `POST /organizations` and
`POST /organizations/{id}/provision` both take `PlatformAdminDep`, and the
portal's routes all require an organization that does not exist yet. So today a
member of KORAS staff creates the organization and starts the run by hand.

**The shape is settled now.** `koras-control-plane/docs/SELF_SERVE_SIGNUP.md`,
written 2026-08-29. The load-bearing decision is that a signup creates *no*
organization: it writes one pending row and sends one email, and provisioning
begins only when the address has been proven. A junk signup at the far end of
that chain would otherwise cost a ZITADEL organization that rollback policy
forbids deleting.

**It depends on F12, not the other way round.** Proving an address means sending
to it, and nothing in either repository sends email. This list originally
ordered them the other way, which was wrong.

Two corrections to what was written here first. The Control Plane *does* have a
rate limiter — `koras-control-plane/services/api/koras_api/core/security.py`, global and per-caller — so the gap is not its
absence but its shape: for an anonymous write it gives one budget to everyone
behind a NAT and a fresh budget to every address an attacker holds. That is the
forcing case for the Control Plane's own TS-01, which asks whether a
per-instance ceiling is enough and answers "for the registry, probably".

**Closed 2026-08-29** apart from the last box, which the work uncovered.

**Fully closed.** The gap it left first -- nothing anonymous could list which
plans are self-serve, so the form named one plan fixed at generation time -- is
`GET /api/signup/v1/plans` now: code and name, self-serve and active only.

Written as its own query rather than `GET /plans` narrowed, because a narrowed
staff read grows the next column somebody adds to the staff read, and the first
time that happens nobody notices it reached an anonymous caller.

**Where the surface landed, and why not where the design said.** In `apps/web`
beside `/login`, not `apps/marketing`. Marketing is optional, so a product
generated without it would have had no way to sign anybody up -- and the
verification link has to land in the application that has a session to send
somebody into anyway.

### F12 — a provisioning run finished and told nobody

- [x] A `notify` step after `verify` in the state machine
- [x] Something that actually sends, in the Control Plane
- [x] A sender a generated product can use

**Closed 2026-08-29.**

**The third box was a different consumer**, which this entry originally
conflated -- and it was also written in the wrong language. The notify step is
Python in the Control Plane's worker; `packages/email` was TypeScript. Mail is
sent server-side, because the address, the transport credential and the decision
to contact somebody all belong to the API: a browser must never hold an SMTP
credential, and a Next.js action sending mail directly would be a second place
deciding who gets written to.

So `python-packages/koras-email` is the real thing and `packages/email` says why
it is empty and where to go instead. Nothing depends on it yet, deliberately: a
service adds it when it has a message to send.

`packages/email` and `packages/notifications` are both `export {}`. The state
machine ends at `READY`.

The step is safe-to-reverse in the rollback classification and must be as
idempotent as every other one: a retried job must not send a second welcome.

What the step cost, because it is the one thing on that engine that could not be
made idempotent the usual way: every other step asks the remote system what
exists and adopts it, and nothing can be asked whether a message was delivered.
The welcome is therefore **at-least-once** -- a duplicate is mildly irritating,
and a missing one leaves a working account nobody knows about.

One thing the package cost, and it is the trap the root `pyproject` already
documents for the API: a workspace member nothing depends on is buildable and
**not installed**, so its own tests could not import it and collected nothing. It
is in the dev group for that reason alone.

### F13 — nothing bills anyone, and that is not an oversight

- [ ] Decide whether self-serve ships trial-only first

No table holds an amount. `COMMERCIAL_CATALOGUE.md` says so directly: plans are
entitlement bundles, not price points. The portal's Billing section is an honest
`NotYet`, and `packages/billing` is `export {}`.

The recommendation is to ship trial-only self-serve and keep paid plans
staff-provisioned until the catalogue and the provisioning path have run
end-to-end once. Designing webhook reconciliation against a flow nobody has
executed is the mistake `SSO_DESIGN.md` avoids when it chooses A1 over A3.

When it is built: the subscription lifecycle stays in the Control Plane, the
processor holds price and payment method, `subscriptions.status` becomes the
thing a webhook drives, and no product ever holds a processor credential.

**Why not done here:** it is a commercial decision before it is an
implementation, and it is the one item here with no dependency forcing it now.

---

## Verification that has not happened

### F7 — nothing has exercised the register job in a real pipeline

> Since this was written, F14 found a defect of exactly the shape a real run
> would have caught: the job read two settings the manifest declared under other
> names, and reported *no Control Plane configured* rather than failing. The
> entry below still stands -- that was found by a test in another repository,
> not by running this.

- [ ] Observe the `register` job run in a generated project's deployment
- [ ] Confirm the Control Plane's stored references change as a result

What has been checked: the payload validates against the Control Plane's real
request model; the script refuses on a generated control-plane project with a
URL and token configured; every failure and skip path is asserted by
`registration-lifecycle.test.ts`.

What has not: a run against a live Control Plane, with a real Doppler config and
a real deployment.

**Why not done here:** deploying and provisioning are out of scope for this
session by instruction.

### F8 — the `--with` / `--without` generation paths remain untested

- [x] Generate with optional components and read the output

**This was already true when it was written, and the entry was wrong.**

`generator-integration.yml` has carried two extra matrix rows since 2026-08-25 --
`--with marketing,ai_gateway,scheduler` and `--without admin,worker` -- and each
is installed, built, linted, typechecked, tested and run through the row-level
security suite. They are the `integration-product-full` and
`integration-product-minimal` jobs, and they run on every push that touches
`profiles/` or `generators/`.

`SYNC_BACKLOG.md` D5 has all three boxes ticked and records the two defects the
rows caught on the day they were added: `--with scheduler` produced a project
that failed its own typecheck, and the AI gateway discarded the coroutine that
reads its config. This entry was written the same day and repeated the gap as
though it were still open.

**What is actually untested is the register job**, which is the half of this
entry that was true: it ships from the shared template regardless of component
selection, and no run exercises it. That is F7, where it already lives -- so
this entry was one real gap filed under another one's name.

Corrected 2026-08-29, by reading the workflow rather than the entry.
