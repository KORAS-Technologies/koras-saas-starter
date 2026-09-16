# SAG-F2 — Manual test plan

> **Not executed.** Every Actual, Pass/Fail and Evidence field is blank on
> 2026-09-16. A blank verdict is not a pass, and automated results never satisfy
> a manual gate.

## Environment

| | |
|---|---|
| Environment | dev, against a deployed product, plus database access |
| Build under test | record the commit before starting |
| Verdicts | `PASS`, `FAIL`, `BLOCKED` — and nothing else |

## Accounts

| Name | Role | Tenant |
|------|------|--------|
| `owner-a` | organization owner | Tenant A |
| `member-a` | member | Tenant A |
| `owner-b` | organization owner | Tenant B |

Several cases need `psql` as the restricted role `koras_rls_test`, not as the
owner. Running them as the owner proves nothing.

---

## TEST-AUDIT-002-01 — A refusal is recorded as firmly as a success

**Story** AUDIT-002 · **AC** AUDIT-002-AC01 · **Priority** Critical

**Steps**
1. As `member-a`, attempt to delete a file (a member may not).
2. Observe the 403.
3. Query `audit_events` for Tenant A, newest first.

**Expected.** A `storage.object.delete_refused` row exists with outcome
`denied`, classification `security`, and `file_id` in details. **No detail key
contains a credential-shaped word, and `storage_key` appears nowhere.**

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-004-01 — One tenant cannot read another's history

**Story** AUDIT-004 · **AC** AUDIT-004-AC02 · **Priority** Critical

**Steps**
1. Generate activity as both `owner-a` and `owner-b`.
2. Connect as `koras_rls_test` and set `app.tenant_id` to Tenant A.
3. `select count(*) from audit_events`.
4. Attempt to select rows belonging to Tenant B.

**Expected.** Only Tenant A's rows are counted. Tenant B's are invisible, not
redacted.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-004-02 — No principal can edit or delete a row

**Story** AUDIT-004, AUDIT-016 · **AC** AUDIT-004-AC03, AC-04 · **Priority** Critical

**Steps**
1. As `koras_rls_test` with Tenant A bound, `update audit_events set action = 'tampered'`.
2. `delete from audit_events`.
3. Repeat both with `app.provisioning` set to `on`.

**Expected.** Steps 1 and 2 change nothing. Under provisioning, the update still
changes nothing — **there is no update policy for anyone** — while the delete is
permitted, because that is the sweep's path.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-007-01 — Each class is kept for its own time

**Story** AUDIT-007, AUDIT-009 · **AC** AUDIT-007-AC01 · **Priority** High

**Test data.** Rows aged beyond each threshold: activity at 100 days, audit at
400, security at 400 and at 1200.

**Steps**
1. Insert the rows above as the owner, with explicit `created_at` values.
2. Run the retention sweep.
3. Count what survives, by class.

**Expected.** The 100-day activity row is gone. The 400-day audit row is gone.
The 400-day security row **survives**. The 1200-day security row is gone. The
log names the counts per class.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-007-02 — A misconfigured class deletes nothing

**Story** AUDIT-007 · **AC** AUDIT-007-AC03 · **Priority** High

**Steps**
1. Set `AUDIT_SECURITY_RETENTION_DAYS` to `0`.
2. Run the sweep.
3. Count rows of **all four** classes afterwards.

**Expected.** The sweep raises. **Nothing is deleted, including the three
classes that were configured correctly.** The guard runs over every class before
the first delete.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-020-01 — Classification comes from the registry

**Story** AUDIT-020 · **AC** AUDIT-020-AC01 · **Priority** High

**Steps**
1. Download a file as `owner-a`, then attempt a deletion as `member-a`.
2. Read both rows' `classification`.

**Expected.** The download is `activity`; the refused deletion is `security`.
No API input influenced either — the class is not a parameter anywhere.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-021-01 — Every storage operation is recorded

**Story** AUDIT-021 · **AC** AUDIT-021-AC01 · **Priority** Critical

**Steps**
1. As `owner-a`: upload a file, download it, then delete it.
2. Read the audit rows for the tenant.

**Expected.** Three rows: `storage.object.uploaded` with size, content type and
an `integrity` value of `verified`, `claimed` or `none`;
`storage.object.downloaded`; `storage.object.deleted`. **The digest itself is
not recorded**, only whether it was verified, claimed or absent.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-021-02 — A quota refusal is recorded

**Story** AUDIT-021 · **AC** AUDIT-021-AC02 · **Priority** High

**Steps**
1. With Tenant A at its ceiling, attempt an upload.
2. Read the newest audit row.

**Expected.** `storage.upload.refused`, outcome `denied`, classification
`security`, reason `quota` or `entitlement`.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-019-01 — An undeclared action is refused

**Story** AUDIT-019 · **AC** AUDIT-019-AC04 · **Priority** Medium

**Steps**
1. In a scratch branch, add a call recording an action not in the registry.
2. Exercise the route.
3. Count rows before and after.

**Expected.** The call raises with a message naming the unregistered action. No
row is written. **This is deliberate**: a default class would mean a security
event swept on the activity schedule.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-014-01 — The private contract refuses a customer token

**Story** AUDIT-014 · **AC** AUDIT-014-AC02 · **Priority** Critical

**Steps**
1. Obtain a valid customer token as `owner-a`.
2. Call `GET /internal/platform/v1/activity` with it.
3. Call it with no token.

**Expected.** Both refused. The refusal does not echo the subject — confirming
which account was seen turns a refusal into an oracle.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-AUDIT-FOUNDATION-01 — Audit survives a product without reporting

**Story** AUDIT-004 · **AC** AUDIT-004-AC01 · **Priority** High

**Steps**
1. Generate a product with `--without reporting`.
2. Check for `00013_audit_events.sql`, `00019_audit_classification.sql`,
   `core/audit.py`, `tasks/audit_retention.py` and `110_audit_isolation.sql`.
3. Apply migrations and run the RLS suite.
4. Check the worker's cron list and the secrets manifest.

**Expected.** All present. The sweep is scheduled. `AUDIT_RETENTION_DAYS` is
declared. No reporting action is registered.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## Coverage summary

| Case | Story | Blocked? |
|------|-------|----------|
| TEST-AUDIT-002-01 | AUDIT-002 | no |
| TEST-AUDIT-004-01 | AUDIT-004 | no |
| TEST-AUDIT-004-02 | AUDIT-004, 016 | no |
| TEST-AUDIT-007-01 | AUDIT-007, 009 | no |
| TEST-AUDIT-007-02 | AUDIT-007 | no |
| TEST-AUDIT-020-01 | AUDIT-020 | no |
| TEST-AUDIT-021-01 | AUDIT-021 | no |
| TEST-AUDIT-021-02 | AUDIT-021 | needs a tenant at its ceiling |
| TEST-AUDIT-019-01 | AUDIT-019 | needs a scratch branch |
| TEST-AUDIT-014-01 | AUDIT-014 | no |
| TEST-AUDIT-FOUNDATION-01 | AUDIT-004 | no |

Search, filtering, export, archival and hold cases are deliberately absent:
nothing to test until AUDIT-005, 006, 008, 010 and 011 are built.
