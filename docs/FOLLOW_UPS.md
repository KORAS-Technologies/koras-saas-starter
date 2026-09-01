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

## The index, in number order

Entries are grouped below by *why they are undone*, and numbered by *when they
were opened*. Those two orders cannot both run in sequence, so this is the
numeric one; the sections are the useful one. Within each section entries are in
number order.

**Identifiers are never renumbered or reused.** Seventeen files cite them —
fourteen here and three in `koras-control-plane`: workflow comments, source
comments, `SYNC_BACKLOG.md`, `TEMPLATE_SYNC.md`, the walkthrough. A dated
passage that says F2b is not made truer by renaming F2b, which is the same rule
`tests/docs/file-references.test.ts` applies to moved paths: record the change,
do not rewrite the record. It is why F14 sits at the end of a section that
otherwise stops at F6, and why there is no F0.

| # | Entry | State | Section |
|---|-------|-------|---------|
| F1 | the eight credentials from control-plane R-65 | closed 2026-08-30 | Blocked here |
| F2 | delete the promotion queue entries now that they are applied | closed 2026-08-30 | Blocked here |
| F2a | registration stores a token that expires in twelve hours | closed 2026-08-30 | Blocked here |
| F2b | the per-product registration credential was designed and never built | **open** — one half enforced | Blocked here |
| F2c | every product registered before 2026-08-28 has a null callback address | **open** — no product left to re-register | Blocked here |
| F3 | which credential should authorise a product's own re-registration | **open** | Blocked here |
| F3a | the tenant endpoints answer 422 and 409, and the Control Plane was not told | closed 2026-08-30 | Blocked here |
| F4 | what `packages/control-plane-client` is for | closed 2026-08-30 | Decisions |
| F4a | the plan catalogue was empty and had no user interface | closed 2026-08-29 | Decisions |
| F5 | `apps/marketing` declares Tailwind and imports no stylesheet | closed 2026-08-30 | Decisions |
| F5a | `doppler-bootstrap` cannot express a legitimately empty setting | closed 2026-08-29 | Decisions |
| F6 | the two references deploy-time registration cannot carry | **open** | Decisions |
| F7 | nothing has exercised the register job in a real pipeline | **open** — a product deployed 2026-08-30 and found seven defects | Verification |
| F8 | the `--with` / `--without` generation paths remain untested | closed — *the entry was wrong* | Verification |
| F9 | the plan catalogue could not be authored | closed 2026-08-29 | Onboarding |
| F10 | the tenant store was in memory | closed 2026-08-29 | Onboarding |
| F11 | there is no way for a customer to start signing up | reopened and re-closed 2026-08-30 | Onboarding |
| F12 | a provisioning run finished and told nobody | closed 2026-08-29 | Onboarding |
| F13 | nothing bills anyone, and that is not an oversight | **open** | Onboarding |
| F14 | two names for the Control Plane, and neither side noticed | closed 2026-08-29 | Decisions |
| F15 | a project generated then provisioned had no way into its own repository | closed 2026-08-30 | Decisions |
| F16 | a customer's own branding has nowhere to be read from | closed 2026-09-01 | Decisions |
| F17 | a product cannot read its customers' entitlements | **open** | Decisions |
| F18 | no test in this repository opens a browser | **open** | Decisions |

**Eight are open**: F2b, F2c, F3, F6, F7, F13, F17, F18. Five of those eight are
not this repository's to close — F2b, F3 and F17 are Control Plane authorization
decisions, F2c and F7 need a live estate and a staff read. The three this
repository can act on alone are **F6**, **F13** and **F18**, and all three are
decisions rather than implementations: F6's own entry says both references
already survive, F13 says outright that nothing forces it now, and F18 is a
question of where a browser harness lives.

F16 closed on 2026-09-01 and was the last open entry whose cost was code this
repository could simply write.

---

## Blocked here — another repository or a person has to act

### F1 — the eight credentials from control-plane R-65 — closed 2026-08-30

- [x] Four Supabase database passwords
- [x] Four ZITADEL OIDC client secrets
- [x] `output/sample-product`'s published history

**Closed by destroying the estate rather than by rotating anything.**

The generator committed a Terraform plan file holding a full state snapshot, and
pushed it. The factory-side defect is closed at four layers and the record is
`SYNC_BACKLOG.md` C4 — but deleting a file does not unpublish it. Commit
`af81b9b` is reachable from `develop`, the repository has a GitHub remote, and
the blob is still in history. It always will be.

So the credentials were not rotated. The resources they authenticate to were
deleted, which is R-041's own conclusion about what works after disclosure: a
rotated secret protects a resource that still exists, and every clone taken
before the rotation still names it. A deleted resource cannot be reached with
any credential, published or not.

`sample-product` is gone as of 2026-08-30 — 41 resources across eight
providers, each confirmed absent by asking the provider rather than by reading
the delete responses:

| Provider | Removed |
|----------|---------|
| Supabase | 4 projects |
| Upstash | 4 databases |
| Fly.io | 8 apps |
| Vercel | 8 projects, **and two more** |
| Cloudflare | 8 DNS records |
| GitHub | the repository |
| Doppler | the project |
| HCP Terraform | the workspace |

**Two of the Vercel projects were not in Terraform state.**
`sample-product-web` and `sample-product-admin`, with no environment suffix,
left from the one-project-per-application model that ENVIRONMENT_STRATEGY
described until 2026-08-28 and that nothing has built since. No teardown could
have found them: the inventory is built from state, and state never knew. They
turned up only because the providers were asked afterwards.

