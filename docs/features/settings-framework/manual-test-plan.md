# Settings framework — Manual test plan

> **Not executed.** Every Actual, Pass/Fail and Evidence field is blank on
> 2026-09-19. A blank verdict is not a pass, and automated results never satisfy
> a manual gate.

These are the cases no automated test in this estate reaches. The resolver, the
coercion and the scope refusals are proven in `python-packages/koras-settings`;
the catalogue, the wiring and the capability behaviour in the starter's
structural suite; the isolation in `supabase/tests`; the routing, the access
control and the degraded rendering in `e2e/settings.spec.ts`. What is left is
everything that needs an API, a database, two organisations and a person
looking at a screen.

## Environment

| | |
|---|---|
| Environment | dev, against a deployed product, plus database access |
| Product under test | `koras-e2e-shop`, which has the only table page in the estate |
| Build under test | record the commit before starting |
| Verdicts | `PASS`, `FAIL`, `BLOCKED` — and nothing else |

## Accounts

| Name | Role | Tenant |
|------|------|--------|
| `owner-a` | organization owner | Tenant A |
| `admin-a` | organization admin | Tenant A |
| `member-a` | member | Tenant A |
| `owner-b` | organization owner | Tenant B |
| platform staff | Control Plane console access | — |

Several cases need `psql` as the restricted role `koras_rls_test`, not as the
owner. Running them as the owner proves nothing.

---

## TEST-SET-01 — A page size is a thing a person can watch work

**Priority** Critical. This is the case the whole framework exists to make true,
and the one with no automated equivalent anywhere.

**Steps**
1. As `member-a`, open `/dashboard/orders` in the shop. Confirm the seeded
   orders are present and the pager reads five pages at fifty.
2. Open `/dashboard/preferences`, set `grid.pageSize` to 25, save.
3. Return to `/dashboard/orders`.
4. Change the size to 250 using the pager's own control.
5. Reload the page.

**Expected.** Step 3 shows twenty-five rows and twelve pages without the page
being told anything. Step 4 changes the rows shown and returns to page 1 rather
than leaving the reader on a page that no longer holds what they were reading.
Step 5 shows twenty-five again — the pager's control is for this visit, the
preference is what persists.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-02 — The snapshot does not follow the platform

**Priority** Critical. The brief's central requirement, and the one a wrong
implementation satisfies on the happy path.

**Steps**
1. In the Control Plane console, Settings → Global Settings, note the current
   value of `grid.pageSize` for this product.
2. Sign up a **new** organisation, Tenant A.
3. In the console, change the platform default for `grid.pageSize` to 10.
4. Sign up a **second** new organisation, Tenant B.
5. As `owner-a`, read `/dashboard/settings`. As `owner-b`, read the same.

**Expected.** Tenant A still shows the value from step 1. Tenant B shows 10. The
change in step 3 reached no organisation that already existed.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-03 — What was copied, and when, is recorded

**Steps**
1. After TEST-SET-02, connect as `koras_rls_test`.
2. `select settings_global_version, settings_copied_at, settings_copied_by from tenants`
   for both tenants.

**Expected.** Both rows are populated, the timestamps differ, and Tenant B's
version is the later one. A null in any of the three means an organisation whose
old default cannot be told from a deliberate choice.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-04 — A member cannot change what the organisation decides

**Steps**
1. As `member-a`, open `/dashboard/settings`. Observe the notice.
2. Attempt the write anyway: `PATCH /tenant/settings/values` with a valid body,
   using `member-a`'s token.

**Expected.** Step 1 shows the notice before anything is filled in. Step 2 is a
403. The notice is courtesy; the 403 is the boundary, and a plan that only
checked step 1 would pass against a product with no server-side check at all.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-05 — A person cannot override what is not theirs to override

**Steps**
1. Pick a `GLOBAL_ORG` setting from `GET /settings/definitions` — one whose
   `user_visible` is false.
2. Confirm it is absent from `/dashboard/preferences`.
3. `PATCH /me/settings` with that key, using `member-a`'s token.

**Expected.** Step 2 shows the page cannot offer it. Step 3 is refused with the
scope error, not accepted and silently ignored — a write that returns 200 and
stores nothing is the failure mode worth looking for.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-06 — Clearing a preference gives back the organisation's value

