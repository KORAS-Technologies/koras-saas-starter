# SAG-F2 — Testing

## Strategy

No new framework: vitest for the generator, pytest for Python, `psql` for
row-level security.

| Layer | Where | What it proves |
|-------|-------|----------------|
| Package unit | `tests/unit/test_audit_actions.py` | The registry refuses duplicates and undeclared actions; classes are right |
| Worker unit | `tests/unit/test_audit_retention.py` | Each class swept at its own age; a bad number deletes nothing |
| API unit | `tests/unit/test_storage_audit.py` | Storage records, and a key-shaped detail cannot be recorded |
| Isolation | `supabase/tests/110_audit_isolation.sql` | Tenant scoping, no rewrite, no tenant delete, and the sweep's bound |
| Structural | `generators/create-koras-app/tests/generation.test.ts` | The table survives `--without reporting` |

## How the isolation test is run

As `koras_rls_test`, a `nologin nobypassrls` role, against a real Postgres, in
every Generator Integration row. Seeding as the owner proves nothing — the R-032
lesson — and the suite is mutation-tested: removing `force row level security`
must make it fail.

## Traceability

| Story | AC | Automated test | Manual test |
|-------|----|----------------|-------------|
| AUDIT-001 | AC-02 | `test_the_object_key_cannot_be_recorded_as_a_detail` | — |
| AUDIT-002 | AC-01 | `test_a_refusal_is_recorded_as_firmly_as_a_success` | `TEST-AUDIT-002-01` |
| AUDIT-002 | AC-02 | `test_the_sink_refuses_an_event_for_another_tenant` | — |
| AUDIT-002 | AC-03 | `test_a_storage_event_is_written_to_the_general_audit_table` | — |
| AUDIT-004 | AC-01 | `generation.test.ts`, without-reporting case | — |
| AUDIT-004 | AC-02 | `110_audit_isolation.sql` | `TEST-AUDIT-004-01` |
| AUDIT-004 | AC-03 | `110_audit_isolation.sql` | `TEST-AUDIT-004-02` |
| AUDIT-004 | AC-04 | `110_audit_isolation.sql` | `TEST-AUDIT-004-02` |
| AUDIT-007 | AC-01 | `test_every_class_is_swept_at_its_own_age_in_one_transaction` | `TEST-AUDIT-007-01` |
| AUDIT-007 | AC-02 | `test_retention_of_nothing_is_refused_for_any_class` | — |
| AUDIT-007 | AC-03 | `test_nothing_is_deleted_when_one_class_is_misconfigured` | — |
| AUDIT-007 | AC-04 | `test_administrative_shares_the_default_and_security_does_not` | — |
| AUDIT-009 | AC-01 | `110_audit_isolation.sql` sweep half | `TEST-AUDIT-007-01` |
| AUDIT-009 | AC-03 | **cannot pass — no hold exists** | — |
| AUDIT-014 | AC-01 | `tests/unit/test_platform_activity.py` | — |
| AUDIT-014 | AC-02 | **none** | `TEST-AUDIT-014-01` |
| AUDIT-016 | AC-01 | `110_audit_isolation.sql` | `TEST-AUDIT-004-02` |
| AUDIT-016 | AC-02 | `110_audit_isolation.sql` | — |
| AUDIT-019 | AC-01 | `test_a_key_that_is_not_dotted_lower_case_is_refused` | — |
| AUDIT-019 | AC-02 | `test_an_action_without_a_summary_is_refused` | — |
| AUDIT-019 | AC-03 | `test_a_duplicate_key_is_refused_where_it_is_a_traceback` | — |
| AUDIT-019 | AC-04 | `test_recording_an_undeclared_action_fails_instead_of_writing_a_row` | — |
| AUDIT-019 | AC-05 | `test_iteration_is_ordered_so_two_runs_of_one_build_agree` | — |
| AUDIT-020 | AC-01 | `test_a_refusal_is_security_and_an_ordinary_read_is_activity` | `TEST-AUDIT-020-01` |
| AUDIT-020 | AC-02 | row-level security job applies `00019` | — |
| AUDIT-021 | AC-01 | `test_a_storage_event_is_written_to_the_general_audit_table` | `TEST-AUDIT-021-01` |
| AUDIT-021 | AC-02 | `test_a_refusal_is_recorded_as_firmly_as_a_success` | `TEST-AUDIT-021-02` |
| AUDIT-021 | AC-03 | `test_the_object_key_cannot_be_recorded_as_a_detail` | — |

Stories 005, 006, 008, 010, 011, 012, 013, 015 and 018 have criteria and no
tests, because they have no code.

## Gaps

| # | Gap | Consequence |
|---|-----|-------------|
| A1 | **The reconciliation sweep's cross-context insert is unproven** | It leaves the provisioning context to write as a tenant. No isolation test exercises that writer under the restricted role, and it is exactly the kind of path that looks right and is not |
| A2 | **No isolation test for `00019`'s column** | Nothing asserts a tenant cannot rewrite `classification` to shorten its own retention |
| A3 | AUDIT-009-AC03 cannot pass | No hold exists; the sweep would delete a record under investigation |
| A4 | **No test that a customer token is refused** on the private contract | The refusal is asserted by reading `require_platform_machine` |
| A5 | **No manual pass has been executed** | Eleven cases, every verdict blank |
| A6 | **No independent review** — code, architecture, security or privacy | Four gates unmet |
| A7 | **No alert if the sweep stops** | The table grows and only the log notices |

**A1 and A2 are the two to close first.** Both are small `.sql` tests, both
cover a boundary that was crossed deliberately, and both are cheaper now than
after something depends on the behaviour being right.

## What CI runs

CI (ruff, mypy, vitest, pytest, build), Generator Integration (four matrix rows,
then the RLS suite and its mutation check), and Security (CodeQL, secret
scanning, gitleaks). Migration `00019` is proven by the RLS job; it applied
cleanly on 2026-09-16.
