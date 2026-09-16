# SAG-F1 — Manual test plan

> **Not executed.** Every Actual, Pass/Fail and Evidence field below is blank
> on 2026-09-16 because no manual QA pass has been run against this work. A
> blank verdict is not a pass, and per
> `profiles/product/template/.claude/orchestration/documentation-policy.yaml`
> automated results never satisfy a manual gate.

## Why these cases are manual

CI has Postgres and no bucket, so no real upload happens there
(`FOLLOW_UPS.md` F22). Everything below needs either a real object store, two
signed-in browsers, or both.

## Environment

| | |
|---|---|
| Environment | dev, against a deployed product |
| Local alternative | the Compose stack with MinIO on the `storage` service |
| Build under test | record the commit before starting |
| Verdicts | `PASS`, `FAIL`, `BLOCKED` — and nothing else |

## Accounts

| Name | Role | Tenant |
|------|------|--------|
| `owner-a` | organization owner | Tenant A |
| `member-a` | member | Tenant A |
| `owner-b` | organization owner | Tenant B |
| `member-nostorage` | member of a tenant whose plan lacks `storage.files` | Tenant C |

## Test data

| File | Purpose |
|------|---------|
| `test-document.pdf` | ~2 MB, ordinary |
| `same-name.pdf` | identical filename, different bytes, for the collision case |
| `large.bin` | just under 5 GiB, for the ceiling |
| `eicar.com` | the standard anti-malware test string, for the scan case |

---

## TEST-STORAGE-003-01 — Tenant storage isolation

**Story** STORAGE-003 · **AC** STORAGE-003-AC01 · **Priority** Critical

**Purpose.** Verify that one tenant cannot retrieve another tenant's object,
and that the refusal is server-side.

**Preconditions.** Tenant A and Tenant B exist. Both have `storage.files`.

**Role** `owner-a`, then `owner-b`.

**Steps**
1. Sign in as `owner-a`.
2. Go to Files and upload `test-document.pdf`.
3. Record the file id from the row.
4. Sign out.
5. Sign in as `owner-b`.
6. Attempt to fetch `/api/v1/files/<recorded id>/download` directly, with
   `owner-b`'s session.
7. Attempt the same against `/api/v1/files/<recorded id>`.

**Expected.** Both attempts answer **404**, not 403 — 403 would confirm the row
exists. No file contents are returned. No filename or size is disclosed. An
audit row exists for Tenant A's upload and none for Tenant B's attempt against a
row it cannot see.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______ · **Notes** ______

---

## TEST-STORAGE-003-02 — Same filename, two tenants

**Story** STORAGE-003 · **AC** STORAGE-003-AC01 · **Priority** High

**Steps**
1. As `owner-a`, upload `same-name.pdf`.
2. As `owner-b`, upload a different file also called `same-name.pdf`.
3. Download each as its own tenant.

**Expected.** Each tenant receives its own bytes. The two object keys differ by
tenant prefix and file id. Neither listing shows the other's row.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-005-01 — Quota refusal names the plan

**Story** STORAGE-005 · **AC** STORAGE-005-AC01 · **Priority** High

**Preconditions.** Tenant A is at or near its plan ceiling.

**Steps**
1. Sign in as `owner-a`.
2. Attempt an upload that would exceed the ceiling.

**Expected.** Refused with 402. The message names the plan. The page states the
limit rather than failing silently. An audit row records
`storage.upload.refused` with outcome `denied` and reason `quota`.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-005-02 — Quota re-checked at confirmation

**Story** STORAGE-005 · **AC** STORAGE-005-AC02 · **Priority** High

**Purpose.** The case no automated test covers: two tickets each inside the
ceiling and jointly over it.

**Steps**
1. With the tenant near its ceiling, start two uploads in two browser tabs so
   both tickets are issued before either confirms.
2. Let both PUTs finish.
3. Observe both confirmations.

**Expected.** The first confirmation succeeds. The second is refused with 402,
its row is removed, and the object is left in the bucket for reconciliation
rather than deleted. Reconciliation later reports it as an orphan.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-008-01 — Signed URL scope and expiry

**Story** STORAGE-008 · **AC** STORAGE-008-AC01..02 · **Priority** Critical

**Steps**
1. As `owner-a`, request a download for an owned file; copy the URL.
2. Open it in a private window with no session. Note the disposition.
3. Wait six minutes and open it again.
4. Edit the URL's key to another object and open it.

**Expected.** Step 2 downloads as an attachment and does not render in the tab.
Step 3 is refused by the provider as expired. Step 4 is refused: the signature
covers the key. The URL contains no secret key material.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-017-01 — Digest recorded and its provenance distinguished

**Story** STORAGE-017 · **AC** STORAGE-017-AC01 · **Priority** High

**Steps**
1. Compute the SHA-256 of `test-document.pdf` locally.
2. As `owner-a`, upload it.
3. Read the file row from `/api/v1/files`.
4. Read `checksum_sha256` and `checksum_verified_at` from the database.

**Expected.** The recorded digest equals the one computed locally.
`checksum_verified` is true **only if** the provider offered a comparable
digest that agreed; on Supabase Storage it may legitimately be false, and false
must not be presented as a mismatch.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-017-02 — An unhashable upload still succeeds

