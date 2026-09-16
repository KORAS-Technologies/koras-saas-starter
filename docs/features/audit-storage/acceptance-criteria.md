# SAG-F2 — Acceptance criteria

Each names the automated test that asserts it, or says none does. Criteria for
stories already built were written on 2026-09-16 against existing behaviour and
describe rather than constrain it.

---

# AUDIT-001 — Canonical audit event model

## AC-01
**Given** any module in either profile
**When** it records an event
**Then** the same envelope is used
**And** action, actor, tenant, target type, target id and outcome are all required.

## AC-02
**Given** a detail whose key contains `token`, `secret`, `password`, `key`,
`credential` or `authorization`
**When** the event is constructed
**Then** it raises
**And** nothing is masked or silently dropped.
*Test:* `test_the_object_key_cannot_be_recorded_as_a_detail`

## AC-03
**Given** an outcome
**Then** it is one of `ok`, `denied`, `failed`, `pending` and nothing else.

---

# AUDIT-002 — Audit event publisher

## AC-01
**Given** a route that emits events and then refuses the request
**When** it flushes
**Then** the events are written
**Because** a refusal is as much a fact as a success.
*Test:* `test_a_refusal_is_recorded_as_firmly_as_a_success`

## AC-02
**Given** a sink bound to tenant A
**When** an event for tenant B is emitted
**Then** it raises, and is not silently dropped.
*Test:* `test_the_sink_refuses_an_event_for_another_tenant`

## AC-03
**Given** a flush that commits
**Then** the tenant is rebound afterwards
**Because** the commit drops the transaction-local setting, and every later
query on that session would match nothing.
*Test:* `test_a_storage_event_is_written_to_the_general_audit_table`

---

# AUDIT-004 — Tenant-isolated audit storage

## AC-01
**Given** a product generated `--without reporting`
**Then** `audit_events`, the sink, the sweep, the setting and the isolation test
are all present.
*Test:* `generation.test.ts`, the without-reporting case

## AC-02
**Given** two tenants with rows
**When** tenant A reads as the restricted role
**Then** only A's rows are visible.
*Test:* `supabase/tests/110_audit_isolation.sql`

## AC-03
**Given** any caller at all, including the provisioning context
**When** an update is attempted on any row
**Then** it is refused
**Because** an audit row that can be edited is not an audit row.
*Test:* `110_audit_isolation.sql`

## AC-04
**Given** a tenant session
**When** a delete is attempted
**Then** nothing is deleted; only the sweep on the provisioning context may.
*Test:* `110_audit_isolation.sql`

---

# AUDIT-007 — Audit retention policies

## AC-01
**Given** an activity row older than 90 days and a security row older than 90
and younger than 1095
**When** the sweep runs
**Then** the activity row goes and the security row stays.
*Test:* `test_every_class_is_swept_at_its_own_age_in_one_transaction`

## AC-02
**Given** any class configured below one day
**When** the sweep runs
**Then** it raises
**Because** retention of nothing is a wipe.
*Test:* `test_retention_of_nothing_is_refused_for_any_class`

## AC-03
**Given** one class misconfigured and three correct
**When** the sweep runs
**Then** **nothing at all is deleted**
**Because** the guard runs over every class before the first delete.
*Test:* `test_nothing_is_deleted_when_one_class_is_misconfigured`

## AC-04
**Given** the four classes
**Then** administrative shares the audit default, and security is longest.
*Test:* `test_administrative_shares_the_default_and_security_does_not`

---

# AUDIT-009 — Audit purge

## AC-01
**Given** rows past their class retention
**When** the nightly sweep runs on the provisioning context
**Then** they are removed and the count is logged per class.

## AC-02
**Given** a sweep interrupted after two of four classes
**Then** the table is consistent with itself
**Because** all four deletes share one transaction.

## AC-03
**Given** a row under an active legal hold
**When** the sweep runs
**Then** the row survives.
*Status:* **cannot pass. No hold exists as of 2026-09-16, so the sweep has
nothing to check. AUDIT-010 blocks AUDIT-009 being called finished.**

---

# AUDIT-005 — Audit search *(planned)*

## AC-01
**Given** an administrator of tenant A
**When** they search their audit history
**Then** only A's rows are returned
**And** the query is served from an index, not a sequential scan.

## AC-02
**Given** a row id belonging to tenant B
**When** A requests it directly
**Then** 404, not 403, so list and URL agree and existence is not confirmed.

## AC-03
**Given** a member without the security permission
**When** they search
**Then** security-classified rows are absent from the result, not redacted in it.

## AC-04
**Given** a result set larger than a page
**Then** it is paged, and no unbounded query is issued.

---

# AUDIT-006 — Audit filtering *(planned)*

## AC-01
**Given** a filter the report does not declare
**Then** the request is refused with 422.

## AC-02
**Given** any filter value
**Then** it reaches the query only as a bound parameter, and there is no
free-text filter at all.

---

# AUDIT-008 — Audit archival *(planned)*

