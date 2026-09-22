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

## What to do first

The index below is ordered by when an entry was opened, which is the one order
that says nothing about what to do next. This says it, and it is a
recommendation rather than a record — revise it, do not preserve it.

| Order | Entry | What is left, and why it is here | Rough cost |
|-------|-------|----------------------------------|------------|
| 1 | **F27 — the settings framework, reviewed and exercised** — *both halves have run and it is still **OPEN**. The review ran 2026-09-19 (BLOCK, four fixed). The closure cycle ran 2026-09-21: all eighteen carried findings reconciled against a running product, the four Highs plus SET-23 fixed. **Eleven of fifteen** manual cases now pass — nine by 2026-09-21, TEST-SET-13 off the shop's un-migrated local database, and TEST-SET-11 and TEST-SET-12 in a live sitting against deployed dev on 2026-09-22.* | **What is left is four manual cases, and none of them is code.** TEST-SET-10 needs the Control Plane console; TEST-SET-14 needs a person with a screen reader; TEST-SET-04 needs one plain-`member` account for the half that is not already proven at the API; and **TEST-SET-01 is now blocked by a live defect rather than a missing page** — `koras-e2e-shop` has the orders table the case needs, and on 2026-09-22 `/dashboard/orders` returned HTTP 500 on dev while every other dashboard page answered 200. Fixing that belongs to the shop's orders feature, not here. Detail in `docs/features/settings-framework/testing/manual/manual-test-results.md`. | ~2h once a console and a second account are to hand |
| 2 | **F28 — data import Phase 1, reviewed and exercised** | The same shape as row 1, one day later and on newer code. Phase 1 shipped on 2026-09-19: two new tables with row-level security, eight routes over a customer's own records, a mapping allowlist that decides which columns an import may ever reach, a parser fed files from outside the product, and the first enqueued job this repository has ever had. None of it has been seen by anybody but the session that wrote it, and `docs/features/data-import/manual-test-plan.md` has twenty-two cases and twenty-two blank verdicts. The parser is the part worth an independent look first: it is the only code in the estate that reads a file a stranger chose. | ~1 day for the review, ~half a day for the pass |
| 3 | **F21 — live mode** | The only entry with money on the other end. Every phase is built and every test-mode box closed on 2026-09-15, including a signup watched from the form through Stripe's checkout to the owner's password. What remains is the walk from test mode to live: activate the account, make the live catalogue, mint a restricted live key, register a prod webhook endpoint, configure the customer portal, and sign up once yourself with a real card and cancel inside the trial. `koras-control-plane/docs/runbooks/stripe-go-live.md` steps 1, 3, 5 and 7, in that order. Nothing here is code. | ~½ day at the Stripe dashboard |
| 4 | **The live sitting** | Three things needing the same estate and the same credentials, which is why they are one item and not three: **R-036**'s second provision-and-teardown now that Cloudflare is in the inventory; the **F17 token audience**; and one `--register-only` for `koras-e2e-shop`, which would be the estate's first *confirmed* registration now that the Control Plane echoes what it stored. Run separately they pay the setup cost three times. | ~half a day |
| 5 | **F23 — the other three environments** | dev has the product's own sign-in and a customer has signed in on it. test, stg and prod need two ZITADEL writes per instance that only a person can make — grant the worker `IAM_LOGIN_CLIENT`, set the Console application to Login V2 — and then the instance feature flipped, **and only after the environment is promoted**, because with the feature off ZITADEL sends sign-ins to the application's base URI and `/login` is a 404 there. | ~1h per environment |
| 6 | **F3 + F2b** | One Control Plane authorization decision arriving from two sides: may a product hold a credential that can rewrite its own registry entry, and if not, what is the narrower machine role. Not urgent while there is one product — the risk is one product's CI holding write access to *other* products' entries, and as of 2026-09-15 the blast radius is still itself. Deploy-time registration stays off until it is answered. | ½ day to decide, more to build |
| 7 | **F19 — the DNS half of the asset fetch** | The branding route refuses raw addresses and private suffixes at two gates, and a *name* that resolves to a private address still passes both. Closing it needs resolving the host, refusing loopback, RFC1918, link-local and unique-local answers, and connecting to the address rather than the name — which needs the socket rather than `fetch`. | ~half a day |
| 8 | **F22 — Files** | Six items, each waiting on a real trigger rather than on time: multipart uploads (a file over 5 GB), an orphan sweep, the `customer-owned` and `azure-blob` policies, a real upload in CI, a foreign bucket's origin in the browser policy, and quota by period. | ~1 day per item |
| 9 | **F25 — reporting** | Three items, none of which blocks a product registering reports today: `reporting.api` enforcement becomes real with the first machine caller, pre-aggregation when a table outgrows a range scan, and report names in the customer's language when somebody asks for one. | ~1 day per item |

**F21 and F23 do not contend with the top row.** They are a person at a dashboard and two ZITADEL writes per instance; nothing in either is code, so an order that reads as a queue is misleading for those two. Run them whenever the dashboard is open.

**Read the entry before working it.** F2c, F6 and F13 all closed on 2026-09-01,
and two of them closed by being *checked* rather than built — F2c's backfill had
no subject, and F13's recommendation was already shipped. F7 closed on
2026-09-15 the same way round: the work it needed turned out to be a smaller
change in the other repository than the one this entry had been describing for
two weeks.


F13's prerequisite sat at the top of this table for part of one day and is
built: `koras-control-plane` R-93, which made `subscriptions.status` mean
something before anything drives it. It is mentioned here rather than deleted
because the shape is worth keeping — the first item on a list of *this*
repository's follow-ups belonged to another repository, and was found by reading
an entry rather than by working one.

F2c, F6 and F13 were 1, 5 and 3 on this list until 2026-09-01. All three closed
the same day, and two of them closed by being *checked* rather than built: F2c's
backfill had no subject, and F13's recommendation was already shipped. What each
left behind was a finding worth more than the entry — which is the argument for
reading an entry before working it, and the reason the top row of this table now
belongs to another repository.

**Do the live work in one sitting.** F7's read, R-036's second teardown and the
F17 token audience all need the same estate and the same credentials, and run
separately they pay the setup cost three times.

Adjacent work competing for the same hours lives elsewhere on purpose:
`SYNC_BACKLOG.md` D6 is the last open sync gap, and R-036 and R-042 are in
`RISK_REGISTER.md`. This document does not rank them; it only notes that they
exist and that the hours are the same hours.

## The index, in number order

F22 — the Files module shipped on 2026-09-08 with the platform's policy and
quota wired through; what it deliberately leaves out is below.

F23 — the sign-in page is the product's own since 2026-09-11, posting to the
Control Plane's session routes; the self-hosted ZITADEL login planned on
2026-09-09 was not built, for the reason recorded in the entry.

F24 — the AI foundation shipped on 2026-09-13 as the `ai` capability; what it
deliberately leaves out is below, and the first item is a real model call.

F25 — the reporting framework shipped on 2026-09-14 as the `reporting`
capability; what it deliberately leaves out is below.

F28 — data import Phase 1 shipped on 2026-09-19 as the `data_import`
capability, off by default; what it leaves out is below.

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
| F2c | every product registered before 2026-08-28 has a null callback address | closed 2026-09-01 — fixed forward, not migrated | Blocked here |
| F3 | which credential should authorise a product's own re-registration | **open** | Blocked here |
| F3a | the tenant endpoints answer 422 and 409, and the Control Plane was not told | closed 2026-08-30 | Blocked here |
| F4 | what `packages/control-plane-client` is for | closed 2026-08-30 | Decisions |
| F4a | the plan catalogue was empty and had no user interface | closed 2026-08-29 | Decisions |
| F5 | `apps/marketing` declares Tailwind and imports no stylesheet | closed 2026-08-30 | Decisions |
| F5a | `doppler-bootstrap` cannot express a legitimately empty setting | closed 2026-08-29 | Decisions |
| F6 | the two references deploy-time registration cannot carry | decided 2026-09-01 — no, with a stated trigger | Decisions |
| F7 | nothing has exercised the register job in a real pipeline | closed 2026-09-15 — every registration verifies itself | Verification |
| F8 | the `--with` / `--without` generation paths remain untested | closed — *the entry was wrong* | Verification |
| F9 | the plan catalogue could not be authored | closed 2026-08-29 | Onboarding |
| F10 | the tenant store was in memory | closed 2026-08-29 | Onboarding |
| F11 | there is no way for a customer to start signing up | reopened and re-closed 2026-08-30 | Onboarding |
| F12 | a provisioning run finished and told nobody | closed 2026-08-29 | Onboarding |
| F13 | nothing bills anyone, and that is not an oversight | decided 2026-09-01 — trial-only, and the trial never ends | Onboarding |
| F14 | two names for the Control Plane, and neither side noticed | closed 2026-08-29 | Decisions |
| F15 | a project generated then provisioned had no way into its own repository | closed 2026-08-30 | Decisions |
| F16 | a customer's own branding has nowhere to be read from | closed 2026-09-01 | Decisions |
| F17 | a product cannot read its customers' entitlements | closed 2026-09-01 | Decisions |
| F18 | no test in this repository opens a browser | closed 2026-09-01 | Decisions |
| F19 | a customer's platform branding was stored and never rendered | logos closed 2026-09-15 — one box left, the DNS half of the fetch | Decisions |
| F20 | a product speaks one language | closed 2026-09-15 — phase 2 took the last four boxes | Decisions |
| F21 | somebody can now be billed, and nothing yet asks them to be | every phase built by 2026-09-07; test mode verified 2026-09-15 — live mode open | Onboarding |
| F22 | Files: what the first storage module leaves out | shipped 2026-09-08 — six boxes left, none urgent | Verification |
| F23 | the sign-in page, on a host of ours | built 2026-09-11, live on dev — test, stg and prod left | Verification |
| F24 | the AI foundation: what the first shared AI layer leaves out | closed 2026-09-15 | Verification |
| F25 | the reporting framework: what the first shared reporting layer leaves out | shipped 2026-09-14 — three boxes left, each waiting on a trigger | Verification |