That is a class worth naming — a resource from a superseded design is invisible
to every check that starts from the current one, and the only thing that finds
it is looking at the provider.

**One thing nearly went wrong.** The first ZITADEL delete answered `301`, not
`200`. `ZITADEL_<ENV>_DOMAIN` in the bootstrap project holds a bare hostname
with no scheme, so the request went out as `http://` and was redirected. Read as
success, four ZITADEL projects would have survived. `koras teardown` is not
exposed to this: it takes the instance URL from the `zitadel_domains` output,
which carries the scheme deliberately, for exactly this reason.

### F2 — delete the promotion queue entries now that they are applied — closed 2026-08-30

- [x] Remove `starter-promotion.patch` and `SYNC_BACKLOG_ENTRIES.md` from
      `koras-control-plane/docs/starter-promotion/`
- [x] Remove `HANDOVER_PROMPT.md` — the same queue entry in session form
- [x] Rewrite that folder's `README.md` rather than delete it
- [x] Close TS-10 in `koras-control-plane/docs/TEMPLATE_SYNC.md`

All three were applied here: the patch as `SYNC_BACKLOG.md` A6, the three
written entries as A4, A5 and E3. Each was checked against this repository's
tree before anything was deleted upstream, rather than taken from the queue's
own account of itself.

That repository's `OWNERSHIP.md` is explicit that the folder is *"a queue, not an
archive"* and that an applied entry moves upstream and is deleted — *"a promotion
folder that only ever grows is a record of things nobody did."*

**Two departures from the item as written**, both because the item was written
before the folder's contents were re-read.

`HANDOVER_PROMPT.md` was not on the list and went anyway. It is the session
brief that carried this same queue into the starter, and all four of its work
items are closed — A5, E3, A6, and R-65, which closed on the same day as F1 by
destroying the estate the leaked credentials reached. It also directs a reader
to `output/sample-product`, which no longer exists. A spent brief left in a
queue is the archive the rule forbids, and this one now points at a deleted
directory.

`README.md` was rewritten, not deleted. `PROMOTION_CANDIDATES.md` stays —
TS-11 through TS-15 are open and it is their per-file reasoning — and deleting
the folder's only explanation would have left it there unexplained. The rewrite
keeps the queue rule, describes what remains, and records what was drained in a
few lines that point at `SYNC_BACKLOG.md` rather than restating it.

**What is not closed by this.** A6 keeps one box open — `product/apps/marketing`
declares Tailwind and imports no stylesheet — which the patch's README listed
under "Not included" as a design decision rather than a fix. It is F5 below, and
it stays open.

Nothing was committed in either repository.

### F2a — registration stores a token that expires in twelve hours — closed 2026-08-30

- [x] Store the `registrar` service-account key instead of a finished token
- [x] Mint the token at call time in the generator
- [~] ...and in `local/scripts/register-with-control-plane.sh` — **deliberately not
      done**, see below
- [ ] Decide whether the service account should be a Terraform resource — still open,
      and still the Control Plane's to decide

**Closed by `KORAS_CONTROL_PLANE_KEY_JSON`.** The generator holds the key and
mints per call, in `generators/create-koras-app/src/registration/token.ts`. The exchange is the one
`scripts/mint-control-plane-token.mjs` already performed, moved where the
generator can reach it, so there is one implementation of it rather than two.
That script stays as a diagnostic — it probes the Control Plane and names the
cause of a refusal — but it is no longer the only thing that can mint, which is
what made a twelve-hour credential into standing configuration.

The key is preferred over a stored token when both are set, because preferring
the token would mean an estate that had done the right thing still failed a day
later. A *malformed* key is refused outright rather than falling back: an
operator who stored a key and then damaged it should learn that now, not
tomorrow from an unrelated 401.

The ZITADEL instance is derived from the Control Plane URL rather than
separately configured, exactly as the script does it. A separately-answered
instance can disagree with the Control Plane it belongs to, and that mismatch is
a 401 indistinguishable from an expired token.

**Why the shell script was left alone, against this entry's own checklist.**
Writing it here as "the generator *and* the script" predates F2b's analysis, and
F2b supersedes it. Minting in the product's deploy script means storing the
`registrar` *key* in each product's Doppler configs — which is strictly worse
than the token it would replace, because a key does not expire. F2b's whole
argument is that a product must not hold estate-wide registry write access at
all; handing it the more durable form of that access to fix an expiry problem
would be solving the smaller problem by enlarging the larger one. The script
still reads a token, and the job that runs it is now off by default (F2b).

**33 tests**, against a generated key pair and an injected fetch — no network
call and no credential in the repository. They cover the assertion verifying
against its public half, the audience being ZITADEL rather than the Control
Plane, the opaque-token refusal from A.2, and that a malformed key never has its
material repeated back in an error message.

**And observed against the real estate on 2026-08-30**, which the tests above
could not establish: they prove the assertion is well-formed and every refusal
is handled, not that ZITADEL accepts it. The generator's own resolution and
minting were run under `koras-platform-bootstrap` / `prod`, storing nothing:

```
credential kind: key (the key won over the stored token)
instance       : https://auth-dev.korastechnologies.com  (derived from the URL)
minted         : true | JWT: true | valid for 12 hours
control plane  : HTTP 422 on an empty body — the identity passed
```

Three things that were design decisions rather than facts until that run. The
**key beat a stored token that was present** — `KORAS_CONTROL_PLANE_TOKEN` had
been set minutes earlier, so this was the contested case rather than the easy
one. The **instance was derived** from the Control Plane URL rather than read
from a setting. And the token came back a **JWT rather than opaque**, which is
the A.2 finding that costs the most to diagnose when it goes the other way.

