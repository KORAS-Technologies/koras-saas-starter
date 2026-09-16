# SAG-F1 — Acceptance criteria

Every criterion names the automated test that asserts it, or says that none
does. Criteria for stories marked `EXISTING` or `Built` in `user-stories.md`
were written on 2026-09-16 against behaviour that already existed, so they
describe it rather than constrain it; criteria for `Planned` and `Blocked`
stories are constraints on work not yet done.

Traceability to tests is `testing.md`; to manual cases, `manual-test-plan.md`.

---

# STORAGE-001 — Storage provider abstraction

## AC-01
**Given** an object store for any supported provider
**When** a caller asks for a page of a prefix
**Then** at most the requested number of keys is returned
**And** the answer says whether the listing was truncated
**And** a continuation cursor is present only when it was.
*Test:* `test_a_listing_is_paged_and_says_when_there_is_more`

## AC-02
**Given** an object uploaded in more than one part
**When** its digest is requested
**Then** the answer is **absent**, not a value
**Because** a multipart entity tag is a digest of digests, and returning it
would report every large object as corrupt.
*Test:* `test_a_multipart_entity_tag_is_absent_rather_than_wrong`

## AC-03
**Given** the protocol gained operations after implementations existed
**When** the package is typechecked
**Then** no implementation is broken by the addition.
*Test:* mypy over a generated project, 97 source files

---

# STORAGE-002 — Storage metadata registry

## AC-01
**Given** a product generated at any capability combination
**When** the migrations are applied in order
**Then** `00018_files_governance.sql` applies without error
**And** `files.status` admits `pending`, `ready`, `quarantined`, `archived`, `deleted` and `purged`
**And** no soft-delete column is introduced.
*Test:* the row-level security job, all three product matrix rows

## AC-02
**Given** two tenants each with a file
**When** tenant A reads, updates or deletes as the restricted role
**Then** only A's row is visible
**And** an attempt to set B's `legal_hold`, `retain_until` or `classification` touches nothing
**And** an insert naming B raises `insufficient_privilege`.
*Test:* `supabase/tests/170_files_governance_isolation.sql`

---

# STORAGE-003 — Tenant-isolated object storage

## AC-01
**Given** tenant A and tenant B both have storage access
**When** A uploads `document.pdf`
**Then** the object is associated with A
**And** B cannot retrieve it
**And** the refusal is server-side, not a hidden button
**And** an audit event records the attempt.
*Test:* `supabase/tests/050_files_isolation.sql` for the data boundary;
`test_storage_audit.py` for the record. **The end-to-end refusal across two
signed-in browsers is manual: `TEST-STORAGE-003-01`.**

## AC-02
**Given** an authenticated administrator of tenant A
**When** a signed download URL is requested
**Then** the URL names only A's object
**And** it expires in five minutes
**And** it carries no storage credential.
*Test:* `test_signed_urls_name_the_bucket_and_key_and_nothing_else_secret`

## AC-03
**Given** a row belonging to tenant B
**When** tenant A requests it by id
**Then** the answer is 404, not 403
**Because** 403 confirms the row exists, which is itself a disclosure.
*Test:* none. **Gap — no automated test asserts the 404-not-403 choice.**

---

# STORAGE-004 — Configurable storage providers

## AC-01
**Given** a customer whose storage policy names Cloudflare R2
**When** they upload
**Then** the object is signed against R2 with that provider's credential
**And** the credential never reaches the browser.

## AC-02
**Given** a policy naming `azure-blob` or `customer-owned`
**When** any storage operation is attempted
**Then** it is refused with 503 and a reason
**And** nothing is written to the platform default
**Because** silently writing a customer's data somewhere they did not choose is
worse than an outage.
*Test:* `test_storage.py` resolution cases

---

# STORAGE-005 — Storage quotas

## AC-01
**Given** a tenant at its plan ceiling
**When** an upload ticket is requested
**Then** it is refused with 402 naming the plan
**And** the refusal is audited as `storage.upload.refused` with outcome `denied`.
*Test:* `test_a_refusal_is_recorded_as_firmly_as_a_success`

## AC-02
**Given** two upload tickets issued together, each inside the ceiling and
jointly over it
**When** the second is confirmed
**Then** it is refused with 402
**And** its row is removed
**And** the object is left for reconciliation rather than deleted on a client's word.
*Test:* the confirmation path in `routers/files.py`. **Gap — no test exercises
two concurrent tickets; the re-check is asserted by reading, not by racing.**

---

# STORAGE-006 — Object lifecycle *(planned)*

## AC-01
**Given** an object whose `retain_until` has passed and which is not held
**When** the lifecycle sweep runs
**Then** it moves to the next state, and PURGE removes it
**And** every transition is audited.

## AC-02
**Given** an object whose `retain_until` is null
**When** the sweep runs
**Then** it is treated as not-yet-eligible, never as due
**Because** null means no policy has been resolved, and the opposite reading
would delete every unclassified object.

## AC-03
**Given** a tenant policy shorter than the platform floor
**When** retention is resolved
**Then** the floor wins.

---

# STORAGE-008 — Secure signed URLs

## AC-01
**Given** an upload ticket for a PDF
**When** the browser sends a different content type
**Then** the provider rejects the PUT, because the type is in the signature.

## AC-02
**Given** any download ticket
**When** the URL is opened
**Then** the response carries an attachment disposition
**Because** a file a customer uploaded is not a page this product vouches for.
*Test:* `test_signed_urls_name_the_bucket_and_key_and_nothing_else_secret`

## AC-03
**Given** a filename containing path separators or control characters
**When** a key and a disposition header are built from it
**Then** both are sanitised and the object cannot escape its prefix.
*Test:* `test_a_name_that_tries_to_leave_its_prefix_cannot`