**What is open, as of 2026-09-15.** Two entries are open in the sense of
waiting on a decision — **F2b** and **F3**, which are one Control Plane
authorization question arriving from two sides, and neither is this
repository's to close alone. Five more are open in the sense of having boxes
left: **F19** (one, the DNS half of the asset fetch), **F21** (live mode),
**F22** (six), **F23** (three other environments, plus second-factor
enrolment and the Control Plane's own portal) and **F25** (three). Two entries
carry a box that will never close as written, and each says so where it stands:
F2a's Terraform question and F7's first box.

Nothing is open for lack of a decision here. Every remaining item is waiting on
a person at a dashboard, a live estate, another repository, or a customer who
needs the thing.

**F13 was decided on 2026-09-01**: trial-only, which is already what the code
does. Checking that found the useful half — nothing expires a trial, and
entitlement resolution ignored `subscriptions.status` altogether, so a
cancelled customer resolved the same entitlements as a paying one. Fixed in
`koras-control-plane` as R-93.

Closed on 2026-09-01: F16, F17, F18, F2c, F6 and F13. F2c closed by being run —
`--register-only` executed against the live Control Plane for the first time —
and by the finding that its backfill has no subject, the stale rows belonging to
a product that was deliberately destroyed. F6 closed as a **decision**: no, a
newly added application does not need to reach the registry before the next
provision, with a stated condition that would reverse it.

F16 and F17 both closed on 2026-09-01. F17 had been filed here as blocked on a
Control Plane authorization decision and was not blocked at all: the customer-
facing route it was waiting for already existed, and what was missing was an
audience rather than a credential. The lesson is the entry's, not the code's —
an item recorded as *somebody else's decision* is the kind nobody re-reads, and
this one sat behind a door that was open.

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

### F2c — every product registered before 2026-08-28 has a null callback address — closed 2026-09-01

- [x] Make re-registering something an operator can actually do — `--register-only`
- [x] Re-register the products already in the registry — run 2026-09-01, and the
      answer is smaller than the box implied

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

**Why the last box was still open on 2026-08-30, and why it never closed as
written.**
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

**Closed 2026-09-01, by running it.**

```
create-koras-app koras-e2e-shop --profile product --register-only
  --> terraform init, terraform output -json
  ✓ Registered with the Control Plane.
    Correlation id: 1bece788-0bfc-411f-a8bb-43a33dbb7da2
```

**What that is worth, stated exactly.** It is the first execution of
`--register-only` against a live Control Plane, and it worked end to end: the
credential resolved, Terraform outputs were read, the payload was accepted. It
is *not* the backfill this entry was opened for.

The backfill has no subject and now demonstrably will not get one. The stale
rows belong to `koras-e2e-atlas`, whose infrastructure was destroyed on
2026-08-30 — so there is no Terraform workspace to read outputs from, and
`--register-only` refuses an empty one by design. `koras-e2e-shop`, the one live
product, registered on 2026-08-30 with both fields already in its payload. There
is no third product.

So this closes as **fixed forward rather than migrated**, which is what the
entry above already predicted. The two null columns survive on rows for a
product that is deliberately gone; deregistration is
`REGISTRATION_LIFECYCLE.md`'s gap, not this one's.

**And the read-back still cannot be done by the caller — for a reason worth
recording.** `POST /api/platform/v1/products` answers `ProductResponse`, whose
`environments` field is `list[Environment]`: environment *names*, not the stored
references. So a successful registration tells the caller the payload was
accepted and nothing at all about what the registry now holds. That is not an
oversight in this run; it is the shape of the response, and it means F7's last
box cannot be closed by the identity that registers even in principle.

Two ways out, both the Control Plane's: widen `ProductResponse` to echo the
stored `infrastructure_references`, which would make every registration
self-verifying; or accept that confirming the registry needs a staff read. The
first is the smaller change and removes a class of silent failure — a payload
accepted and stored wrongly is indistinguishable from one stored correctly,
today.

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

### F6 — the two references deploy-time registration cannot carry — decided 2026-09-01

- [x] Decide whether a newly added application should reach the registry before
      the next `--provision` — **no**, and the reason has a trigger to reverse it

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

**Decided 2026-09-01: no.** A newly added application does not need to reach the
registry before the next `--provision` or `--register-only`.

Four things settle it, and the fourth is the one that makes the other three
sufficient rather than merely comfortable.

1. **Omission ages a reference; it does not lose one.** Both are upserted and
   never pruned, so the registry keeps what it knew. The gap is a newly added
   application, and it is visible — the registry lists the applications it has,
   not a truncated set that looks complete.

2. **The cost is a widening, not a line of code.** `supabase_project_ref` is
   reachable only through `DATABASE_URL`, so carrying it means the deploy job
   reads a credential to extract a non-credential. `vercel_projects` means
   aggregating per-application repository secrets into one job. Both enlarge
   what a deployment touches, permanently, for a reference that already
   survives.

3. **There is already a complete answer, and it was executed today.**
   `--register-only` reads Terraform outputs and carries both references
   correctly — run against the live Control Plane for `koras-e2e-shop` on
   2026-09-01. It is operator-initiated rather than automatic, which is the
   whole of the difference, and it changes no infrastructure.

4. **Deploy-time registration is switched off.** F2b turned it off by default on
   2026-08-30, in `deploy.yml`, because the only credential that can register is
   estate-wide. So these are two references that a job which does not run cannot
   carry. Building either mechanism now optimises a path nothing takes, and the
   design it would be built against is the one F3 has not made yet.

**What would reverse this.** If F2b and F3 resolve into a per-product credential
and deploy-time registration is switched on by default, a newly added
application's references go stale between provisions rather than being refreshed
by the operator who added it — and the same decision that makes the job safe
also makes reading a project reference inside it less objectionable, because the
identity doing the reading is that product's own. Revisit then, and not before.
Recorded here rather than closed silently, so the reversal has a stated
condition instead of somebody's memory.

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

**What was still not read from anywhere is the plan.** That was F17, filed as a
different kind of blocker — a Control Plane authorization decision rather than a
route this repository can write. It closed the same day, and the filing was
wrong: see below.

### F19 — a customer's platform branding was stored and never rendered — opened and closed 2026-09-04

- [x] Read the Control Plane's portal branding from `apps/web/src/lib/tenant-branding.ts`
- [x] Parse it in the platform's names, and assert them
- [x] Decide how a product renders the platform's logos under `img-src 'self'` —
      decided and built 2026-09-15: the product serves them from its own origin
- [ ] Resolve the host before fetching it, and connect to the address rather
      than the name — the one thing the two gates below do not stop

F16 closed with the product reading `tenant_settings.branding` — its own
column, which nothing writes. The place a customer actually sets their branding
is the Control Plane's portal, and the platform stores what they save. Nothing
in any product read it back. The Control Plane's contract says it plainly:
branding had exactly two readers, platform staff and the customer's own portal,
so a customer could set their colours, be told their product would use them,
and have nothing ever do so. `koras-e2e-shop`'s first customer did exactly that.

**The endpoint offered was not the endpoint used.** The contract's §6a is
`GET /api/platform/v1/tenants/{tenant_key}/branding` — machine identity only,
by tenant key, per environment. A product cannot call it as generated, for
three reasons of different weight. A product holds no machine credential at
runtime, by the F2b argument, and the only machine identity that exists is the
estate-wide `registrar`. The web application does not know its environment
name — `deploy.yml` injects `ENVIRONMENT` into the Fly services and never into
Vercel. And the tenant settings route omits `tenant_key` deliberately. Above
all three, the platform's own R-104 records that the route is unscoped across
products and asks that nothing be built as if the check exists.

The portal surface already had the same values, on
`GET /api/portal/v1/products/{product_code}/branding`, authorised by the
customer's own token with the organization resolved server-side — the exact
shape F17 found for entitlements, with the audience scope already requested at
sign-in. That is the read now made, from `packages/api-client`'s
`fetchBranding`, cached per render beside `tenantEntitlements`. No new
credential, no environment parameter, no tenant key.

**The parser is the half worth arguing, again.** The portal speaks snake case
— `primary_color`, `company_name`, `corner_style` — and `parseTenantBranding`
reads camel case. Feeding the response into the existing parser would not have
failed: every key unknown, every value dropped, and the customer appearing to
have set nothing. That is the F17 defect in a second place, and this time it
was caught before shipping rather than after. `parsePlatformBranding` reads the
platform's names, six tests assert them in both directions, and renaming the
wire field in the parser fails four of them.

**The logos are the open box.** The platform validates its assets as `https`
URLs on its own storage, and the product's Content-Security-Policy is
`img-src 'self'`, so a remote logo is a broken image in every header. The
parser drops them deliberately and a test says so. Closing the box is either a
product serving the platform's assets from its own origin, or a policy
exception for one named origin — and the second is a decision about what a
customer's logo is allowed to load from, which is R-042 territory if it is made
by editing a header and not writing it down.

**Closed 2026-09-15, by the first of the two.** `/api/branding/logo`,
`/logo-dark` and `/icon` on the product's own web tier are the platform's
images, so the policy stays `'self'` and no origin is named anywhere. The
route takes one thing from the browser — which of three names — and resolves
the URL itself from the caller's own session, so there is no parameter to
point it anywhere; the fetch is `https` only, refuses redirects rather than
following them, times out, caps what it will read both by the declared length
and by counting, and admits only image types. It is served back
`private, max-age=3600` with `nosniff`, because a path every customer's page
asks for must never be held in a shared cache. `parsePlatformBranding` keeps
the three URLs apart from the tokens now, which the six tests that asserted
they were dropped were rewritten to say.

The argument for it over the second way out is the one the box was written
with: a policy exception is a decision about where a customer's logo may load
from, made in a header nobody reads and widened every time the platform's
storage moves. The route is the same decision made once, in a file with tests
around it.

**What the gates stop, and the one thing they do not.** The URL is a value a
customer typed into the platform's portal, and the fetch is made from inside
this product's network, so it is checked twice: once when the branding answer
is parsed, and again inside `fetchPlatformAsset`, which is where the socket is
opened. `https` only, no credentials in the URL, not `localhost`, `.local` or
`.internal`, and never a raw IPv4 or IPv6 literal — an address is how a server
gets pointed at something a browser could never reach.

An automated review on 2026-09-15 is why both of those are true. The fetch had
documented itself as "the second gate ... because a function reachable from
more than one caller cannot know the first gate was passed" and then checked
only the scheme; the host rules lived in the parser alone. `api-client` is a
leaf and cannot import `branding`, so the rule is written twice now and a
shared table of cases in `assets.test.ts` is what keeps the two from drifting.
Reading it again found a second thing: `https://localhost./logo.png` keeps its
trailing dot through URL parsing, means exactly `localhost` to every resolver,
and matched none of the string comparisons. Both gates strip it now, and
`localhost.`, `vault.internal.`, the cloud metadata address and a unique-local
IPv6 literal are in the attack table.

**The open box above is what is left.** A name is resolved by the runtime
after the check, so a hostname whose DNS answers a private address still
passes. Closing it means resolving the host here, refusing every loopback,
RFC1918, link-local and unique-local answer, and connecting to the address
rather than the name so the two cannot differ between the check and the
request — which needs the socket rather than `fetch`. What stands in front of
it meanwhile: the platform stores only assets on its own storage, the response
must be an image under two megabytes, and no redirect is followed, so a blind
request is most of what an attacker would get.

### F17 — a product cannot read its customers' entitlements — opened 2026-08-31, closed 2026-09-01

- [x] Decide which credential authorises a product reading its own entitlements
- [x] Call the Control Plane from `apps/web/src/lib/entitlements.ts`

The authenticated product shell resolves navigation against four gates:
capabilities, permissions, tenant features and **plan entitlements**. Three of
them worked. The fourth could not, because a product had no way to ask.

**The credential is the customer's own token, and no new one exists.**

The route this entry assumed a product would call is the *platform* API's
`GET /organizations/{id}/products/{code}/entitlements`, which takes an
organization id as a parameter and is authorised by the estate-wide `registrar`
service account. A product must not hold that at runtime — it authorises writes
to every other product's registry entry, which is the argument that keeps
deploy-time registration off by default (F2b). The two ways out this entry
listed were a customer-facing route, or a per-product service account that would
close with F3.

The first already existed. `GET /api/portal/v1/products/{product_code}/entitlements`
has been on the Control Plane's **portal** surface — its customer API — and it
takes no organization id at all: the organization is resolved from the caller's
token, so the call can only ever reach the plan of the person making it. That is
a stronger property than a scoped machine credential would have had, because
there is no identity anywhere that can read a customer other than the one signed
in, and nothing to rotate or leak.

**What was actually missing was an audience.** A resource server verifies `aud`
against its own project and never widens it, so a product's token is refused by
the platform — correctly. ZITADEL's reserved scope
`urn:zitadel:iam:org:project:id:<project>:aud` is the supported way to say at
sign-in that the token is meant for a named second project too, and
`api/auth/start` now asks for it when `KORAS_CONTROL_PLANE_PROJECT_ID` is set. A
project id is an identifier, not a credential: it grants nothing on its own, and
the token still carries only that one caller's identity and roles.

So the answer was neither of the two this entry proposed, and it needed no
change to the Control Plane. **Filing something as another repository's decision
is what kept it closed for a day** — the entry was re-read only because the work
above it finished, and the route it was waiting for was already shipped.

**One defect came out of wiring it.** `parseEntitlements` was written against an
imagined response and read each row's `feature` field. The wire field is `code`.
Nothing would have failed: every row would have been skipped, every customer
would have resolved to a plan granting nothing, and the sidebar would have
looked exactly like a customer who had bought nothing. A parser written before
its producer exists is a parser nobody has compared to anything.

It has six tests now, and it moved to `packages/branding` to get them —
`apps/web` has no test runner, which is why the parser that decides what a
customer may open had none. Both the field name and the enabled-means-`true`
rule are mutation-checked: restoring either earlier reading fails four tests.

**The failure direction is unchanged.** An unresolved entitlement set counts as
*not entitled*, so a plan-gated module is hidden or shown locked and the rest of
the product is untouched. The opposite convention would make an unreachable
Control Plane the way to obtain a paid feature. `404` is treated as unresolved
rather than as an empty plan, because the portal answers it both for a customer
with no subscription and for a product code the platform has never heard of —
the second is a misconfigured deployment, and reporting it as "your plan grants
nothing" is how it would go unfixed. The log line says which is suspected; the
customer sees one message for both.

### F18 — no test in this repository opens a browser — opened 2026-08-31, closed 2026-09-01

- [x] Decide whether a browser harness belongs in the starter or in a product

**It belongs in the generated project, and the factory runs the generated copy.**

A browser test needs a running application. The starter has none — it is a
factory, and a harness kept here would have to generate a project first to have
anything to open. That cost is already paid: `generator-integration.yml`
generates both profiles every run and builds them. So the suite is authored in
`profiles/product/template/e2e/`, ships to every product, and the factory runs
it against a project generated moments earlier. One harness, authored once,
exercised in the factory and available to every product that ships.

The alternative — a starter-side harness driving a scratch project — puts the
test furthest from the code it tests and gives a real product nothing.

`playwright.config.ts` builds and starts `apps/web` itself, at 375 and 1440,
because below `lg` the navigation is a drawer and above it a sidebar; testing
one would leave half the navigation unexercised. No API runs: `NEXT_PUBLIC_API_URL`
is unset, the tenant read fails closed, and the shell falls back to the
product's own branding — a supported state, and the one a new customer is in. A
suite needing a database to check a focus trap is a suite nobody runs.

Nothing is bypassed. `e2e/support/session.ts` signs its cookie with the
application's own `mintSession` rather than a hand-built copy, and the
middleware verifies it on every request. The Control Plane's suite is the reason
that matters: its helper built the old ID-token cookie by hand, the cookie
changed shape, and every test failed — which was the suite working, and would
have been silence had the helper been the thing that changed.

**Eleven tests pass and five are viewport-skipped.** They cover the focus trap,
Escape restoring focus to the toggle, the drawer closing on navigation, the
collapsed sidebar keeping every link's accessible name, the preference surviving
a navigation, the skip link pointing at a target that exists, and an anonymous
caller reaching sign-in rather than the shell.

**It found something on its first run.** The shell renders the navigation twice
— sidebar and drawer, the drawer staying in the DOM while closed so its toggle's
`aria-controls` names a real element. Two nodes carry `aria-current="page"` at
every viewport, and at most one is reachable; at 375 none is, until the drawer
is opened. `PRODUCT_APP_SHELL.md` asserted the single-`aria-current` rule and
the server-side probe confirmed it by counting DOM nodes. Both were describing
the markup. Only a browser reads the accessibility tree.

**The e2e directory is typechecked**, by `tsc -p tsconfig.e2e.json` inside the
`e2e` script, and that is not incidental. Nothing else in a generated project
compiles that directory: it belongs to no workspace package, so `turbo run
typecheck` never sees it. Which is exactly how the Control Plane's half of this
rotted — see SYNC_BACKLOG B6.

What was already true without a browser, on 2026-08-31, remains the more
important half: the built application was probed with real signed session
cookies, one per organisation role, and the sidebar, the 403s and the 404 were
all asserted server-side. That covers the security claim. This covers the
interaction, which is the part that was only ever claimed.

### F20 — a product speaks one language — opened 2026-09-05, phase 1 closed the same day

- [x] A dependency-free `packages/i18n`: typed catalogues, negotiation, a translator
- [x] Every string in `apps/web`, `apps/marketing` and `packages/ui` read from it
- [x] English, German and Spanish complete, all three offered by the default configuration
- [x] `productConfig.i18n` and `productConfig.translations`; the homepage copy in German and Spanish
- [x] A cookie-backed switcher, in the footer of every public page, on the sign-in frame, and in Settings beside the appearance control
- [x] `lang` and `dir` on the document from the resolved locale
- [x] Persist the choice per member, and a tenant default (phase 2) - 2026-09-15
- [x] `apps/admin` - 2026-09-15
- [x] Email templates and API error text - 2026-09-15
- [x] A locale in the marketing site's URL, so it can be a cached document again
      - 2026-09-15

Every generated product was English, three times over: `lang="en"` in each
layout, the homepage copy in `productConfig.marketing` with no locale
dimension, and about a hundred and fifty lines of interface prose typed into
pages and components. Nothing in the Control Plane knows what a language is, so
this was the factory's alone to do.

**What was built, and the shape of it.** `packages/i18n` is a leaf with no
workspace dependency: an English catalogue that is the source of truth, a
German one typed as `Record<keyof typeof en, string>` so a missing key is a
compile error, and `createTranslator(locale)`, which is a plain function and
therefore works in a server component, a client component and a route handler
alike. The locale itself crosses the server/client boundary as a two-letter
prop — no provider, no context — which is the same "every prop is plain data"
rule the shell already lives by. `productConfig` gained `i18n` (what the product
offers, as distinct from what the package can speak) and `translations` (a
partial per-locale override of the product's own copy, merged field by field
by `marketingFor`, `productFor` and `navigationFor`). The default configuration
offers both languages so the switcher, the negotiation and the German catalogue
are exercised in every generated product; a product that wants English only
removes `'de'` from one list.

**Resolution is cookie, then `Accept-Language`, then default — never the URL.**
A locale in a query string is a locale somebody can put in a link. The cookie
is set by `POST /api/locale`, a plain form target so the switcher works before
any script attaches, and both applications serve one because the marketing
site is another origin. The value is validated against the offered list before
it reaches `lang` or a catalogue lookup; the return path is same-origin only.
`/api/locale` joins `PUBLIC_PATHS` in the middleware, and the public-routes test
learned that the exemption must exist exactly where the route does.

**What this cost, deliberately.** The marketing homepage was a cached static
document and is now rendered per request, because the language comes from a
cookie and a header. The comment in `apps/marketing/src/app/page.tsx` says so.
The repair is the last box above — `/de/` in the URL — and it is a different
design (routing, `hreflang`, a redirect from the bare path) rather than a small
edit, which is why it is a follow-up and not part of this.

**What is out, and why each.** Persisting the choice per member means the
API's first write route and a new RLS policy scoped to `current_user_id()`;
that deserves its own review and was agreed as a second pull request. The
admin application is staff-facing and does not depend on `packages/branding`,
so it has no declared locale list to negotiate against; it keeps `lang="en"`
until it is given one. Email templates in `packages/email` and the API's error
`detail` strings are English; the frontend maps API status codes to its own
messages, so nothing an API returns is shown to a person verbatim, but a
welcome email arrives in English whatever the visitor chose. The Control Plane
portal has no tenant default language for a product to read — that is a
platform change and is recorded there when it is wanted.

**The structural tests are the ones worth knowing about.** `product-i18n.test.ts`
asserts that no layout hardcodes `lang="en"`, that every page under `apps/web`
resolves the locale, that every catalogue key is used by some template and
every used key is declared, that no JSX carries a sentence of English prose,
and that `packages/i18n` imports nothing from the workspace. The last of those
is the dependency direction — `i18n` is a leaf, `branding` reads it for the
type, `ui` reads both — and a reversed edge would make the catalogue depend on
the copy it translates.

**Phase 2, 2026-09-15.** All four boxes, and each one was a different kind of
work.

**A choice that follows the person, not the device.** `member_preferences`
(migration 00017) holds one row per person per tenant, and `tenant_settings`
gains a default for everyone who has not chosen. A table of its own rather than
a column on `tenant_members`, for two reasons worth keeping: a member who signed
in through their organisation's identity provider has no `tenant_members` row,
so a preference stored there would exist for one person per tenant; and that
table carries `role`, so a policy letting a member write their own row would be
a policy letting them write their own role unless something else stopped it. A
table holding only preferences has nothing a policy has to protect.

This is **the first policy keyed to the caller rather than the tenant**.
`current_user_id()` had existed since migration 00001 and nothing read it: every
policy scoped rows to a tenant and the API set `app.tenant_id` alone. A request
now declares who is asking as well as which tenant, and the policy checks both.
On the user alone, a member of two tenants of this product would read their
preference from the wrong one; on the tenant alone, a member would read a
colleague's. `160_member_preferences_isolation.sql` is those two sentences as
three tests, and it fails closed with no subject.

Resolution for a signed-in member is now the stored choice, then the cookie,
then the tenant default, then `Accept-Language`, then the product's default, and
still never the URL inside the application.

**`apps/admin` speaks the three languages**, resolving cookie then
`Accept-Language` then default. Deliberately *not* the signed-in order: the
admin application is staff-facing, renders no tenant's branding, and asking the
product's API for a two-letter code would be the first thing it ever asked it
for.

**Mail and error text.** The mail catalogues are Python, typed so a missing key
fails mypy, and the locale travels with the send. The API's `detail` strings are
replaced by an `ApiErrorCode` on every route a person can reach from the shell,
which the web tier maps to its own catalogue, so nothing English reaches a
person even where the API is the thing that refused.

**The marketing homepage is a static document again**, under a `[locale]`
segment with `generateStaticParams`, `hreflang` alternates and a canonical. The
middleware stays dynamic and does the redirecting; the pages do not. That is
what the box asked for on 2026-09-05, when phase 1 made the homepage render per
request and said so in a comment at the path it then lived at.

**Two defects the verification found, neither visible in the diff.** The
marketing middleware stamped the locale cookie on *every* request it redirected,
and Next prefetches the header and footer links, so a prefetch issued moments
earlier under the previous language overwrote the language the visitor had just
chosen: choosing Spanish and then English left the cookie on Spanish. A guard on
`Sec-Fetch-Dest` fixes it, and a guard on Next's own router headers does *not*,
because Next strips those before middleware runs. And the F19 browser spec used
Playwright's `request` fixture, which keeps its own cookie jar: both of its
tests were strangers after signing in, followed the redirect to `/login`, and
read 200 where they asserted 404. A spec that asserted nothing, while passing.

**Verified** by generating a product with the full capability row and running
the chain CI runs: build, lint, typecheck and test across 34 tasks, 453 tests
passed in pytest, mypy over 111 source files, the row-level security suite
including the new isolation file and its mutation check, and Playwright at 375
and 1440 with 101 passed.

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

### F13 — nothing bills anyone, and that is not an oversight — decided 2026-09-01

- [x] Decide whether self-serve ships trial-only first — **yes, and it already
      does; what the decision actually turned on is somewhere else**

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

**Decided 2026-09-01: yes, trial-only. It is already what the code does, and
that is not the useful half of this entry.**

`koras-control-plane/services/worker/koras_worker/provisioning/repository.py` creates every
self-serve subscription as `status='trialing'` with
`trial_ends_at = now() + 14 days`, and reasons about it in place: *"a
subscription with no `trial_ends_at` cannot be reported on, chased, or expired,
so 'trialing' would mean the same thing forever."* So the recommendation this
entry made was already shipped, and confirming it is a paragraph.

**What checking it found is that the trial never ends, twice over.**

1. **Nothing expires it.** `subscription_renewal_check` runs nightly in the
   scheduler and returns `None`, deliberately, with the comment *"Implemented in
   Phase 19 with the rest of billing."* No subscription has ever changed status
   because a date passed.

2. **Status would not matter if it did.** `_RESOLVE`, the entitlement resolver
   in `koras-control-plane/services/api/koras_api/repositories/entitlements.py`,
   filters on
   `s.organization_id` and `p.code` and nothing else. It does not read
   `s.status`, `s.trial_ends_at` or `s.cancelled_at`. So `cancelled`,
   `suspended`, `past_due` and a `trialing` subscription three months past its
   end date all resolve **the same full entitlement set**.

The second is the one that matters. Cancelling a customer does not remove their
access; expiring a trial would not either. `subscriptions.status` is the field
this entry already names as *"the thing a webhook drives"* — and it drives
nothing today, so a webhook wired to it would move a value nothing reads.

**Blast radius today is zero, and that is precisely why it is worth writing
down.** No module in the shipped navigation registry declares
`requiredEntitlements`, so nothing is gated on a plan and nothing is therefore
wrongly ungated. F17 records the same thing from the other side: the moment a
product writes `requiredEntitlements` on a module, the gate goes live — and as
of 2026-09-01 a product actually reads entitlements, so the inert half is the
Control Plane's, not the product's.

**So the decision has a prerequisite, and it is not payment.** Before a card is
taken, `subscriptions.status` has to mean something. That is a `where` clause
and a scheduler job, it is worth strictly less than a day, and it is the seam
every later billing webhook lands on. Building dunning, proration or invoices
against a resolver that ignores status would be designing reconciliation against
a flow nobody has executed — the mistake this entry already refuses.

**The grant policy is the one genuinely commercial choice in it.** Recommended:

| Status | Grants | Why |
|---|---|---|
| `trialing`, `trial_ends_at` in the future | yes | the trial is the product |
| `trialing`, `trial_ends_at` passed | **no** | this is what makes a trial a trial |
| `active` | yes | |
| `past_due` | yes, for a stated grace window | revoking on a failed card loses a customer to an expired card; dunning belongs before revocation, and a grace window is a number somebody chooses rather than a default |
| `suspended` | no | |
| `cancelled` | no | cancelling that leaves access is not a cancellation |

Only the `past_due` row is a business decision; the rest follow from what the
words mean.

**Built in `koras-control-plane` the same day**, as R-93 —
[PR #2](https://github.com/KORAS-Technologies/koras-control-plane/pull/2).
Seven days of grace, measured from `current_period_end`. Both halves are
mutation-checked and its 870 tests pass. The two mechanisms are deliberate and
only one is authorisation: the resolver denies by date, so access stops on time
whether or not the nightly sweep ran, and the sweep exists to make the record
reportable rather than to enforce anything.

So F13's prerequisite is met and the payment work has a field that means
something to land on.

### F21 — somebody can now be billed, and nothing yet asks them to be — opened 2026-09-05, phases 1 and 2 closed the same day

- [x] Phase 1 — the provider adapter, a Paddle implementation, the signed webhook, `billing_events`, and status driven from outside (`koras-control-plane` 9cfee99)
- [x] Phase 2 — price references and seat bounds on plans, in the API, the public catalogue, the client and the console form
- [x] Phase 1's other half: recorded sandbox events replacing the authored fixtures — recorded 2026-09-15 from the test account's events API, see the note below. The database half was done on 2026-09-05 — the suites ran green with 00028 and 00029 applied, locally and in dev
- [x] Phase 3 — interval and seats on the signup form, Paddle.js on the verify page, provisioning started by `subscription.created`, the abandoned-checkout reminder (built 2026-09-05, both repositories)
- [x] Phase 3's browser run: a sandbox signup with a test card, from a product deployed with the client-side token, ending signed in — done six times by hand between 2026-09-10 and 2026-09-13, and once more on 2026-09-15 watched from the signup form through the checkout to the owner's password. The Playwright journey that records it ships at `e2e/live/signup-card.spec.ts`; running it unattended needs a person at the pay button, see below
- [x] Phase 4 — the portal's billing section, plan and seat changes, the trial-ended and past-due states; the first module with `requiredEntitlements` had already shipped with the shell (built 2026-09-05, both repositories)
- [x] Phase 5's code — the `billing.subscription` check in the estate sweep, repaired toward the provider (built 2026-09-06)
- [x] **The provider switched from Paddle to Stripe Managed Payments on 2026-09-09**, before any customer existed to migrate. The adapter, the webhook, the checkout and the pricing page were rewritten in both repositories; the Paddle adapter was deleted rather than kept behind a flag. See the note below
- [~] Phase 5's rest — the Stripe account with Managed Payments enabled, the test-mode catalogue with eligible tax codes, keys and webhook endpoint in Doppler: **all existed in test mode by 2026-09-13**, recorded 2026-09-15 in `koras-control-plane/docs/BILLING.md`. Still ahead: live-mode activation, the live key, the customer portal check, the first real cycle — `koras-control-plane/docs/runbooks/stripe-go-live.md` steps 1, 3, 5 and 7
- [x] The two paths the stand-in provider cannot exercise: the hosted checkout completed in a browser against test mode (six times, above), and a period-end change observed as a subscription schedule on a real subscription — run 2026-09-15 through the adapter against a test-mode subscription made for it: two phases, three seats to the period's end and two from that second, `end_behavior` `release`; released and cancelled afterwards

The design is `BILLING_DESIGN.md`, decided 2026-09-05: card at signup, charge
at trial end, a Merchant of Record behind an adapter, and the Control Plane
the only writer of `subscriptions.status`. What the Control Plane holds of it
is `koras-control-plane/docs/BILLING.md`.

**Why the provider changed.** Paddle was chosen for one reason: Merchant of
Record, so that KORAS files no sales tax or VAT anywhere. On 2026-09-09 the
comparison was re-run and Stripe's Managed Payments turned out to offer the
same thing -- Stripe as the seller, tax filed in more than eighty countries,
Germany an eligible location, SaaS an eligible category -- on the provider
whose account opens in hours rather than weeks. No subscription existed, so
there was nothing to migrate and the switch cost the adapter and the
checkout: Stripe Checkout is a hosted page rather than an overlay, so the
product now loads no provider script and holds no provider token at all;
Stripe has no browser-side price preview, so the adapter gained a sixth
operation, `prices`, and the public catalogue carries the amounts; and Stripe
has no "from next period" flag, so a scheduled seat decrease is a
subscription schedule. Each is recorded where it applies in the design.

**What F13 left and this picked up.** F13 made status mean something. This
gives status a writer: a webhook that verifies Paddle's signature over the raw
body, stores every event by Paddle's id before acting on it, and refuses to
let an older event move a row backwards. The webhook runs as the commercial
authority rather than the machine, because the RLS suite asserts a machine out
of `subscriptions` — and that one fact moved the customer reference from a
column on `organizations` into its own table, since the billing authority
cannot write an organization row and should not gain the ability for one
column. Both are recorded in the design where they apply.

**Why the top of the list.** Every earlier entry in this section was about
getting a customer *in*. This is the first about a customer paying, and Phase
3 is the first change that shows a price on a page a stranger can reach. It
belongs above F7 because F7's remaining box is a verification of something
already sold to nobody, and this is the thing that will be.

**What is deliberately not in it.** A free tier or a "continue without a
card" path. The design assumes neither, and adding one later is cheaper than
removing one; the decision is the user's and is asked for before Phase 3
begins. Usage-based pricing, coupons and invoiced contracts are price shapes
the provider supports and none changes the adapter.

**Phase 3, the same evening.** Both halves. The Control Plane's verify
endpoint answers `awaiting_payment` with checkout details where a provider key
and a price exist, the webhook's `subscription.created` writes the subscription
row with the provider's ids and starts the run through `koras_api.onboarding`,
the status endpoint answers by registration id, and an hourly sweep reminds a
closed checkout once with a reissued token. The product template's form gained
the interval and seat controls, its verify page opens Paddle.js from the
provider's CDN with the public token, its CSP admits the provider's hosts
exactly when that token is set, and its settings contract declares the two
`NEXT_PUBLIC_PADDLE_*` names. Tested end to end through the API with a
simulated provider, and the template is type-checked as a generated project;
the browser run against the real sandbox is the open box above, because it
needs a product deployed with the token.

**Phase 4, the same evening.** The portal's Billing page replaced its "not
yet": plan, interval, seats and the next date per product, one form to change
any of them, and a button into Paddle's own portal for the card and the
invoices. The API applies the design's rules — increases and yearly now,
decreases and monthly at period end, a decrease below the people holding a
seat refused with the number to remove — and the row follows the provider's
answer, never the request. The product's entitlement read carries the
subscription's status and dates, and the shell says what they mean without
deciding anything from them. The "first gated module" turned out to be
already there: the shell shipped `reports` locked and `insights` hidden on
2026-09-01, so what this phase added is the sentence that explains why.

**The pricing section, 2026-09-07.** The flow the design opens with started
at a page nobody had built. `/#pricing` now sits on both public homepages:
plans from the platform's public catalogue, read on the server; prices from
Paddle's price preview, rendered in the browser with the public token, so no
amount lives in this repository; each card into the signup form with the plan
and interval preselected. `parsePublicPlans` moved into `packages/branding`
beside `parseEntitlements`, and the signup action reads through the same
loader as the section, so the two never disagree about what is on sale.

**Phase 5's code, 2026-09-06.** The provider adapter moved into
`python-packages/koras-billing` so the worker could hold one, and the
reconciliation engine gained `billing.subscription`: every held subscription
read back from Paddle every fifteen minutes and compared on the four things
that decide access and money, repaired toward the provider because it holds
the money. Severity follows cost — a paying customer the row calls closed is
CRITICAL. What is left of Phase 5 is the live account and the walk from
sandbox to live, which is a runbook rather than code.

**Left undone on 2026-09-05, and why.** The fixtures under
`koras-control-plane/tests/fixtures/paddle/` were authored from Paddle's
documented shape, because recording needs a destination Paddle can reach and
the dev API received its secrets only that evening. The database-backed tests
did not run in the session that wrote them, because Docker was not up. Neither
is a reason to wait on Phase 3, but both are cheaper than Phase 3 and turn the
code that shipped into evidence — which is why the first open box is the
half-finished Phase 1 rather than the next phase.

**Read back from Stripe on 2026-09-15, and what it changed.** The four boxes
above were worked in the order the table recommends, and the first thing the
work found was that three of them were already done and nobody had written it
down: the test account, the catalogue with `txcd_10103001` on it, the price
ids on the `dev` plans, the webhook endpoint at the dev API, and six hosted
checkouts completed in a browser from real signups on `koras-e2e-shop` --
four of which had gone `trialing` to `active` at trial end, because `dev`
runs a one-day trial. `koras-control-plane/docs/BILLING.md` said none of it
existed. That is R-042 landing on a document about money, and the reason the
correction there opens by saying so.

What the sitting then did, rather than found: the fixtures under
`koras-control-plane/tests/fixtures/stripe/` are Stripe's own deliveries
now -- three read from the account's events, two (`past_due`, `deleted`)
made for the purpose on a test clock with metadata nothing holds -- and the
sixty-six tests over them assert the recorded ids and times rather than the
authored ones. The period-end schedule was exercised through the adapter
against a subscription created for it and cleaned up after. And the
product template gained `e2e/live/signup-card.spec.ts`, the journey from the
emailed link through Stripe's checkout to the dashboard, skipped unless an
operator supplies the links a mailbox holds.

**Where it stopped, and who finished it.** The seventh signup,
`F21 Card Run`, was driven in a browser as far as Stripe's hosted page --
Sandbox, "sold through Link", $38 a month after a one-day trial for two
Starter seats -- and stopped at the pay button, by the policy that stops an
agent from completing a payment, test card or not. A person paid it the same
afternoon, and the rest ran on its own: the session reads `complete` and
`paid`, `customer.subscription.created` arrived at 14:28 UTC with the
registration id in its metadata, provisioning finished, the welcome mail went
out at 14:29, and the owner's password was set a minute after that.

So **Phase 3's browser run is done end to end**, by hand rather than by the
spec, on a product deployed with a real key against a real provider. What the
spec has still not done is drive it unattended: `e2e/live/signup-card.spec.ts`
exists, is skipped without the two emailed links, and has not been run to
completion -- and it never can be by an agent, because the pay button is where
an agent is refused. That is a fact about who runs it rather than a gap in it.

**One small thing the run showed.** The signup form says "your 14-day
trial" and the checkout said "1 day free": the number is `BILLING_TRIAL_DAYS`
on the platform, per environment, and the product's copy had it typed in.
The copy now says "your trial", and the length is Stripe's page's to state,
since it is the page that reads it from the session.

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
- [x] Confirm the Control Plane's stored references change as a result — the
      registration answers what it stored since 2026-09-15, and the generator
      compares; see the closing note at the end of this entry

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

**Why the last box was still open until 2026-09-15.** Confirming the *stored*
references means
reading the registry, and `GET /api/platform/v1/products` answers `403 This
endpoint is restricted to platform staff` to the registrar. That is correct —
the registrar is a machine identity that registers and cannot read — so this
needs the console or a `STAFF_TOKEN`, neither of which a session can obtain.

**And it cannot be closed by the caller even in principle**, which was not known
when this was written. `POST /api/platform/v1/products` answers
`ProductResponse`, whose `environments` is `list[Environment]` — environment
names, not stored references. A successful registration therefore reports that
the payload was *accepted* and says nothing about what the registry holds. A
payload stored wrongly and one stored correctly produce identical output, which
is the same indistinguishability F7's own findings keep turning up.

The cheaper fix is the Control Plane's: echo the stored
`infrastructure_references` in the response and every registration verifies
itself. Recorded in F2c with the alternative.

**A second real send, 2026-09-01.** `--register-only` was run against the live
dev Control Plane for `koras-e2e-shop` and accepted — correlation id
`1bece788-0bfc-411f-a8bb-43a33dbb7da2`. That is the operator refresh path
executed end to end for the first time: credential resolved, Terraform outputs
read, payload accepted, no infrastructure touched. It closes F2c. It does not
close this box, for the reason above.

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
first box was blocked twice over — once by F2b's deliberate default, once by
something no code in this repository can reach. See R-030, reopened for
products.

**Only the first blocker survives.** Billing was resolved that evening — first
successful CI at 19:15, first successful deploy at 20:44 — and R-030 said
otherwise until 2026-09-01. The register job is off by F2b's deliberate default,
which is a decision somebody can take, not an impossibility.

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

**Closed 2026-09-15, by making every registration self-verifying.** The last
box could not be closed by the caller because `POST /api/platform/v1/products`
answered environment *names*. F2c named two ways out and this takes the
smaller: the Control Plane now reads the registry back inside the
registration's own transaction and answers `stored_environments` -- what the
tables hold, in the request's shape, not an echo of the request -- and
`runRegistration` compares it with what it sent, key for key. A match prints
*Registry confirmed*; a difference fails the step, not retryable, naming the
differing paths and never a value; a response without the field is an older
Control Plane and is reported as *accepted, not confirmed*, so R-001 is
untouched. Asserted by `registration-verify.test.ts` (match, mismatch, older
shape) here and `test_product_registration.py` there, the latter against a
real Postgres.

**What the read-back found on its first day.** `supabase_api_url` and
`zitadel_instance` were accepted by the request schema and stored by nothing
-- registration answered 201 and dropped both, and the generator sends
`zitadel_instance` every time. Invisible while nothing compared the two
sides; a mismatch on every registration the moment something did. Both are
stored now.

**Still open on 2026-09-15, elsewhere.** The deploy-time script does not
compare the echo (`REGISTRATION_LIFECYCLE.md`, not covered), and it stays off
by F2b's default. The first box stands unsatisfiable as written, as recorded above.
Nothing in this closure has been run against the live dev Control Plane; the
next `--register-only` for `koras-e2e-shop` will be the first confirmed
registration in the estate.

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


### F22 — Files: what the first storage module leaves out

Built 2026-09-08: `docs/PRODUCT_APP_SHELL.md` §21a. Left undone, each for a
reason rather than for lack of time:

- [ ] **Multipart uploads.** One object, one signed PUT, five gigabytes at
      most. Larger files need the multipart protocol, which needs the API to
      hold an upload id across requests. Not until a product needs it.
- [ ] **A sweep for orphans.** A row without an object is a `pending` upload
      that never confirmed; an object without a row is a confirmation that
      failed after the PUT. Both are findable and neither is found yet.
- [ ] **`customer-owned` and `azure-blob`.** The policy can name both; the
      product refuses both with 503. The first needs the customer's own
      credential, which nothing in the estate holds; the second is not
      S3-compatible.
- [ ] **A real upload in CI.** Generator Integration has Postgres and no
      bucket. The browser spec proves the page's states without one; the
      upload itself is proven against MinIO locally and against dev by hand.
- [ ] **A foreign bucket's origin in the browser's policy.** `connect-src`
      names the product's own storage origin, from `STORAGE_ENDPOINT`. A
      customer whose policy names a bucket on another provider is served by
      the API and refused by the browser, because the page's policy is built
      before the tenant is known. Either the policy's endpoint joins the list
      per request, or uploads to foreign buckets go through a signed proxy.
- [ ] **Quota by period.** The limit is a ceiling in gigabytes on a boolean
      entitlement's plan grant, not a `quota` kind, because the platform's
      quota needs a period and storage has none.

### F24 — the AI foundation: what the first shared AI layer leaves out

Built 2026-09-13: `docs/AI_ARCHITECTURE.md`. Every line below is a decision
rather than an omission, and each names the seam it plugs into.

- [x] **A real model call.** Held on dev on 2026-09-14, from `koras-e2e-shop`
      through its deployed gateway to OpenAI, and it found two defects the
      scripted provider could not: OpenAI refuses a function named
      `files.list`, so tool ids now cross the gateway with the dot as a
      hyphen; and the usage row was refused by row-level security, because
      the store committed mid-request and the tenant setting is
      transaction-local, so the store re-binds the tenant after every commit.
      The three entitlements are in the Control Plane's catalogue, granted to
      Pro and above, and a routing template per tier is written at
      provisioning; an organization that predates it gets its rows from one
      button on the admin's AI page.
- [x] **Tracing spans on the gateway call.** Built 2026-09-14: a client
      span per call with provider, model, alias and tokens, trace context
      forwarded to the gateway, and the exporter chosen by
      `OTEL_EXPORTER_OTLP_PROTOCOL` -- which fixed the dev collector, whose
      every export had failed with "missing selected ALPN property" because
      the gRPC exporter was talking to Grafana Cloud's HTTP gateway.
- [x] **Streaming.** Built 2026-09-14: the runtime tells a turn as events
      and `send` is the same stream kept to the end; the API writes them as
      server-sent events on a session of its own; the web tier's
      `/api/assistant/stream` route handler decides who is calling the way
      the server actions do and pipes the bytes to the panel, which shows
      the answer as it arrives. A refusal mid-stream is an `error` event
      with the status the whole-answer route would have given.
- [x] **Approval notification.** Built 2026-09-14: the owner and every
      active member whose role carries `ai.approve` are told, after the
      response, which tool waits and who proposed it -- never the input. A
      deployed product has no mail host, so there the notice is recorded and
      logged; see the mail provider entry below.
- [x] **A mail provider for products.** Done 2026-09-14 the way the Control
      Plane did it: SMTP_HOST, SMTP_PORT, SMTP_SECURE, SMTP_FROM, SMTP_USERNAME
      and SMTP_PASSWORD are optional settings a product's Doppler config may
      hold for any provider that speaks SMTP, and an unset host still records
      and logs the notice rather than failing. Nothing is sent until an
      estate's config names a provider.
- [x] **A vector store.** Built 2026-09-14 on pgvector in the product's own
      database: `ai_knowledge_chunks` under the tenant policies, text uploads
      indexed after completion and removed with the file, `knowledge.search`
      on the reference agent, the 100 isolation test. PDFs with a text layer
      and workbooks are indexed too since the same day (pypdf, openpyxl),
      and images and scanned PDFs since the evening: pages rendered with
      pypdfium2 and transcribed by the vision alias, metered per page
      under `knowledge.ocr`, twenty pages a file at most. The CI Postgres
      is now the pgvector image.
- [x] **A durable audit table.** Built 2026-09-14: `ai_audit_events`,
      insert-only per tenant, flushed by every AI route after answer or
      refusal, read at `/api/v1/ai/audit` by anyone with `ai.approve` and shown
      on the assistant page, swept after `AI_AUDIT_RETENTION_DAYS`.
- [x] **Retention.** Built 2026-09-14: the worker's nightly sweep, on the
      provisioning context, removes conversations untouched for
      `AI_RETENTION_DAYS` with their messages and actions and keeps the usage
      rows. It needed a second migration after all -- a delete policy for that
      context -- and the 080 isolation test bounds it.
- [x] **Usage reporting to the platform.** Built 2026-09-14 the other way
      round: the platform pulls. The private platform router answers every
      tenant's usage per day, aggregated, on the provisioning session, which
      migration 00007 admits for reading and the 070 isolation test bounds to
      it; the Control Plane collects hourly through the identity it already
      holds toward every product, keeps daily rows per organization, and shows
      staff the calls, tokens and list-price estimate, and the customer the
      calls and tokens. Cost is the platform's price list in code, carried in
      each routing policy as `prices` and stamped on each usage row as
      `estimated_cost_micros`. The "last collected" component landed
      2026-09-15 as `collectors` on platform health: the worker records
      every attempt per collector and product in `collection_runs`
      (Control Plane migration 00043), success or failure, so a product
      with nothing to report still reads as collected and one that has
      stopped answering reads as stale after two sweeps, with the last
      error beside it. The console's health page lists it per product.
- [x] **Pay as you go beyond the allowance.** Built 2026-09-15, decided
      against packs (a dispute per pack) and against daily billing (thirty
      invoices a month): an owner or administrator agrees in the portal to
      a rate card and sets a monthly charge limit; the product meters each
      call past the allowance at cost times the staff rate and stops at the
      limit; the platform sums, shows and warns. `AI_ARCHITECTURE.md` has
      the shape. Reporting the month's charges to Stripe was decided
      against on 2026-09-15, on the documentation: Managed Payments lists
      attaching invoice items to one of its subscriptions, and a one-off
      invoice outside the billing period, as unsupported
      (https://docs.stripe.com/payments/managed-payments), and a metered
      line is neither named as supported nor creatable after the Checkout
      that makes the subscription. The charges stay a summed, shown, capped
      number nobody is billed for; `koras-control-plane/docs/BILLING.md`
      records the decision and the three alternatives, the first of which
      is to sell larger allowances as plan tiers.
- [x] **The gateway's unauthenticated answer.** Fixed 2026-09-14 with a
      middleware in front of the proxy that answers 401 itself. It was a 500, because LiteLLM's
      authentication error handler imports Prisma to classify the error and
      the image has none. Harmless to the product, which always sends the
      key, and misleading to anyone probing the gateway by hand.
      A wrong key got the same 500 until 2026-09-15; the guard now compares
      the bearer to `LITELLM_MASTER_KEY` in constant time where one is
      configured and answers 401, so the proxy's Prisma-importing error path
      is never reached for either case.
- [x] **A per-minute AI quota.** Built 2026-09-15 as a setting rather than
      a plan field, because it stops abuse rather than sells capacity:
      `AI_REQUESTS_PER_MINUTE`, thirty unless set, zero to switch off, a
      fixed window per organization on the two routes that call a model,
      refused with the 429 the monthly allowance uses (`limit_ai_turns` in
      `core/ai.py`).
- [x] **The local gateway.** Fixed 2026-09-15: `dev-service.mjs` starts
      the gateway through its own entry point, `python -m koras_ai_gateway.main`,
      the way the container does, with `--host` and `--port` on the command
      line; the module's `main()` loads the configuration before serving.
      No `--reload` for it: the gateway is configuration, and a change to it
      is a restart.

### F25 — the reporting framework: what the first shared reporting layer leaves out

Built 2026-09-14: `docs/REPORTING_ARCHITECTURE.md`. Every line below is a
decision rather than an omission, and each names the seam it plugs into.

- [x] **Scheduled delivery.** Built 2026-09-14: `report_schedules`
      (migration 00014), `routers/reporting_schedules.py`, the hourly
      `deliver_scheduled_reports` in the worker, mail through `koras_email`
      with the file attached. The plan at delivery time was unresolved for
      the first hours: the worker rendered with `UNRESOLVED_PLAN`, so a
      schedule made on Business kept delivering after a move to Starter.
      Closed the same night in the direction the estate allows: the platform
      syncs each tenant's effective entitlements into `tenant_plans` hourly
      through the private contract, and the worker pauses a schedule the
      plan no longer covers. What that leaves is the hour: a downgrade is
      honoured at the next sync, not the next second.
- [x] **XLSX and PDF.** Built 2026-09-14: `to_xlsx` through `openpyxl`,
      `to_pdf` through `fpdf2`, one `render()` over the three. The PDF is a
      plain landscape table with the title and the range; a branded document
      with the tenant's mark is still a design question.
- [x] **Asynchronous export.** Built 2026-09-14, in the API rather than the
      worker: past `EXPORT_ROW_LIMIT`, or on request, the router answers 202
      and writes the file after the response into the tenant's bucket, the
      Exports list mints the download, and `REPORT_EXPORT_RETENTION_DAYS`
      retires old ones on the way to listing. In the API because the worker
      holds no storage credentials and the resolver already ran; a worker
      task is the shape to move to when an export outgrows a request's
      lifetime.
- [ ] **`reporting.api` enforcement.** Declared in the catalogue and
      granted to Enterprise; every call today carries a person's token and
      the product's own web tier is the only caller, so there is nothing to
      refuse yet. It becomes real with the first machine caller.
- [ ] **Pre-aggregation.** Every resolver runs an indexed query bounded by a
      date range of at most 366 days, which is right for one product and
      one tenant. A daily aggregate per metric and dimension -- the shape
      the platform's AI usage table already has for one metric -- is the
      answer when a table grows past what a range scan should read.
- [ ] **Report names in the customer's language.** A report's name and
      description come from its definition in English; the page's own
      strings are translated, the definitions are not. A `translations`
      field on `ReportDefinition` keyed by locale is the seam.
- [x] **Product activity on the platform.** Built 2026-09-14: the product
      answers `GET /internal/platform/v1/activity` with counts per tenant,
      day, action and outcome; the Control Plane's product-activity
      collector pulls hourly into its daily activity table (its migration
      00041, the AI usage table's twin) and
      Usage & Adoption reports actions, customers with activity, actions by
      product, and the busiest day's people per action. Sign-ins are still
      not among them: the product records no sign-in event yet, so there is
      nothing to count.
- [x] **A retention setting for the shop's domain.** Built 2026-09-14 in
      `koras-e2e-shop`: a shop retention setting in days, unset by default so
      orders are kept, a nightly sweep of orders on the provisioning context,
      the shop's migration 00015 for the one delete policy it needs, and a
      row-level security test proving a tenant cannot reach another's orders
      through it.

### F26 — storage and audit governance: what the first governance layer leaves out

Opened 2026-09-16, after the first independent security and privacy review of
the work. Both reviewers returned BLOCK; everything they found is fixed and in
`1b59f29`. These are the items that were decisions rather than defects.

- [ ] **Erasure by class.** ADR 0003 decision 14 settles the position: an
      Article 17 request removes a data subject's content and leaves every
      audit row about them, on 17(3)(b) and 17(3)(e). The more defensible
      answer is to split it — erase `activity`, which is convenience data with
      no obligation behind it, and refuse the three that carry one. It is not
      built because it is three things, not one: a route that erases, an audit
      row recording the erasure (which must survive the erasure it records),
      and a hold check, since a subject under hold is exactly the case the
      refusal exists for. Improvising any of the three is worse than the
      documented refusal.
- [ ] **A product-level retention policy.** The precedence in
      `docs/RETENTION_POLICY.md` names three levels and two exist: the platform
      floor in settings and the tenant override in `tenant_settings`. The
      product level — a product's own configuration sitting between them — has
      no home yet. Nothing is wrong without it; a product that wants a longer
      default sets the floor.
- [ ] **Reconciliation findings as a table.** The sweep records what it found
      as audit rows, so a console wanting a history rather than a latest has to
      read them back out of `audit_events`. That works and is indirect.
      `docs/features/storage-architecture/integration-contracts.md` says the
      same.
- [ ] **Storage tiers.** WARM, COLD and ARCHIVE stay metadata with no physical
      effect: no provider in this estate offers tiering and no bucket is
      provisioned for an archive. ADR 0003 decision 11. A `tier` column that
      nothing acts on would be the defect this work exists to close.
- [x] **The two capabilities are undeclared.** Declared 2026-09-16, both on by
      default, and what they gate is the surface rather than the record: only
      `00025_file_backups.sql` is a gated migration, because nothing outside
      the backup sweep reads `file_backups`. A product generated without either
      still records every event, still classifies and forgets it on a schedule,
      still refuses a deletion under hold, and still answers the platform's
      governance contract. What it loses is search, export, the holds routes,
      the Audit page and the three sweeps.

### F27 — the settings framework: what the first settings layer leaves out

Opened 2026-09-19, the day the eleven phases finished. Nothing here is a
defect; each is a decision taken deliberately, with the reason.

- [x] **Five settings that resolve and do nothing** — **three closed
      2026-09-19.** The shared table learned column resizing, column reordering
      and remembering an arrangement, so `grid.allowColumnResize`,
      `grid.allowColumnReorder` and `grid.rememberColumns` are honoured and
      offered again. It was built once for this and for IMPORT-GAP-006, which
      names the same component from the other side; neither feature should have
      built it alone.
- [ ] **Two settings that still resolve and do nothing.**
      `grid.rememberFilters` and `grid.rememberSort` stay `surfaced=False`, and
      the reason is now sharper than "the table does not honour them": the
      table has no filter and no sort, so they describe persistence of state it
      does not own. A surface above it does. The resolution is one of two
      things and not a third: the table grows sorting and filtering, or they
      leave the catalogue. Leaving them registered and invisible is how a
      catalogue stops describing the product.
- [ ] **No page in a generated product uses the shared table.** The grid
      integration is the feature's most visible claim and the template has no
      list long enough to page. The page that makes `grid.pageSize` observable
      is in `koras-e2e-shop`, and it is that repository's own work. Until a
      template page uses it, a freshly generated product ships a settings
      surface whose largest category changes nothing a customer would see.
- [ ] **The round trip has no automated proof.** `playwright.config.ts` starts
      the web application and nothing else, so the sixteen browser checks in
      `e2e/settings.spec.ts` cover routing, refusal and degraded rendering, and
      cannot cover a save. Stubbing an API would prove the stub. Closing this
      means a harness that runs the API and a database against a generated
      product, which is a piece of infrastructure rather than a test, and it
      would pay for more than this feature.
- [ ] **No manual pass, no independent review.**
      `docs/features/settings-framework/manual-test-plan.md` has fifteen cases
      and fifteen blank verdicts. Three new tables with row-level security, a
      check constraint that refuses secrets, and a platform write route that
      needed an ADR to justify its direction have had no eyes but the ones that
      wrote them. This is the same gap SAG-F2 carries, and for the same reason.
- [ ] **Bulk import and export of settings.** The brief does not ask for it and
      nothing needs it yet. It is recorded because it is the first thing anybody
      asks for once a second product exists and somebody wants its defaults to
      match the first's.
- [ ] **No way to move existing organisations onto a new default.** By design —
      the snapshot is the requirement, and "we changed the default and nothing
      happened" is the correct outcome. But there is no deliberate act either:
      if a platform default turns out to be wrong for everybody, the only route
      today is a hand-written update per tenant. What it needs is a decision
      about who may do it and what it records, not a script.

### F26 — the platform's member list carries no subject

Opened 2026-09-19, by CAT-01 Phase 2, which is the first work that needed the
two halves to join and found that they do not.

A notification has two destinations and this product knows its people
differently in each. The feed goes to a **subject** — a row in
`tenant_members`, somebody who can open the product. A mail goes to an
**address** — `tenants.owner_email`, plus whatever
`GET /api/portal/v1/members` holds. That answer carries an email and a role and
**not** the ZITADEL subject, so an address cannot be matched back to a member.

Three consequences, each paid rather than fixed as of 2026-09-19:

- [ ] **A person-level email preference cannot exist.** `notifications.emailEnabled`
      is `Scope.GLOBAL_ORG` for exactly this reason: a recipient the product
      can mail is one it cannot match to a member, so a per-person switch would
      be a control nothing could ever read. The rung is not offered rather than
      offered and ignored.
- [ ] **A mail cannot be written in the recipient's own language** unless they
      are also resolved as a member. A member's stored `general.language` is
      read for the feed; an address falls back to the organisation's.
- [ ] **The same person can be told twice** — once as a subject and once as an
      address — and `recipients.resolve` cannot tell that they are one person.
      Today the two audiences barely overlap, because members rarely have
      addresses the product holds, so this is latent rather than visible.

What closes it is one field in the Control Plane's portal contract: the member
list answering the subject beside the email. That is a change in
`koras-control-plane` and a version of
`contracts/product-platform.v1.json`, not a change here — which is why this is
an entry rather than a defect.

### F28 — data import: what Phase 1 leaves out

Opened 2026-09-19, the day Phase 1 shipped. The phase boundary is deliberate —
a run reaches `validated`, which is a terminal state that wrote nothing — so
most of what is missing is Phase 2 and lives in
`docs/platform/execution/CAT-02-data-import.md` rather than here. What is here
is the three Phase 1 items that were planned and not built, plus the two kinds
of proof nobody has.

- [ ] **`files.maxFilesPerUpload` is hidden rather than enforced.** The other
      two `files.*` settings are resolved at the upload ticket now; this one
      cannot be, because the presign route issues one ticket per call and has
      no notion of a batch. Hiding it is the honest position of the two
      available today — a control that changes nothing costs a person the time
      to find out — but it is a setting in the brief's catalogue that the
      product does not offer, which is the same shape as F27's five `grid.*`.
      Closing it means a batch ticket route, not a check.
- [ ] **No shared upload primitive.** IMPORT-GAP-007 asked for the Files page's
      ticket-and-progress flow to be extracted into `packages/ui` rather than
      written a second time. It was written a second time — about two dozen
      lines — because the import flow needs the same three steps in a different
      order and extracting a working page's uploader inside a feature branch is
      a refactor with no test that would catch its regressions. The third
      caller is what should pay for the extraction.
- [ ] **The preview does not go through the shared data table.** Its columns
      vary per file and are built at runtime, which is not something that table
      takes; it also paginates on the client, which is IMPORT-GAP-006 and is
      the same constraint F27 records from the settings side. The preview is a
      bounded head of 200 rows in a plain table. Both are fixed by the same
      piece of work — a table that takes a column set and a page callback — and
      neither feature should build it alone.
- [ ] **No manual pass.** Twenty-two cases, twenty-two blank verdicts. The e2e
      harness starts the web application alone, so the four browser checks
      cover routing, refusal and degraded rendering, and nothing that needs an
      API, a queue or a bucket. No file has been imported through a deployed
      product, and the dry run has never executed against a real Redis.
- [ ] **No independent review.** Of the parser especially. `koras_import.reading`
      is the only code in this estate that parses a file chosen by somebody
      outside the product, and the scan gate in front of it refuses `pending`,
      which means it is unreachable until a scanner exists — so as of
      2026-09-19 the gate is protecting code nobody has read.
- [ ] **`koras-e2e-shop` is not level with this.** It is the one repository in
      the estate with a domain that could declare real import targets, and
      declaring one is what would make the registry, the mapping and the
      permission observable rather than asserted. Nothing has been synced.
- [ ] **No audit action is registered for an import.** IMPORT-US-016 is a
      Phase 2 story and the run row already records who asked, but a product
      answering "who loaded these records" from the audit log cannot do so
      today. It is recorded here because the audit registry is the kind of
      thing added when the feature lands, not after.

### F23 — the sign-in page, on a host of ours — opened 2026-09-09, built 2026-09-11 as the product's own page

The one customer surface still drawn by ZITADEL is the sign-in page: ZITADEL
Cloud's hosted Login V2, with a language switcher and a theme toggle in its
footer that no ZITADEL setting removes. Every other surface on a customer's
first day is the product's since 2026-09-09 (Control Plane R-107: the owner
and every invited member set their password on the product's `/activate`).

**The plan** is written and checked against ZITADEL's source and docs:
`koras-control-plane/docs/LOGIN_UI_PLAN.md`. In one paragraph: a full fork of
`zitadel/zitadel` from a release tag, three source commits in `apps/login`
(remove both switchers, the font, the application name), the image on Fly as
`koras-login-<env>` at `login-<env>.korastechnologies.com`, a login-client
token of its own in Doppler, the instance's Login V2 flag pointed at it, dev
first for a week. About two days to dev, half a day for the rest.

**Why it is here and not done.** It is a fork to maintain -- a monthly merge
from upstream -- and a flag that redirects every login on the instance at
once, staff included. Neither belongs to a day that also shipped four fixes to
the signup path. And it is the *first half* of R-90 only: the page would be
ZITADEL's login app on our host, not a product page. The second half, a
branded sign-in calling ZITADEL's session API from the product, is the larger
piece and is not planned.

**Built differently, 2026-09-11.** The fork was not made. What ships is
the *second half* the paragraph above called larger: the product's `/login`
is the sign-in, posting the email address and password from its server to
new Control Plane routes that check them with ZITADEL's session API and
finalise the auth request; a TOTP code is a second step; a forgotten
password reuses the portal's reset job and the `/activate` page. ZITADEL is
told **per application** -- `login_version { login_v2 { base_uri } }` on the
product's OIDC app, derived in Terraform from the web domain -- so the
Console and every other application on the instance keep the hosted login,
and no instance-wide flag, break-glass token or week on dev is needed.
That, and having no fork to merge monthly, is why the smaller plan lost to
the larger one once the per-application setting was checked in the
provider. The design is `docs/PRODUCT_SIGN_IN.md`; the Control Plane's
`LOGIN_UI_PLAN.md` stays as the record of the road not taken.

- [x] The page, the actions, the code step, forgotten password, three
      languages, the browser suite (this repository).
- [x] The routes, the ZITADEL session client, the held attempts, the
      public-surface claims and the integration suite (`koras-control-plane`,
      `feat/product-sign-in`).
- [x] The per-application setting in the Terraform module, derived per
      environment in `project-bootstrap`.
- [x] `terraform apply` on `koras-e2e-shop` dev, then one sign-in in a
      browser: ZITADEL answering the authorize request with a redirect to
      `/login`, and the platform's callback URL landing on
      `/api/auth/callback`. Done late on 2026-09-11, after four fixes the
      stub could not have found (the Login V2 instance feature, the base URI
      being an origin, the `IAM_LOGIN_CLIENT` role, and the callback landing
      on the product's own origin): a real Chromium signed a customer in on
      the product's page and reached `/dashboard`. This box stood unticked
      for a day after that, which is R-042 landing on the file that lists
      what is undone.
- [ ] The same on test, stg and prod. **The Terraform half is already done on
      all four instances** — the per-application base URI is applied for the
      Control Plane's portal and for `koras-e2e-shop`, read live on
      2026-09-12. What is left per instance is three writes a person has to
      make, in this order: grant the `worker` service user
      `IAM_LOGIN_CLIENT`; set ZITADEL's own Management Console application to
      login version V2; and only **after** the environment is promoted, turn
      the instance's `loginV2.required` off. The order is the whole of it: with
      the feature off, ZITADEL sends every sign-in to the application's base
      URI, and the product's `/login` answers 404 on an environment that has
      not been promoted. All three writes are refused to an agent by the
      permission classifier, tried on dev and on test; the curl is step 2 of
      `koras-control-plane/docs/runbooks/zitadel-worker-credential.md` and the
      token is the environment's own `ZITADEL_SERVICE_TOKEN`, which holds
      `IAM_OWNER`.
- [ ] The remaining halves of R-90, unchanged: enrolment of a second factor
      on a product page; the Control Plane's own portal.