This is a `pnpm koras:token` result for the generator's code path rather than
the script's. The two now share a proven exchange; before this they shared only
an intended one.

`docs/NEW_PRODUCT_WALKTHROUGH.md` §A.2 is updated: its configuration table, its
"expires in twelve hours" section, and the section that used to explain why the
arrangement was temporary.

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

**What this did not settle.** F3 is untouched: *which* identity may register a
product is still the Control Plane's decision, and this only changed the form
the credential is stored in. The two were filed together because a product
minting its own registration credential looked like the same question one layer
down — it is not. Credential *form* and credential *authority* are separable,
and separating them is what let this close while F3 stays open.

### F2b — the per-product registration credential was designed and never built

- [ ] Have registration issue a per-product credential, or decide it should not —
      the Control Plane's decision, untouched
- [x] Until then, keep deploy-time re-registration switched off — **enforced
      rather than recommended, 2026-08-30**

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
a defect in it.

**It is off now, in the workflow rather than in this document.** The `register`
job in the shared `deploy.yml` carries
`if: vars.KORAS_DEPLOY_REGISTRATION == 'true'`, so it does not run unless a
repository variable explicitly enables it, and it shows as a skipped job rather
than as a silent absence. Until 2026-08-30 it ran unconditionally and the only
thing keeping it harmless was that no product had the two settings — which is
not a control, it is a coincidence that a single `doppler secrets set` would
have ended.

A job-level condition is the right place for it. `deploy.yml` is copied into a
generated project verbatim and never rendered, so there is no generation-time
conditional available; and a gate inside the script would hide the decision from
anyone reading the workflow to find out what deployment does.

Generation-time registration is unaffected, and a product's references are
refreshed with `--register-only` in the meantime (F2c).

**Why not done here:** what the Control Plane issues, and to whom, is the
Control Plane's decision. It is the same question as F3, arriving from the other
side.

### F2c — every product registered before 2026-08-28 has a null callback address

- [x] Make re-registering something an operator can actually do — `--register-only`
- [ ] Re-register the products already in the registry — **still owed, and still
      an operator action against a live estate**

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

**The blocker was the cost of the fix, and that is removed.** Re-registering
meant re-running `--provision-only`: a full plan across eight providers, an
approval prompt, and an apply, all to re-send references that were already
correct. Nobody performs that to fill in two columns, which is why these rows
have stayed stale.

`--register-only` now exists (2026-08-30):

```bash
pnpm create-koras-app <project> --profile product --register-only --output-dir <dir>
```

It runs `terraform init` and `terraform output -json`, and sends what it reads.
It has no code path to a plan or an apply — asserted structurally, because a
regression that reintroduced one would fail no other test and would quietly make
this flag capable of changing infrastructure. The heaviest thing it can do
against a live estate is fail an HTTP request.

The flag is not new as an idea. `client.ts` has described "the operator's
`--register-only`" since it was written; it simply did not exist, which is its
own small instance of R-042 — a comment naming a flag nobody had built.

**Why the last box is still open, and why it may never close as written.**
Running it is an operator action against a live estate. But as of 2026-08-30
there is no estate to run it against: `koras-e2e-atlas` was torn down that day,
and `output/sample-product` was destroyed earlier the same day (F1). **No
product infrastructure exists.**

So this entry's remaining work has no subject. The two null columns are on
registry rows whose infrastructure is gone, and `--register-only` now refuses an
empty Terraform workspace rather than re-asserting a product nothing backs — see
below.

**That next product exists as of 2026-08-30.** `koras-e2e-shop` was provisioned
and registered, and its payload carries `platform_api_base_url` and
`cloudflare_zone_id` — the two fields whose absence opened this entry. So the
gap is closed for everything generated from here, by the fix rather than by a
migration.

Stated precisely: the *payload* carries them, which `registration.test.ts`
asserts and `buildRegistration` shows. What the registry now *stores* has not
been read back, because that needs a staff identity the registrar does not have
— the same open box as F7.

**What the teardown left behind, which is a different entry's problem.** Nothing
deregisters a product when its infrastructure is destroyed —
`REGISTRATION_LIFECYCLE.md` lists deregistration under what is not covered. So
the registry still holds `koras-e2e-atlas` with references to resources that no
longer exist, and reconciliation compares the registry against reality. The
first reconciliation run over it will report drift for a product that is
*deliberately* gone. That is worth knowing before somebody reads it as a bug.

**One defect this scenario found, fixed the same day.** `--register-only` read
`terraform output -json` and sent whatever came back. A destroyed workspace
answers `{}`, which parses into a valid all-empty result rather than an error,
and the payload built from it is *accepted*: identity comes from the manifest
rather than from state, so the Control Plane answers 200 and the operator is
told a torn-down product was registered. Nothing was destroyed by it — references
upsert per entry, so empty maps write nothing and prune nothing — but the claim
was false, from the one command whose purpose is making the registry match
reality. It refuses an empty workspace now. A state of nothing but sensitive
outputs still counts as real, because the parser withholds those values and a
check that read only what it could see would refuse a legitimate estate.

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

### F3a — the tenant endpoints now answer 422 and 409, and the Control Plane has not been told — closed 2026-08-30

- [x] Teach the Control Plane's reference product the two refusals
- [x] Decide whether a `409` on the tenant step should roll a job back or hold it
- [x] Declare both refusals in the shared contract, so they can be asserted
- [x] Fix the live defect that reading this turned up

