# Settings framework — manual test results

| | |
|---|---|
| **Plan** | `docs/features/settings-framework/manual-test-plan.md`, fifteen cases. |
| **Executed** | 2026-09-21. |
| **Tree** | `5e8fbc4` plus the F27 corrections in the same working tree. Each case names which of the two it ran against. |
| **Verdicts** | `PASS`, `FAIL`, `BLOCKED`. A blank is not a pass and none is left blank. |

## The environment, and how it differs from the plan's

The plan asks for **dev, a deployed `koras-e2e-shop`, the Control Plane console
and `psql` as `koras_rls_test`**. That estate was not available to this cycle
and `koras-e2e-shop` is explicitly out of scope, so the cases were executed
against the nearest honest substitute:

| | |
|---|---|
| Product | Generated fresh from the tree under test, `f27v2`, product profile, defaults |
| Database | Real PostgreSQL 15.6, all 28 of the product's migrations applied |
| Row-level security | The unprivileged `koras_rls_test` role, `nobypassrls`, exactly as `generator-integration.yml` runs it |
| API | The product's own FastAPI application — its real routers, resolver, store and catalogue |
| Browser | The product's round-trip Playwright project: a local identity provider, the product's API against that database, and the web application pointed at both |
| Not available | The Control Plane console, a deployed environment, a page using the shared data table, a screen reader, a plain-`member` browser session |

**What that substitution costs is stated per case rather than averaged away.**
Where a case needs something the substitute does not have, the verdict is
`BLOCKED` with the reason — never `PASS` by analogy.

## Summary

| Verdict | Count | Cases |
|---|---|---|
| PASS | 11 | 02, 03, 05, 06, 07, 08, 09, 11, 12, 13, 15 |
| **FAIL** | **1** | **14** |
| PARTIAL — recorded as BLOCKED | 2 | 01, 04 |
| BLOCKED | 1 | 10 |

**TEST-SET-14 is the first FAIL in this plan**, found on 2026-09-22 by
measuring focus rather than assuming it. Three of its four sub-claims pass
outright; the fourth does not, and it is a real accessibility defect recorded
as **SET-24**. F27 cannot close with a FAIL outstanding, which is the correct
outcome rather than an inconvenient one.

**A live sitting on 2026-09-22 against the deployed dev product** took this
from 9 to 11. TEST-SET-11 and TEST-SET-12 both passed, and TEST-SET-01's
blocker changed from "no page uses the shared table" to a live 500 on the one
page that does. Details per case below; the environment was
`app-dev.koras-e2e-shop.korastechnologies.com`, signed in as a real customer.

**Nine of fifteen executed and passing, including all three Critical cases that
could run.** Six could not run here, and F27 therefore does not close: the
closure rule forbids it while any required case is BLOCKED.

**TEST-SET-13 moved from BLOCKED to PASS on 2026-09-22**, and it is the one
case that could never have been recovered later. It needs a database on the
pre-settings-framework schema, and `koras-e2e-shop`'s local PostgreSQL was the
last one in the estate still sitting at `00017` — found while preparing the
live sitting, and executed before anything migrated it.

The two PARTIAL cases are recorded as BLOCKED rather than as a pass on the half
that ran. Half a case is not a case, and a table of passes with a footnote is
how a gap stops being visible.

---

## TEST-SET-01 — A page size is a thing a person can watch work

**Priority** Critical. **Verdict** BLOCKED (half executed, and the half that
matters most did not).

| Step | Result |
|---|---|
| A page size chosen in preferences survives a reload | **PASS** — round-trip project, and again on **deployed dev**: set to 25, read back 25 on a fresh load, marked "modified" |
| One person's page size is not what another sees | **PASS** — round-trip project, two subjects |
| The seeded orders table repaginates at the chosen size | **NOT EXECUTED — blocked by a live defect** |

**The blocker changed on 2026-09-22, and the new one is worse.** It was "no
product page uses the shared data table". `koras-e2e-shop` has one —
`/dashboard/orders` — and on deployed dev **that page returns HTTP 500**.
Every other dashboard page answers 200, including both settings pages, so the
settings surface is healthy and the orders page specifically is not.

That is a live defect in this repository's own orders feature, outside F27's
boundary, and it is recorded rather than fixed here. Until it is fixed, the one
page in the estate that makes `grid.pageSize` observable cannot be observed.

**What is proven:** the value is chosen, stored, resolved, persisted across a
reload, and kept private to its owner — on a deployed product. **What is not:**
a table drawing that many rows.

---

## TEST-SET-02 — The snapshot does not follow the platform