**Steps**
1. As `admin-a`, set `ui.theme` for the organisation to a value that is not the
   platform default.
2. As `member-a`, set `ui.theme` to something else. Confirm the field reads
   "Yours".
3. Press Reset on that field.

**Expected.** The field returns to the organisation's value from step 1 — not to
the platform's, and not to the definition's default. The label returns to "From
your organisation" and names that value.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-07 — Resetting an organisation value is not the same act

**Steps**
1. As `admin-a`, reset a setting the organisation holds.
2. Query `tenant_setting_values` for that key.

**Expected.** The row still exists, holding the platform's current value. An
organisation reset is a copy, not a delete — deleting would make the
organisation start following the platform again, which is the snapshot rule
broken by the reset button.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-08 — One tenant cannot read another's settings

**Steps**
1. Connect as `koras_rls_test`, set `app.tenant_id` to Tenant A.
2. `select count(*) from tenant_setting_values`.
3. Attempt to select Tenant B's rows by id.
4. Repeat for `member_setting_values`, and additionally attempt to read
   `member-a`'s row while `app.user_id` is another member of Tenant A.

**Expected.** Tenant B's rows are invisible rather than redacted. A colleague in
the same organisation cannot read another person's preferences.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-09 — A secret-shaped key is refused by the database

**Steps**
1. As `koras_rls_test` with a valid tenant context, insert into
   `tenant_setting_values` with key `integrations.accessKey`.
2. Repeat with `integrations.access_key`, `billing.apiKey` and `x.password`.

**Expected.** All four are refused by the check constraint. The first is the one
that was accepted before the pattern was corrected, so it is the one that
matters.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-10 — Every write is in the register, and the platform's is separate

**Steps**
1. Make one change at each scope: platform (console), organisation (`admin-a`),
   person (`member-a`).
2. In the console, Settings → Change History.
3. In the product, read the tenant's own audit history.

**Expected.** The console shows the platform change and **not** the other two.
The product's own register shows the organisation and person changes under
Tenant A's isolation. No setting's value appears in a log line anywhere.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-11 — One save writes one category

**Steps**
1. As `admin-a`, change one field in Appearance and save.
2. Read the tenant's audit history.

**Expected.** The entries cover the Appearance category and nothing else. An
administrator who changed one field has not generated an audit entry for
twenty-six settings they only looked at.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-12 — `auto` still negotiates

**Steps**
1. Confirm `general.language` resolves to `auto` for a newly created
   organisation.
2. Open the product in a browser whose language is German.
3. Set `general.language` to `en` in preferences, then set it back to `auto`.

**Expected.** Step 2 is German. Step 3's return to `auto` resumes negotiation
rather than pinning English. This is the case the snapshot would have silently
ended.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-13 — The locale migration moved what was there

**Priority** Critical, and it can only be run once per environment.

**Steps**
1. Before applying `00031_settings_locale_migration.sql`, record
   `tenant_settings.locale` and `member_preferences.locale` for several rows.
2. Apply it.
3. Read `general.language` at both scopes for the same rows.

**Expected.** Every recorded value is present in the framework. The column and
the table are gone. Nobody's language changed.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-14 — Keyboard and screen reader

**Steps**
1. Reach every control on both pages by keyboard alone, at 1440 and 375.
2. Confirm the focus ring is visible on each, including the per-field Reset.
3. With a screen reader, confirm each Reset announces which field it resets, and
   that the save outcome is announced without moving focus.

**Expected.** No control is reachable only by pointer. "Reset" alone next to
twenty-seven fields does not say which one, so the accessible name must carry
the field's label.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-SET-15 — A product's own setting needs no page edit

**Steps**
1. In the shop, add one setting to `settings_catalogue/product.py`.
2. Deploy. Change nothing else.
3. Read `/dashboard/settings` or `/dashboard/preferences` as appropriate, and
   the Control Plane's Setting Definitions for that product.

**Expected.** It appears on the right page, with the right control, and in the
console. If any page needed editing, the extension point does not work and the
catalogue is not the single source it claims to be.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______