**This was filed as a documentation gap and was not one.**

`ProductPlatformClient._request` mapped **every** 409 to `AlreadyExistsError`.
That class means "the resource I wanted is already there, so adopt it and carry
on" — `failures.decide` returns `should_retry=False` with the reason *"the
resource already exists and has been adopted"*, and the run proceeds to READY.

No route on that API can return an adoptable 409. A repeat of the same
`tenant_key` is answered `200` with that tenant, which is what makes the call
retryable and is required by the contract's `create_is_idempotent` rule.
Activate and suspend are assignments and never conflict. So the only 409 the API
produces is the product's slug conflict — a *second* organization asking for a
name the first one holds, where the tenant in the way **belongs to somebody
else**.

Adopting it handed one customer another customer's tenant and reported the
provisioning run as successful. That is the exact failure the contract exists to
prevent, arriving through its error handling. It is mapped to `InvalidError`
now.

**The decision, then: neither adopt nor roll back — hold.** Invalid rather than
transient because nothing on either side can resolve it; a person has to choose
a different name. Not a rollback because the organization and its identity
resources are already correct, and destroying them because a name collided would
punish the customer for the collision. The tenant step is idempotent, so a retry
after somebody picks another slug succeeds.

**Both refusals are in the contract now**, as
`environment_must_match` (422) and `slug_conflict_is_not_adoptable` (409), each
carrying its status code — a rule with no status is a rule no test can assert,
which is how these came to be implemented in the product and written down in
neither half of the contract. `contracts/product-platform.v1.json` ships
identically to both profiles and to `koras-control-plane`, and the starter's
parity test holds the two copies in step.

**Verified by mutation, not by the tests merely passing.** Reverting the 409
mapping to `AlreadyExistsError` fails two of the new contract tests; the product
side was mutated too, and that found a weakness in my own first attempt — an
assertion that the router "mentions `settings.environment`" passed with the
branch disabled, because the value is also interpolated into the message. It
asserts the comparison itself now.

Control Plane: 672 passed. Starter: 873 in the generator, 12 in a freshly
generated product's contract suite.

**One stale claim fixed while in there.** `reference_product.py` said it mirrors
`services/api/src/routers/platform.py`; the router has been at
`services/api/koras_api/routers/platform.py` for some time. The file whose whole
purpose is to mirror another named the wrong path to it.

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

**What is still the Control Plane's alone.** `ProductPlatformAdapter` has one
implementation and it is `MockProductPlatformAdapter`, so the real HTTP adapter
that a live provisioning run would use does not exist yet. What is fixed here is
the client the contract tests exercise; whether the engine surfaces a held job
to an operator usefully is a question that arrives when that adapter is wired.
F3 — which identity may register at all — is untouched.

---

## Decisions this repository can make, and has not

### F4 — what `packages/control-plane-client` is for — closed 2026-08-30

- [x] Decide whether the package should exist
- [x] It should not: removed, with the `control_plane_client` capability

Tracked as `SYNC_BACKLOG.md` A4. Its `ProductRegistration` type could not produce
a request the Control Plane accepts — every field either missing from the schema
or rejected by `extra="forbid"` — and nothing imported it, which is why no one
had noticed.

**Deleted.** Three things settled it, and the third is the one that made the
decision safe rather than merely tidy.

*Nothing imported it*, checked on `koras-e2e-shop` — a real provisioned product,
not just the templates — where not even a `package.json` dependency edge pointed
at it.

*Both working implementations live outside the product by nature.* Registration
is performed by `src/registration/` in the generator and by
`register-with-control-plane.sh` from CI. One is in the factory and the other is
bash; neither could import a workspace package even in principle. Registration
is something done *to* a product by the machinery that builds it, not something
the product's application code performs — which is the actual reason this package
never had a caller, rather than an oversight anyone could have corrected.

*No second caller was coming.* `PRODUCT_REGISTRATION_CONTRACT.md` has exactly two
directions: registration outbound, and the tenant endpoints inbound. There is no
entitlement pull or any other product-initiated call, so a runtime outbound
client had nothing to be for.

**The delicate part was the capability, not the package.** `control_plane_client`
gated the package *and* the `KORAS_CONTROL_PLANE_URL` / `KORAS_CONTROL_PLANE_TOKEN`
declarations in `secrets.manifest` and `.env.local.example` — one flag doing two
unrelated jobs. Removing it without ungating those would have left every product
unable to declare the two settings its own deploy-time registration reads, which
is a worse defect than the one being fixed. They are unconditional now: a product
does not optionally register.

**Verified by generating**, not by the tests passing. Package absent, both
settings present, and the generated product builds, typechecks and lints — 21,
30 and 30 tasks green. The absence is asserted in three suites rather than left
to be noticed, because a package that quietly reappears is how the outbound and
inbound halves get conflated again — which has already happened once.

**One behaviour change:** `--without control_plane_client` is no longer a valid
component name. Nothing in CI passes it.

`PROFILE_ARCHITECTURE.md` keeps the outbound/inbound explanation and says why the
package went, rather than losing the reasoning along with the code.

### F4a — the plan catalogue was empty and had no user interface — closed 2026-08-29

- [x] Build the plan, entitlement and subscription forms the console is missing

**Closed 2026-08-29**, in `koras-control-plane`. Same work as F9; kept here
because this is where it was first written down.

What it needed beyond the five forms: `GET /entitlements`, which had never
existed. A form for what a plan grants has to name an entitlement, and nothing
could tell it which exist.

### F5 — `apps/marketing` declares Tailwind and imports no stylesheet — closed 2026-08-30