**Story** STORAGE-017 · **AC** STORAGE-017-AC02 · **Priority** Medium

**Steps**
1. Open the product over plain http, where `crypto.subtle` is unavailable.
2. Upload `test-document.pdf`.

**Expected.** The upload succeeds. No digest is recorded. No error is shown.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-018-01 — An infected file is withheld

**Story** STORAGE-018 · **AC** STORAGE-018-AC01 · **Priority** Critical

**Preconditions.** A scan hook is registered. **As of 2026-09-16 none is, so
this case is `BLOCKED` until a product installs one** — record it as BLOCKED
with that reason rather than as a pass.

**Steps**
1. Upload `eicar.com` as `owner-a`.
2. Wait for the scan hook to record its result.
3. Attempt a download.

**Expected.** The row shows `scan_status` `infected` and status `quarantined`.
The download is refused with 403 before any URL is signed. The object still
exists in the bucket. A security-classified audit row records the refusal.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-018-02 — No scanner means no refusal

**Story** STORAGE-018 · **AC** STORAGE-018-AC02 · **Priority** High

**Steps**
1. On a product with no scan hook, upload and download an ordinary file.

**Expected.** Succeeds. Every file is `pending` and `pending` is not withheld.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-019-01 — Reconciliation finds an orphan and removes nothing

**Story** STORAGE-019 · **AC** STORAGE-019-AC01 · **Priority** High

**Steps**
1. Enable the sweep with `STORAGE_RECONCILE_ENABLED`.
2. Put an object into the tenant's prefix directly with a bucket client, with no
   corresponding row.
3. Leave a `pending` row older than the stale window with no object.
4. Run the sweep.
5. Inspect the object, the row, and the audit table.

**Expected.** The run reports one orphan object and one stale pending row.
**The object still exists and the row still exists.** One audit row records the
finding with counts and no key.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-019-02 — A foreign-bucket tenant is unverifiable, not missing

**Story** STORAGE-019 · **AC** STORAGE-019-AC03 · **Priority** High

**Preconditions.** A tenant whose Control Plane storage policy names a bucket
the worker holds no credential for.

**Steps**
1. Upload a file as that tenant.
2. Run the sweep.

**Expected.** The row is counted **unverifiable**. It is not reported as an
orphan, not reported as missing, and no alert implies data loss.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-004-01 — An unsupported provider is refused, not defaulted

**Story** STORAGE-004 · **AC** STORAGE-004-AC02 · **Priority** Critical

**Steps**
1. Set a tenant's storage policy to `azure-blob` in the Control Plane.
2. Attempt an upload as that tenant.
3. Inspect the platform default bucket.

**Expected.** 503 with a reason naming the provider. **Nothing is written to the
default bucket** — silently storing a customer's data somewhere they did not
choose is worse than an outage.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-ENT-01 — A plan without storage is refused and says so

**Story** STORAGE-005 · **AC** STORAGE-005-AC01 · **Priority** Medium

**Steps**
1. Sign in as `member-nostorage`.
2. Observe the sidebar, then open Files directly by URL.
3. Attempt an upload through the API.

**Expected.** The module is locked in the sidebar. The page names the plan. The
API refuses with 402 `ENTITLEMENT_MISSING`. The refusal is audited.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## TEST-STORAGE-RBAC-01 — Deletion needs an owner or administrator

**Story** STORAGE-003 · **Priority** High

**Steps**
1. As `member-a`, attempt to delete a file through the API.
2. As `owner-a`, delete the same file.

**Expected.** The first is refused with 403 `ROLE_REQUIRED` and audited as
`storage.object.delete_refused`, a security event. The second succeeds, removes
the object before the row, and is audited as `storage.object.deleted`.

**Actual** ______ · **Pass/Fail** ______ · **Evidence** ______

---

## Coverage summary

| Case | Story | Blocked? |
|------|-------|----------|
| TEST-STORAGE-003-01 | STORAGE-003 | no |
| TEST-STORAGE-003-02 | STORAGE-003 | no |
| TEST-STORAGE-005-01 | STORAGE-005 | no |
| TEST-STORAGE-005-02 | STORAGE-005 | no |
| TEST-STORAGE-008-01 | STORAGE-008 | no |
| TEST-STORAGE-017-01 | STORAGE-017 | no |
| TEST-STORAGE-017-02 | STORAGE-017 | no |
| TEST-STORAGE-018-01 | STORAGE-018 | **yes — no scanner installed** |
| TEST-STORAGE-018-02 | STORAGE-018 | no |
| TEST-STORAGE-019-01 | STORAGE-019 | no |
| TEST-STORAGE-019-02 | STORAGE-019 | needs a foreign-bucket tenant |
| TEST-STORAGE-004-01 | STORAGE-004 | needs a Control Plane policy edit |
| TEST-STORAGE-ENT-01 | STORAGE-005 | needs a plan without storage |
| TEST-STORAGE-RBAC-01 | STORAGE-003 | no |

Backup and restore cases are deliberately absent: nothing to test until
STORAGE-009 through STORAGE-013 are built.
