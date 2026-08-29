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

### F4a — the plan catalogue is empty and has no user interface

- [ ] Build the plan, entitlement and subscription forms the console is missing

A provisioning run requires a plan code, and
`koras-control-plane/docs/COMMERCIAL_CATALOGUE.md` measures dev as zero plans,
zero entitlements and zero subscriptions. The console can start a run naming a
plan nobody can create from the console; a plan can only be created with `curl`
and a staff token.

This blocks the first real end-to-end run rather than merely inconveniencing it,
which is why it is here and not only in that document. The workaround is
NEW_PRODUCT_WALKTHROUGH.md stage 4.2.

**Why not done here:** the console is `koras-control-plane`'s, and that document
already specifies what to build.

### F5a — `doppler-bootstrap` cannot express a legitimately empty setting

- [ ] Let the prompt record an empty value deliberately, rather than treating
      every empty answer as a skip

Found by running it. The prompt loop treats an empty answer as `skipped, still
missing`, writes nothing, and fails the run. Four settings in the product
contract are legitimately empty until infrastructure exists that needs them —
the three `OTEL_EXPORTER_OTLP_*` names and `CONTROL_PLANE_API_KEY` — and there
is no way to answer them. The operator has to leave the script and use the
Doppler CLI directly.

`CONTROL_PLANE_API_KEY` is the sharper case: it is declared `supplied` in
`secrets.manifest`, and nothing can supply it, because the Control Plane issues
no such credential (F2b). A manifest entry that demands a value the platform
cannot produce is a check that can only be satisfied by inventing one.

`PROVISIONING_RUNBOOK.md` claimed empty answers were recorded and counted. They
are not; that claim is corrected.

**Why not done here:** the fix is a small change to a template script, and it
should be made together with the decision in F2b about whether
`CONTROL_PLANE_API_KEY` should be in the contract at all.

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

Five pieces, in the order they unblock each other, from the review on
2026-08-29 of how a customer gets from nothing to a working tenant. **This is
forward scope and therefore belongs in a roadmap**; it is written here because
four of the five are "identified and deliberately not started", which is what
this file is for, and because three of them are another repository's to build.
When any of them is started, the phase it becomes should be recorded in the
owning repository's `IMPLEMENTATION_ROADMAP.md` and this entry reduced to a
pointer.

The design rationale is not restated here. `PROVISIONING_DESIGN.md` §1 and §3
own the sequence, `COMMERCIAL_CATALOGUE.md` owns the two-authorities split, and
`DOMAIN_MODEL.md` §5 owns entitlement precedence — all three in
`koras-control-plane`.

**The finding that orders them:** onboarding is a Control Plane responsibility
and is already designed as one. Of the twelve provisioning steps, the product
owns exactly one — `POST /internal/platform/v1/tenants`. So the answer to "does
each product need an onboarding form" is no: one shared acquisition form, and a
first-run setup wizard per product for the part that genuinely differs.

### F9 — the plan catalogue cannot be authored, and nothing downstream works without it

- [ ] Five client methods and a form per page, per `COMMERCIAL_CATALOGUE.md`

Already tracked as F4a, and repeated in the sequence only because it is first.
A provisioning run requires a `plan_code`; dev measures zero plans, zero
entitlements, zero subscriptions; a plan can be created only with `curl` and a
staff token. Nothing below can be tested until this exists.

For a product with four plans and around six capabilities that is four `plans`
rows, six `entitlements` rows and roughly twenty `plan_entitlements` rows —
small, and unreachable.

**Why not done here:** the console is `koras-control-plane`'s, its Phase 14, and
`COMMERCIAL_CATALOGUE.md` already specifies what to build.

### F10 — the tenant store was in memory

- [x] Persist tenants rather than holding them in a module-level dict
- [x] Keep the lookup by `tenant_key` first, and 200 apart from 201
- [x] Policies that let a call with no tenant context create one

**Closed 2026-08-29.** `core/tenant_store.py`, migration `00003`, and
`supabase/tests/030_provisioning_context.sql`. The last of those found a real
defect on its first CI run — an `on conflict` naming an arbiter needs the
table's select policies, and `tenant_members` had been given insert alone.

### F11 — there is no way for a customer to start signing up

- [ ] An unauthenticated signup endpoint on the Control Plane
- [ ] Rate limiting, and address verification before a job is created
- [ ] Some way for a plan to say it may be bought unattended, so trial is
      reachable and enterprise is not
- [ ] One shared, brandable signup surface in `profiles/_shared/template`

`PROVISIONING_DESIGN.md` §1 begins "customer opens product → branded signup",
and no endpoint serves that. `POST /organizations` and
`POST /organizations/{id}/provision` both take `PlatformAdminDep`, and the
portal's routes all require an organization that does not exist yet. So today a
member of KORAS staff creates the organization and starts the run by hand.

This is the piece that decides whether onboarding is self-serve at all, and the
only one where the shape is not already settled by an existing document.

**Why not done here:** the endpoint is the Control Plane's, and the form should
not be designed before the endpoint it posts to. The shared template half is
this repository's and lands after.

### F12 — a provisioning run finishes and tells nobody

- [ ] A `notify` step after `verify` in the state machine, idempotent like the rest
- [ ] `packages/email` implemented once in `_shared`, against one provider

`packages/email` and `packages/notifications` are both `export {}`. The state
machine ends at `READY`.

The step is safe-to-reverse in the rollback classification and must be as
idempotent as every other one: a retried job must not send a second welcome.

**Why not done here:** the step is the Control Plane's, the package is this
repository's, and neither is worth writing before F9 and F11 make a run
reachable by a customer.

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

- [ ] Generate with optional components and read the output

Pre-existing, tracked as R-037 and `SYNC_BACKLOG.md` D5, and named in `CLAUDE.md`
as the next step. Recorded here only because it now also covers the register job:
that job comes from the shared template and is present regardless of component
selection, but nothing has generated a product with optional components and
checked it.

**Why not done here:** it is the repository's existing next step and larger than
this session's scope.