- [x] Give it a `globals.css`, or drop `tailwindcss` from its `package.json`

Noted in the promotion patch's own "not included" section and carried into
`SYNC_BACKLOG.md` A6, which this closes — it was that entry's last open box.

**Decided: it gets a `globals.css`.** The design question was real, and one fact
settled it. `apps/marketing` already depends on `@koras/ui` and names it in
`transpilePackages`. That package is a stub today (`export {}`), and
`koras-control-plane` TS-11 is the queued promotion of thirty Tailwind-classed
components into it. Dropping the dependency would leave the one application whose
entire purpose is styled pages unable to render the shared components it is
already wired to — and the failure would arrive as A6's own symptom one
application later, an element rendering unstyled with its class name as the
obvious suspect rather than the build.

Three files, matching `apps/web` exactly: `postcss.config.mjs`, a `globals.css`
of one `@import`, and the import in `layout.tsx.hbs`. `package.json.hbs` is
unchanged, because `tailwindcss` and `@tailwindcss/postcss` were already
declared there. That is what made this a defect rather than an absence: the
dependency was paid for and did nothing.

**Verified by generating rather than by reading**, which is the failure mode
this repository has had repeatedly. `--with marketing` into a scratch directory,
installed, `turbo run build` green across all 23 tasks. The built stylesheet
contains no literal `@tailwind utilities`. Adding six utility classes to the
generated page and rebuilding compiled all six and took the sheet from 4,039 to
4,896 bytes — only the classes used, which is precisely the behaviour that was
missing.

No manifest change was needed: `template_map` maps `marketing: apps/marketing`
as a subtree, so new files under it are emitted with the component.

### F5a — `doppler-bootstrap` cannot express a legitimately empty setting — closed 2026-08-29

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

### F14 — two names for the Control Plane, and neither side noticed — closed 2026-08-29

- [x] Declare the settings under the names Doppler actually holds
- [x] Correct the runbook an operator follows
- [x] Extend `test_settings_are_declared.py` here to the Python services

**Closed 2026-08-29.**

An earlier version of this line read *"closed apart from the last box"* while
all three boxes were ticked. The boxes were right: the shared test is
`profiles/_shared/template/tests/security/test_settings_are_declared.py` and it
reads pydantic `Settings` fields, as the paragraph below has always said. The
sentence was left over from a plan and contradicted the entry containing it —
R-042 exactly, in the register that names it.

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

### F15 — a project generated then provisioned had no way into its own repository — closed 2026-08-30

- [x] A `--push` flag
- [x] The `--provision-only` path says how, instead of only what did not happen

**Found by noticing**, which is the point. `koras-e2e-shop` was provisioned with
`--provision-only`, and its GitHub repository held one auto-init commit and a
README while the whole project sat on disk, untracked. Nothing was wrong with
either half; there was no supported way to connect them.

`--provision` pushes as its last step, via `initAndPushToDevelop`.
`--provision-only` deliberately does not, and that is right: it operates on a
tree the operator owns, and writing files and committing during what was asked
to be an infrastructure operation would be the opposite of what this CLI
promises. But there was no third option.

**The silence was the worse half.** The seven manual steps existed — and printed
only when an *attempted* push failed. The path that never attempts one showed
nothing, so `--provision-only` reported `nothing was committed`: the fact,
without the remedy. A defect whose symptom is an accurate message is one nobody
reports.

`--push` reads the repository name from **Terraform outputs**, not from
`.koras/project.yaml` — which does not record it — and not from a guess at
`<org>/<slug>`. Pushing a product's source into the wrong repository is not a
mistake a retry undoes. It changes no infrastructure: `readOutputs` runs `init`
and `output -json` and has no path to a plan or an apply.

Both refusals were exercised against real projects rather than asserted:

```
--push on a project that is already a repository
  -> "Git repository already initialised — nothing pushed."
--push on a project never provisioned
  -> "f15-check has no Terraform state, so no repository has been created for it."
```

The guards it inherits are the ones that matter. `initAndPushToDevelop` asks
before pushing, refuses a directory that is already a repository, and checks for
Terraform state artifacts **before** `git add` rather than after — the commit is
pushed moments later, and a credential that reaches a remote is published
whether or not a later commit removes it. That is F1's whole lesson.

**`koras-e2e-shop` was pushed by hand before the flag existed**, following the
same sequence. 384 files, verified in a copy first: no plan file, no state, no
`.env`, and `terraform.tfvars` carrying non-secret inputs only. The `update-ref`
graft onto `origin/develop` made it a plain fast-forward, which is what branch
protection requires — a force push is declined with GH006.

---

---

### F16 — a customer's own branding has nowhere to be read from — opened 2026-08-31, closed 2026-09-01

- [x] Add a customer-facing route to `services/api` returning the calling
      tenant's `tenant_settings.branding`
- [x] Call it from `apps/web/src/lib/tenant-branding.ts`

`customer_branding` and `white_label` are declared capabilities of the product
profile, `public.tenant_settings.branding` has been a `jsonb` column since the
first migration, and until 2026-08-31 nothing read it or wrote it. The frontend
half was built first: `BrandScope` re-declares the brand tokens for the signed-in
subtree, `ProductLogo` takes the customer's mark, and `parseTenantBranding`
decides which of the stored values may reach a stylesheet. Twelve tests in the
generated project argue that last part, because the column is customer-controlled
data on its way into a CSS custom property and a custom property value is not
escaped the way text content is.

**Closed 2026-09-01**, and the route was the smaller half of the work.