## AC-01
**Given** a row past its archive threshold and inside its retention
**When** the archive step runs
**Then** it is written to the archive destination before being removed from the
hot table
**And** the transition is audited.

## AC-02
**Given** an archive destination that is unreachable
**Then** nothing is removed from the hot table.

---

# AUDIT-010 — Legal hold *(planned)*

## AC-01
**Given** a hold covering a scope
**When** the purge sweep runs
**Then** covered rows survive past their retention
**And** the skip is recorded.

## AC-02
**Given** a hold
**When** it is placed or lifted
**Then** both are audited as administrative events with who requested and who
approved.

## AC-03
**Given** a member who is not an owner or administrator
**When** they attempt to lift a hold
**Then** it is refused
**Because** lifting is what makes a purge possible again.

## AC-04
**Given** a tenant session
**When** another tenant's hold is targeted
**Then** nothing is touched.
*Precedent:* the equivalent for objects is already proven in
`170_files_governance_isolation.sql`

---

# AUDIT-011 — Audit export *(planned)*

## AC-01
**Given** an administrator with the export entitlement and a resolved plan
**When** 50,000 rows are exported
**Then** the API answers 202 with an export id
**And** the artifact becomes available
**And** it expires.

## AC-02
**Given** an export
**Then** requester, scope, filters, timestamp, status and artifact are recorded
**And** the rows themselves are not recorded in the audit of the export.

## AC-03
**Given** an unresolved entitlement plan
**Then** the export is refused
**Because** a download leaves the product.

## AC-04
**Given** CSV, JSON and NDJSON
**Then** each is offered with its correct media type and an attachment
disposition.

---

# AUDIT-014 — Control Plane audit contract

## AC-01
**Given** the platform's machine identity
**When** it reads the activity aggregate
**Then** it receives counts per tenant, day, action and outcome
**And** no actor ids, no target ids and no details.

## AC-02
**Given** a customer token
**When** it is presented to the private contract
**Then** it is refused.

---

# AUDIT-015 — Audit RBAC *(planned)*

## AC-01
**Given** `audit.view` added to the catalogue
**Then** it exists in **both** the TypeScript and Python mirrors, in one commit,
or the structural test fails.

## AC-02
**Given** a member with `audit.view` but not the security permission
**Then** security-classified rows are not returned.

---

# AUDIT-016 — Audit integrity

## AC-01
**Given** any principal the policies apply to
**When** an update is attempted
**Then** it is refused: there is no update policy for anyone.
*Test:* `110_audit_isolation.sql`

## AC-02
**Given** the sweep
**Then** it is the only deleter, and only on the provisioning context.
*Test:* `110_audit_isolation.sql`

---

# AUDIT-019 — Audit action registry

## AC-01
**Given** a key that is not dotted lower-case
**Then** construction raises.
*Test:* `test_a_key_that_is_not_dotted_lower_case_is_refused`

## AC-02
**Given** an action with no summary
**Then** construction raises.
*Test:* `test_an_action_without_a_summary_is_refused`

## AC-03
**Given** a key already registered
**Then** the second registration raises and the first survives.
*Test:* `test_a_duplicate_key_is_refused_where_it_is_a_traceback`

## AC-04
**Given** an action nobody declared
**When** it is recorded
**Then** it raises, and **no row is written**
**Because** a default class would mean a security event swept on the activity
schedule.
*Test:* `test_recording_an_undeclared_action_fails_instead_of_writing_a_row`

## AC-05
**Given** two runs of one build
**Then** iteration order is the same.
*Test:* `test_iteration_is_ordered_so_two_runs_of_one_build_agree`

---

# AUDIT-020 — Classification

## AC-01
**Given** any recorded event
**Then** its class comes from the registry and never from the caller.
*Test:* `test_a_refusal_is_security_and_an_ordinary_read_is_activity`

## AC-02
**Given** migration `00019`
**Then** rows written before it default to `audit`, and none is reclassified
retrospectively.

## AC-03
**Given** the sweep's delete
**Then** it is served by an index on class and time together.

---

# AUDIT-021 — Storage operations recorded

## AC-01
**Given** a successful upload
**Then** exactly one `storage.object.uploaded` row exists, carrying size and
content type
**And** no detail key contains a credential-shaped word.
*Test:* `test_a_storage_event_is_written_to_the_general_audit_table`

## AC-02
**Given** an upload refused for quota or entitlement
**Then** a `storage.upload.refused` row exists with outcome `denied`.
*Test:* `test_a_refusal_is_recorded_as_firmly_as_a_success`

## AC-03
**Given** any storage event
**Then** `file_id` identifies the target and `storage_key` appears nowhere.

---

## Criteria with no automated test

| Criterion | Why |
|-----------|-----|
| AUDIT-009-AC03 | Cannot pass; no hold exists |
| AUDIT-005, 006, 008, 010, 011, 015 | No code |
| AUDIT-014-AC02 | The refusal of a customer token on the private contract is not asserted by a test |
| The reconciliation sweep's cross-context insert | **Gap.** No isolation test exercises that writer |