---

# STORAGE-009 — Daily backup *(blocked)*

## AC-01
**Given** a scheduled run
**When** it finishes for any reason
**Then** a catalogue row records the outcome, the counts and the first error
**Because** one bad night must neither stop the job for good nor repeat it hourly.

## AC-02
**Given** a run that could not read every object
**Then** it is recorded partial, never completed.

## AC-03
**Given** the destination is unreachable
**Then** the run fails, alerts, and changes no object's state.

---

# STORAGE-011 — Backup integrity verification *(blocked)*

## AC-01
**Given** a nightly run where every copy call returned success
**And** one destination object's digest differs from its source
**Then** the run is `failed`, not `completed`
**And** the specific object is named
**And** the failure is alerted.

## AC-02
**Given** an object with no comparable provider digest
**Then** it is recorded `copied`, never `verified`, and never `failed`.

---

# STORAGE-012 — Object restore *(blocked)*

## AC-01
**Given** a member without owner or administrator role
**When** an overwriting restore is requested
**Then** it is refused, and the refusal is audited.

## AC-02
**Given** an owner who lacks the permission the restore needs
**When** they approve it
**Then** the approval is refused
**Because** an approver must be someone who could have performed the action.

## AC-03
**Given** an unresolved entitlement plan
**When** a restore is requested
**Then** it is refused
**Unlike** upload, which proceeds — an outage must not lock a customer out of
their own work, and must not let unverified data move either.

## AC-04
**Given** a tenant session
**When** a restore names another tenant's object
**Then** it fails under row-level security as the restricted role.

---

# STORAGE-016 — Configuration inheritance *(planned)*

## AC-01
**Given** a platform floor, a product policy and a tenant policy
**When** they disagree
**Then** the strictest wins and a tenant can never loosen a security minimum.

## AC-02
**Given** a setting a tenant may not override
**When** a tenant attempts it
**Then** it is refused and audited as an administrative event.

---

# STORAGE-017 — Object integrity at upload

## AC-01
**Given** a browser that computed a SHA-256
**When** the upload is confirmed
**Then** `checksum_sha256` holds the claim
**And** `checksum_verified_at` is set **only** where the provider's own digest agrees
**And** the API response distinguishes the two.
*Test:* the confirmation path; `test_storage.py` digest cases

## AC-02
**Given** a browser where `crypto.subtle` is unavailable or throws
**When** the file is uploaded
**Then** it succeeds with no digest
**Because** the digest is corroborating evidence and refusing the upload would
trade a real capability for a theoretical one.

## AC-03
**Given** a confirmed upload
**When** the audit event is written
**Then** it records whether integrity was `verified`, `claimed` or `none`
**And** never the digest itself.
*Test:* `test_a_storage_event_is_written_to_the_general_audit_table`

## AC-04
**Given** an object whose size does not match its ticket
**Then** the row is removed, the object is left for the sweep, and 409 is returned.

---

# STORAGE-018 — Scan seam and quarantine

## AC-01
**Given** a file whose scan concluded `infected`
**When** a download is requested
**Then** it is refused with 403 before a URL is signed
**And** the refusal is audited as a security event.

## AC-02
**Given** a product with no scanner installed
**When** any file is downloaded
**Then** it succeeds
**Because** every file is `pending`, and refusing `pending` would break the
feature the control protects.

## AC-03
**Given** a scan concluding `infected`
**When** the result is recorded
**Then** the row moves to `quarantined` in the same statement
**And** the object is not deleted.

---

# STORAGE-019 — Reconciliation

## AC-01
**Given** an object with no row and a stale pending row
**When** the sweep runs
**Then** both are reported
**And** neither is deleted
**And** no delete statement is issued at all.
*Test:* `test_an_object_with_no_row_is_reported_and_nothing_is_deleted`

## AC-02
**Given** a listing that did not finish
**Then** the result is partial and reports **no** orphans
**Because** keys it did not read look exactly like keys that are not there.
*Test:* `test_a_partial_listing_reports_no_orphans_at_all`

## AC-03
**Given** a ready row whose object is not in the platform bucket
**Then** it is counted unverifiable, not missing
**Because** the tenant may be on a policy this worker holds no credential for.
*Test:* `test_a_ready_row_whose_object_is_elsewhere_is_unverifiable_not_missing`

## AC-04
**Given** the sweep is not enabled, or has no database or no credentials
**Then** it skips and says which.
*Test:* three skip-path tests in `test_storage_reconcile.py`

---

# STORAGE-020 — Multi-consumer hooks

## AC-01
**Given** two modules registering an interest
**Then** both are offered a matching upload, in a deterministic order.
*Test:* `test_two_hooks_both_register_and_both_are_offered_the_upload`

## AC-02
**Given** a name already registered
**Then** the second registration raises, and the first survives.
*Test:* `test_a_repeated_name_is_refused_rather_than_replacing_the_first`

## AC-03
**Given** a hook that throws after an upload
**Then** the upload is unaffected and the next hook still runs.
*Test:* `test_a_throwing_hook_does_not_become_the_uploads_problem`

---

## Known criteria with no automated test

Recorded rather than left to be discovered, as of 2026-09-16:

| Criterion | Why not covered |
|-----------|-----------------|
| STORAGE-003-AC01 end to end | Needs two signed-in browsers and a bucket; CI has Postgres and no bucket |
| STORAGE-003-AC03 (404 not 403) | No test asserts the choice |
| STORAGE-005-AC02 concurrency | The re-check is asserted by reading the code, not by racing two tickets |
| STORAGE-017-AC01 provider corroboration | Needs a real provider digest; MinIO locally, dev by hand |