`GET /api/v1/tenant/settings` returns the tenant's name, slug, branding and
features — one row, one call, because the shell paints itself from the branding
and resolves its navigation from the features on the same page load, and two
endpoints could disagree about which version of that row a page came from.
`apps/web/src/lib/tenant-settings.ts` wraps it in React's `cache`, so three
readers make one request per render.

**What actually blocked it was resolving a tenant at all.** Every policy in
`00002_rls_policies.sql` is keyed on `current_tenant_id()`, which is a tenant's
primary key. A customer's request carries no such thing — a verified token names
a ZITADEL *organization*, and the organization-to-tenant mapping lives in the
table the policies protect. So the first read of any customer request was the
one read no policy admitted, and nothing had noticed because no customer-facing
route existed: `resolve_tenant` fabricated a `TenantContext` out of the
organization id, and had anything called `get_db`, `current_tenant_id()` would
have tried to cast a numeric organization id to a `uuid` and failed.

`00004_tenant_settings_read.sql` gives the policies a second key the request
genuinely has: `public.current_organization_id()`, and one permissive select
policy admitting the single tenant whose `zitadel_org_id` matches. Nothing new
is trusted — that value comes from the same verified token the tenant id did,
and it is set transaction-locally by one function for one query. The
alternative, a `security definer` lookup with the policies suspended, would have
been a privilege escalation kept narrow by convention rather than by the
database. `supabase/tests/040_organization_lookup.sql` makes the narrowness
checkable: the lookup opens for exactly one row, opens for none with no context
set, reaches no settings row without tenant context, and grants no write.

**Three things came unblocked, not one.** The features column has its first
reader, so the shell's tenant-feature gate works rather than being permanently
off; and the workspace badge shows the organisation's own name instead of
rendering nothing, because it no longer has only a uuid to offer.

`packages/api-client` stopped being a two-line stub in the same change. It is
where the timeout, the credential and the error shape now live, so the next
call to this API is not a fifth opinion about all three.

**What is still not read from anywhere is the plan.** That is F17, and it is a
different blocker: a Control Plane authorization decision rather than a route
this repository can write.

### F17 — a product cannot read its customers' entitlements — opened 2026-08-31

- [ ] Decide which credential authorises a product reading its own entitlements
- [ ] Call the Control Plane from `apps/web/src/lib/entitlements.ts`

The authenticated product shell resolves navigation against four gates:
capabilities, permissions, tenant features and **plan entitlements**. Three of
them work. The fourth cannot, because a product has no way to ask.

The Control Plane resolves a plan code and a list of effective entitlements per
organisation and product, and the route that answers is part of its *platform*
API — the private surface authorised by the estate-wide `registrar` service
account. A product must not hold that credential at runtime: it authorises
writes to every other product's registry entry, which is exactly the argument
that keeps the deploy-time registration job off by default (F2b).

So this needs one of two things, and both are decisions about the platform's API
surface rather than product work:

1. a customer-facing entitlements route, authorised by the caller's own token
   the way the signup plan catalogue is anonymous; or
2. a per-product service-account credential scoped to reading that product's own
   entitlements — which is F3 by another name, and would close with it.

`apps/web/src/lib/entitlements.ts` holds the seam, the mapping and the reason.
The parser is written; only the call is missing.

**The failure direction is already correct.** An unresolved entitlement set
counts as *not entitled*, so a plan-gated module is hidden or shown locked and
the rest of the product is untouched. The opposite convention would make an
unreachable Control Plane the way to obtain a paid feature. Nothing is hidden
today because the shipped registry gates nothing on a plan — the moment a
product writes `requiredEntitlements` on a module, that module goes dark until
this is closed, which is the safe direction and worth knowing about in advance.

**Blocked on the Control Plane**, like F2b and F3.

### F18 — no test in this repository opens a browser — opened 2026-08-31

- [ ] Decide whether a browser harness belongs in the starter or in a product

The starter has no Playwright and no browser-driven test of any kind. The
`webapp-testing` skill is vendored and unused. Everything the frontend asserts
is structural — the generator reads the templates, and the generated project
runs `node --test` over pure functions.

That was proportionate while the signed-in area was one page. The product shell
adds behaviour a text search cannot check: the drawer's focus trap, Escape
returning focus to the toggle, the drawer closing on navigation, the collapsed
sidebar keeping accessible names, and layout at 375 through 1440.

What *was* verified on 2026-08-31, without a browser, is more than it sounds.
The built application was started and probed with real signed session cookies,
one per organisation role: the sidebar a plain member receives contains Home and
nothing else, an administrator's contains the Administration group, and the two
settings routes answer 403 to the member, 200 to the administrator and 404 for a
path no module claims. The rendered markup carries one `#main-content`, the
labelled navigation landmarks, `aria-current="page"`, and both disclosure
toggles pointing at elements that exist unopened. That covers the security
claim, which is the one that matters; it does not cover the interaction.

**Not blocked.** It is a question of where the harness lives. A browser test in
the starter tests a project the starter does not have, so it would have to
generate one first — which is what `generated-builds.test.ts` already does, at a
cost of three minutes a run.

## The customer-onboarding sequence

Five pieces, in the order they unblock each other, from the review on 2026-08-29
of how a customer gets from nothing to a working tenant.

**All of it closed on 2026-08-29 except F13**, which is a commercial decision
rather than an implementation. A customer can go from a product's `/signup` page
to a provisioned tenant with a welcome email, choosing from the plans that
product actually sells, without a member of staff touching anything.