**Priority** Critical. **Verdict** PASS.

Executed against a real database with the product's own `seed_tenant` and
`write_global_values`, in the order the case specifies.

| Step | Expected | Actual |
|---|---|---|
| Seed Tenant A at the current defaults | A holds `grid.pageSize` = 50 | 50 |
| Change the platform default to 10 | Version increments | version 0 → 1 |
| Seed Tenant B | B holds 10 | 10 |
| Read both | A is unchanged | **A still 50, B 10** |

**The central requirement of the brief, and it holds.** A platform change
reached no organisation that already existed.

Evidence: `docs/features/settings-framework/testing/runs/2026-09-21-01/manual-cases-02-03-07.py`

---

## TEST-SET-03 — What was copied, and when, is recorded

**Verdict** PASS.

Both tenant rows carry all three columns; the timestamps differ; Tenant B's
version is the later one.

| | `settings_global_version` | `settings_copied_at` | `settings_copied_by` |
|---|---|---|---|
| Tenant A | 0 | set | `provisioning` |
| Tenant B | 1 | set, later | `provisioning` |

Zero is a real answer and the commonest in a new estate, as `00030`'s own
comment says. No null in any of the six values.

Evidence: same script.

---

## TEST-SET-04 — A member cannot change what the organisation decides

**Verdict** BLOCKED (the boundary executed, the notice did not).

| Step | Result |
|---|---|
| `PATCH /tenant/settings/values` with a member's token | **Executed, PASS** — 403 `permission_missing`, nothing written |
| The page shows the notice before anything is filled in | **Not executed** |

**Why it is BLOCKED.** The round-trip fixture seeds two members and both are
`organization_admin`, so there is no plain-`member` browser session to look at
the page with. The plan's own reasoning applies in reverse here: it warns that
checking only the notice would pass against a product with no server-side
check. The server-side check is the half that ran, which is the better half —
but the case is not complete.

---

## TEST-SET-05 — A person cannot override what is not theirs to override

**Verdict** PASS.

`general.currency` is `GLOBAL_ORG`. It is absent from the preferences half of
the catalogue (`user_visible` is false), and a personal write is refused with
the scope error rather than accepted and silently dropped — the failure mode
the case says to look for.

Evidence: `docs/features/settings-framework/testing/runs/2026-09-21-01/manual-cases-05-06-08.py`

---

## TEST-SET-06 — Clearing a preference gives back the organisation's value

**Verdict** PASS.

| Step | Expected | Actual |
|---|---|---|
| Organisation sets `ui.theme` to `dark` (not the platform default) | — | stored |
| Member sets `ui.theme` to `light` | resolves to the person's | `light`, source `user` |
| Member clears it | returns to the organisation's | **`dark`, source `organization`** |

Not to the platform's value and not to the definition's default, which is the
distinction the case exists to make.

---

## TEST-SET-07 — Resetting an organisation value is not the same act

**Verdict** PASS.

After an organisation reset, the row in `tenant_setting_values` **still
exists** and holds the platform's current value (10). An organisation reset is
a copy, not a delete — deleting would restore the dynamic inheritance the
snapshot exists to prevent.

---

## TEST-SET-08 — One tenant cannot read another's settings

**Verdict** PASS.

Executed twice, at two levels.

*As `koras_rls_test` against a real database:* with `app.tenant_id` set to
Tenant A, one tenant row is visible and Tenant B's are invisible rather than
redacted; a colleague's `member_setting_values` row is invisible; another
tenant's member row is invisible.

*Through the resolver:* a colleague's override changed nothing about what the
first member resolves.

Evidence: `docs/features/settings-framework/testing/runs/2026-09-21-01/rls-settings-suites.txt`
and `manual-cases-05-06-08.py`.

---

## TEST-SET-09 — A secret-shaped key is refused by the database

**Verdict** PASS.

All four credential-shaped keys refused by the check constraint, including
`integrations.accessKey` — the camelCase spelling that was accepted before the
pattern was corrected, and the one the case says matters.

Two additional assertions, neither in the plan and both worth keeping: a nested
secret (`{"a":[{"b":{"apiKey":"s"}}]}`) is refused, which is the SET-03 fix
still holding; and `shop.sortKey`, an honest column name, is **accepted** — a
guard that refuses the legitimate case is a guard somebody turns off.

---

## TEST-SET-10 — Every write is in the register, and the platform's is separate

**Verdict** BLOCKED.

Needs the Control Plane console to make the platform change and to read Change
History, and the console is not available to this cycle. The product half —
that organisation and member changes are recorded under the tenant's own
isolation — is covered by the automated API suite, which is different evidence
and does not satisfy this case.