One setting decides whether that works in a given environment: without
`SMTP_HOST` the sender records instead of sending. It is `optional` in the
Control Plane's manifest, so a deployment does not demand it, which makes that
failure silent — deliberately, since a product without a mail transport is a
product still being set up. It holds a value in all four environments as of
2026-08-29.

An earlier version of this paragraph said neither setting had a value yet. Both
did, in all four configs, and the sentence was carried forward through an edit
without being checked — which is the *why* half of R-042 doing exactly what that
entry says it does.

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

That derivation makes the Control Plane depend on three shapes owned here: the
`web` application is served at the `app` label, every environment but prod
suffixes it as `app-<env>`, and the signup page is at `/signup/verify`. All
three are asserted in `tests/docs/signup-verify-contract.test.ts`, because the
symptom of changing any of them is a customer who cannot finish signing up and
has no way to report why.

**The values it replaces were already wrong**, which is the argument for
deriving rather than setting. Read on 2026-08-29, `SIGNUP_VERIFY_BASE_URL` held
`https://web-dev.koras-e2e-atlas.korastechnologies.com/signup` and the three
matching hosts, while the DNS records for that estate are `app-dev.…`,
`app-test.…`, `app-stg.…` and `app.…`. Every verification link those four
environments would have sent pointed at a host that does not resolve. Nothing
reported it: the setting had a value, the task found one, and the mail was
built. A derived host cannot be wrong in that way without the derivation being
wrong for everyone at once, which is the kind of wrong that gets noticed.

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

### F9 — the plan catalogue could not be authored — closed 2026-08-29

- [x] Five client methods and a form per page, per `COMMERCIAL_CATALOGUE.md`
- [x] The read that was missing, so a form can name a capability
- [x] Browser coverage of each write

**Closed 2026-08-29**, in `koras-control-plane`. F4a closes with it.

One thing that document did not anticipate: `PUT /entitlements` had existed
since the entitlement work with nothing reading it back, so a form for what a
plan grants had no way to name an entitlement. `GET /entitlements` was added
with the forms.

### F10 — the tenant store was in memory — closed 2026-08-29

- [x] Persist tenants rather than holding them in a module-level dict
- [x] Keep the lookup by `tenant_key` first, and 200 apart from 201
- [x] Policies that let a call with no tenant context create one

**Closed 2026-08-29.** `core/tenant_store.py`, migration `00003`, and
`supabase/tests/030_provisioning_context.sql`. The last of those found a real
defect on its first CI run — an `on conflict` naming an arbiter needs the
table's select policies, and `tenant_members` had been given insert alone.

### F11 — there is no way for a customer to start signing up — reopened 2026-08-30, and closed again the same day

- [x] An unauthenticated signup endpoint on the Control Plane
- [x] Rate limiting, and address verification before a job is created
- [x] A column on a plan saying it may be bought unattended, defaulting to false
- [x] A signup surface in the product template
- [x] An anonymous way to learn which plans are on sale
- [x] **Any of it actually working** — added 2026-08-30, when the first person
      tried to use it

**Every box above was ticked on 2026-08-29 and not one customer could have
signed up.** The pieces were all present and the path between them was broken
in five places, each hidden by the one in front of it. Found on 2026-08-30 by
opening the page on a deployed product and trying:

| Where | What | Fixed by |
|---|---|---|
| product `middleware.ts` | `/signup` redirected to `/login?next=/signup` — you needed an account to make one, and `/signup/verify` is where an *email link* lands | starter `0d29fa1` |
| Control Plane `signup.py` | all three anonymous endpoints opened transactions without declaring a caller, so `GET /plans` had answered **500 to every request it ever received** | control-plane `d00e0de` |
| Control Plane `plans` | `self_serve` was read by two queries and written by nothing — no request model, no endpoint, no form. Every plan was created `false` and could not be changed except by editing the database | control-plane `cfb871b` |
| product `signup/page.tsx` | prerendered at build time with the empty list the 500 produced, so a plan created later never appeared — `X-Nextjs-Prerender: 1` | starter `7cf5d6a` |
| Control Plane `tasks/` | `send_signup_verification` had the same undeclared-caller fault, so the email was never sent — while the page said "check your email" and the API logged `202` | control-plane `3f1f697` |

**What each entry teaches is the same thing.** Every one of them passed its own
tests. The Control Plane's integration suite inserts plans with raw SQL, so the
write path was never exercised; it builds its own engine without `install_rls`,
so the listener that fails in production is absent from the only place those
repositories are tested. Nothing was wrong with those tests — they test what
they say they test. The gap is that no test ran the *sequence*.

**The last two are the ones worth remembering.** The prerendered page and the
unsent email both **reported success**. A visitor was told to check their email
by a page that was right to say so, and the API logged `202 Accepted`, correctly,
because the send is asynchronous. A failure that announces itself gets fixed;
these needed somebody to notice an email that never arrived.

**Closed again 2026-08-30**, with the form rendering and a live plan in it. Not
end to end: nobody has yet clicked a link in a delivered email and had a tenant
provisioned. Until that happens this entry is closed on the same kind of
evidence it was closed on the first time.


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

### F12 — a provisioning run finished and told nobody — closed 2026-08-29

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

- [~] Observe the `register` job run in a generated project's deployment —
      **cannot be closed as written**, see below
- [x] Observe *generation-time* registration send a real payload — 2026-08-30
- [ ] Confirm the Control Plane's stored references change as a result — needs a
      staff read, which the registrar identity cannot perform