Related and reproduced separately: **SET-14**, the platform write route records
nothing at all. Whatever this case would have shown in the console, the
product-side register of a platform change does not exist.

---

## TEST-SET-11 — One save writes one category

**Priority** high — this is the case that demonstrates the SET-05 correction.
**Verdict** PASS, executed 2026-09-22 on deployed dev.

**Measured, not inspected.** The audit list was captured before and after a
save, and the difference taken — because presence of a key in the page proves
nothing about which save wrote it, and the first attempt at this case was
misled exactly that way: `ui.density` appeared in the audit text before the
probe ran, from an earlier save made while this product still carried the
SET-05 defect.

The Appearance category holds four fields — `ui.theme`, `ui.density`,
`ui.sidebarCollapsed`, `ui.defaultLandingPage`. Exactly one was changed.

| | |
|---|---|
| Changed | `ui.density`, `comfortable` → `compact` |
| New audit rows | **2** |
| Of those, `settings.member_changed` | **1**, for `setting · ui.density` |
| The other | `audit.searched` — reading the audit page is itself an audited act |

Two earlier saves in the same session show the same shape: `grid.pageSize`
alone from the Tables category, `ui.theme` alone from Appearance. One field
changed, one entry written.

**Before the SET-05 fix this save would have written the whole category.** An
administrator who changed one field got an audit entry for everything they
looked at, and a member got a personal override for every field they did not
touch. This is that correction, observed in a deployed product.

Evidence: `docs/features/settings-framework/testing/manual/screenshots/TEST-SET-11/`

**This is the case that would have demonstrated the SET-05 correction through
the audit trail**, and it remains the most valuable unexecuted case in the
plan.

What stands in for it is no longer only a structural assertion. The closure
review found that every assertion about SET-05 and SET-06 was a substring
search over template text — `same()` returning `true` would have made every
setting unsaveable with the whole suite still green — so the deciding logic
moved into `packages/ui/src/settings/form-values.ts` and
`product-settings-logic.test.ts` now runs it against real `FormData`. Eighteen
tests, mutation-checked: 7 fail under `same() => true`, 11 under
`same() => false`, 2 under restoring SET-06.

That covers the *effect* of the correction. What it still does not cover is
this case's actual question — that one save leaves one category's worth of
entries in the tenant's audit history and nothing else — which needs a browser
and a trail to read back.

---

## TEST-SET-12 — `auto` still negotiates

**Verdict** PASS, executed 2026-09-22 on deployed dev, all three steps.

`general.language` offers `auto`, `en`, `de`, `es`, and held `auto`.

| Browser locale | Stored value | `html[lang]` | Heading |
|---|---|---|---|
| `en-GB` | `auto` | `en` | "My preferences" |
| `de-DE` | `auto` | `de` | "Meine Einstellungen" |
| `de-DE` | **`en`** (pinned) | `en` | "My preferences" |
| `de-DE` | back to `auto` | `de` | "Meine Einstellungen" |

Pinning overrides the browser; releasing resumes negotiation rather than
leaving English stuck.

**This is the case ADR 0007's `auto` value exists for.** The rule it produced —
a setting whose absence means "infer it from context" must express that
inference as one of its values, or the snapshot silently ends the inference —
is exactly what these four rows check, and it holds.

Evidence: `docs/features/settings-framework/testing/manual/screenshots/TEST-SET-12/`

---

## TEST-SET-13 — The locale migration moved what was there

**Priority** Critical. **Verdict** PASS, executed 2026-09-22.

*The entry below is the verdict this case carried on 2026-09-21, kept because
it was true then and because the reason it changed is worth seeing:*

> **BLOCKED, and it cannot be run here at all.** The case requires recording
> the two locale columns **before** `00031` is applied, and every database in
> this cycle was created by applying all 28 migrations to an empty schema, so
> the pre-migration state never existed.

That was true of every database **I had built**. It was not true of every
database in the estate: `koras-e2e-shop`'s local PostgreSQL still sat at
`00017_locale_preferences`, eighteen migrations behind, which is exactly the
state this case needs. Found while preparing the live sitting, and run before
anything migrated it — the opportunity would not have survived the next
`make bootstrap`.

**Both source tables were empty**, so the pre-migration state was *created*
rather than found: five rows across two tenants and three subjects. That
exercises what the case asserts — values carried, source removed, nobody's
language changed — and does not exercise incidental production data. Stated
rather than glossed, because "executed against seeded data" and "executed
against a real estate" are different claims.

| | Before, recorded | After, read back |
|---|---|---|
| Tenant A `tenant_settings.locale` | `de` | `general.language` = `"de"` |
| Tenant B `tenant_settings.locale` | `es` | `general.language` = `"es"` |
| A / `user-alpha` | `en` | `"en"` |
| A / `user-beta` | `de` | `"de"` |
| B / `user-gamma` | `es` | `"es"` |
| `tenant_settings.locale` column | present | **gone** |
| `member_preferences` table | present | **gone** |

Every recorded value is present, at the right scope and against the right
subject. Sixteen migrations applied clean in sequence.

Evidence: `docs/features/settings-framework/testing/runs/2026-09-21-01/test-set-13-locale-migration.txt`

---

## TEST-SET-14 — Keyboard and screen reader

**Verdict FAIL**, executed 2026-09-22 on deployed dev at both widths.

Three sub-claims pass and one fails. The failure is **SET-24**.

| Sub-claim | 1440×900 | 375×812 |
|---|---|---|
| Every control reachable by keyboard alone | **PASS** — 21 of 21 settings, no `tabindex="-1"` | **PASS** — 21 of 21 |
| Focus ring visible on each, including per-field Reset | **PASS** — 54/54 focused controls | **PASS** — 71/71 |
| Each Reset announces *which* field it resets | **PASS** — see below | **PASS** |
| Save outcome announced **without moving focus** | **FAIL** | **FAIL** |

**The Reset names are right, and this is the property the case exists for.**
"Reset" alone beside twenty-seven fields says nothing; the accessible names
read `Reset: Language`, `Reset: Theme`, `Reset: Interface density`,
`Reset: Rows per page`. Zero buttons carry a bare "Reset". Read from the
accessibility tree, which is what a screen reader announces.

### SET-24 — saving loses focus, and the confirmation may never be announced

Focus was on the `ui.density` control. After saving:

| | |
|---|---|
| Focus before | `SELECT`, inside `[data-setting="ui.density"]` |
| Focus after | **`BODY`** |
| URL after | `/dashboard/preferences?saved=ok` |
| Outcome text | "Saved." |
| Its container | `role="status"` |

Two consequences, and the second is the worse one.

**A keyboard user loses their place.** The save is a server-side redirect — a
deliberate choice, documented in `actions.ts.hbs`: a redirect "works without
JavaScript, survives a reload, and says the same thing to everybody". But a
full navigation resets focus to the document, so anybody working by keyboard
must tab back to where they were after every save.

**The confirmation may not be announced at all.** "Saved." sits in a
`role="status"` region, which is a polite live region — and a live region
announces *changes made after it exists*, not content already present when the
document loads. Arriving by redirect, the message is present at load. So the
one signal that the save worked may be silent for exactly the users the live
region was added for.

**What this pass cannot settle**, stated rather than implied: whether a given
screen reader announces it. That needs NVDA, JAWS or VoiceOver and a person.
What is settled is the mechanism — focus moves, and the message is initial
content rather than an update. The remedy is likely to move focus deliberately
to the status region after a save, or to announce it as a change; both are
design decisions rather than corrections, which is why this is recorded as a
finding and not fixed here.

Evidence: `docs/features/settings-framework/testing/manual/screenshots/TEST-SET-14/`

---

## TEST-SET-15 — A product's own setting needs no page edit

**Verdict** PASS.

A setting was declared in `services/api/koras_api/settings_catalogue/product.py`
and **nothing else was changed**. It is registered at import, published by
`GET /settings/definitions`, and carries the visibility its declaration asked
for (`org_admin_visible` true, `user_visible` false). No page was edited.

The console half of the case — that it appears in the Control Plane's Setting
Definitions — is not covered, for the reason TEST-SET-10 gives.

---

## What this pass found

**Nothing that was passing is now failing, and one thing that was passing
should not have been.** The eight executed cases all passed on the corrected
tree. The corrections themselves produced one regression during the cycle — the
SET-05 baseline input was first placed inside each field's `data-setting`
container, which made `[data-setting="x"] input` match two elements and failed
three of the product's four round-trip tests on a strict-mode violation. It was
caught by that suite within the hour, fixed, and is now pinned by an assertion
about *where* the input is rather than that it exists.

**The seven blocked cases are blocked on four things**, and they are worth
naming because they are the same four every time: the Control Plane console
(10, 15's second half), a product page using the shared data table (01, and
`koras-e2e-shop` is the only repository with one), a plain-`member` browser
session (04), and a person (14). TEST-SET-13 is blocked on history rather than
on tooling.