What has been checked: the payload validates against the Control Plane's real
request model; the script refuses on a generated control-plane project with a
URL and token configured; every failure and skip path is asserted by
`registration-lifecycle.test.ts`.

**What has been observed since, on 2026-08-30.** The *identity* half is proven
against the live dev estate, twice — by `pnpm koras:token` and by the
generator's own resolution and minting path. Both returned a JWT and a `422`
from the Control Plane on an empty body, which is the identity passing. See F2a.

**A real payload was sent on 2026-08-30**, and this is what it found.

`koras-e2e-shop` was provisioned — 8 providers, 4 Supabase projects, 4 ZITADEL
instances, 8 Vercel projects, 8 Fly apps — and its registration **timed out
twice** at the 15,000ms default. The estate was intact and nothing was rolled
back, which is the behaviour R-001 asks for.

The cause was not an unreachable Control Plane. Timed with the budget raised:

```
readOutputs   : 4,190ms
registration  : registered in 14,749ms
```

**It was failing by about 250 milliseconds.** The default is 60s now, with the
measurement in the comment.

What hid this is worth recording, because every check before it was green.
Every earlier probe used an **empty body** and came back in 203-621ms — but a
`422` is refused at validation *before the request touches the database*, so a
fast answer proved the identity and nothing whatever about the cost. A real
payload writes a product row, four environments, their references and their
services. The Control Plane also runs on Fly and stops when idle: 4.6s to
cold-start, ~0.5s warm, measured the same day. Registration is the last step of
a long provisioning run, so it is reliably the first request after an idle
period.

This is exactly the defect class this entry exists to catch, and nothing but a
real payload against a real registry could have found it. The identity probes,
the 33 unit tests and the contract tests were all green throughout.

**A second finding, from the same run.** The failure message told the operator
to retry with `--provision-only` — a full plan across eight providers and an
apply — to recover from one failed HTTP request. `--register-only` had been
added that morning and the recovery guidance was never pointed at it. Fixed.

**Why the last box is still open.** Confirming the *stored* references means
reading the registry, and `GET /api/platform/v1/products` answers `403 This
endpoint is restricted to platform staff` to the registrar. That is correct —
the registrar is a machine identity that registers and cannot read — so this
needs the console or a `STAFF_TOKEN`, neither of which a session can obtain.

**The first box contradicts F2b, and F2b wins.** F2b turned the deploy-time
`register` job off by default on the same day, because the only credential that
can register today is estate-wide and putting it in a product's CI gives that
product write access to every other product's registry entry. So "observe the
job run in a deployment" now requires deliberately enabling the thing F2b says
must stay disabled. Two entries written days apart, each right on its own, and
together unsatisfiable — worth stating rather than leaving for whoever tries to
close this one.

The second box is what is actually reachable, and it is the more useful test
anyway: generation-time registration is the path every product takes, it is on
by default, and it has never run in this estate either.

**And a second blocker arrived on 2026-08-30, unrelated to either.**
`koras-e2e-shop` was pushed and both its workflows failed in six seconds with no
job started: Actions billing. A product repository is private by design, private
repositories consume paid minutes, and this account's payment is failing. The
`register` job is listed in run `33325368170` and was never started. So the
first box is blocked twice over now — once by F2b's deliberate default, once by
something no code in this repository can reach. See R-030, reopened for
products.

---

**What the first real deployment found, later that same day.** Billing was
resolved that evening and `koras-e2e-shop` deployed. This is the entry that
argued only a real run would find certain defects, so what it found belongs
here. **Seven, each hidden behind the one in front of it:**

1. `create_async_engine` was handed a driverless `postgresql://`, which
   SQLAlchemy maps to psycopg2 — a dependency of neither service — so the API
   died at import. Both templates lacked a validator the *running* Control Plane
   had carried since it was deployed (`4d3508f`).
2. `create-app-role.sh` dropped the pooler's tenant suffix when swapping the
   role into the URL, refusing every connection with `ENOIDENTIFIER`. Correcting
   it by hand worked; **re-running the script put the broken value straight
   back**, which is how it was found twice (`9d93e18`).
3. A worker image missing a manifest its root `pyproject` names (`4c81e5f`).
4. `/signup` was gated behind the session check — you needed an account to make
   one (`0d29fa1`).
5. Every anonymous Control Plane endpoint opened a transaction with no declared
   caller, so `GET /plans` had answered 500 to every request it ever received
   (`d00e0de`).
6. `plans.self_serve` was readable and unwritable, so no plan could be put on
   sale by any supported means (`cfb871b`).
7. The signup page was prerendered with the empty answer from when it was
   broken (`7cf5d6a`), and the verification email was never sent — the same
   undeclared-caller fault as (5), one layer down (`3f1f697`).

**Not one was reachable without deploying a real product**, and every one passed
the tests that existed. That is this entry's argument, demonstrated rather than
predicted.

**The pattern worth carrying forward is in the last two.** Both *reported
success*. A page told a visitor to check their email and was right to; an API
logged `202 Accepted` correctly, because the send is asynchronous. The only
evidence was a traceback in a worker log nobody reads when the thing in front of
them says it worked. A defect that announces itself is cheap; these are not.

**Also observed, and worth recording as a pass rather than a finding:** the
whole pipeline ran — Components, Preflight, Settings present, Migrate, Deploy ×4
and Verify green — and `Register with the Control Plane` was **skipped**, by
F2b's condition, visibly. That is what the change was for.

**Why not done here:** deploying and provisioning are out of scope for this
session by instruction.

### F8 — the `--with` / `--without` generation paths remain untested — closed 2026-08-29, the entry was wrong

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

