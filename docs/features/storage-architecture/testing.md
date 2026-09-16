# SAG-F1 — Testing

Strategy, the traceability matrix, and — the part worth reading — the gaps.

## Strategy

No new framework. Everything uses what the repository already runs: vitest for
the generator, pytest for Python, `psql` for row-level security, Playwright for
the browser.

| Layer | Where | What it proves |
|-------|-------|----------------|
| Package unit | `python-packages/koras-storage/tests/test_storage.py` | Provider resolution, key layout, signing, listing, digests |
| API unit | `tests/unit/test_storage_audit.py` | Every storage operation records, and no credential-shaped detail can |
| API unit | `tests/unit/test_file_hooks.py` | The registry admits many, refuses a repeat, isolates a failure |
| Worker unit | `tests/unit/test_storage_reconcile.py` | The sweep finds and never deletes; a partial listing invents nothing |
| Isolation | `supabase/tests/050_files_isolation.sql` | One tenant's index never shows, admits or loses another's rows |
| Isolation | `supabase/tests/170_files_governance_isolation.sql` | The governance columns ride the same policies |
| Structural | `generators/create-koras-app/tests/` | Files are generated, gated and imported consistently |
| Browser | `e2e/files.spec.ts` | The page's states at 375 and 1440 |

## How the isolation tests are run

Not as the owner. `migrate.sh` applies every migration, the job creates a
`koras_rls_test` role that is `nologin nobypassrls`, and every assertion runs as
that role. Seeding as the owner proves nothing — the lesson R-032 left behind —
and the suite is itself mutation-tested: dropping `force row level security`
must make it fail, and CI asserts that it does.

## Traceability

| Story | AC | Automated test | Manual test |
|-------|----|----------------|-------------|
| STORAGE-001 | AC-01 | `test_a_listing_is_paged_and_says_when_there_is_more` | — |
| STORAGE-001 | AC-02 | `test_a_multipart_entity_tag_is_absent_rather_than_wrong` | — |
| STORAGE-001 | AC-03 | mypy over a generated project | — |
| STORAGE-002 | AC-01 | row-level security job, three matrix rows | — |
| STORAGE-002 | AC-02 | `170_files_governance_isolation.sql` | — |
| STORAGE-003 | AC-01 | `050_files_isolation.sql` (data only) | `TEST-STORAGE-003-01` |
| STORAGE-003 | AC-02 | `test_signed_urls_name_the_bucket_and_key_and_nothing_else_secret` | `TEST-STORAGE-008-01` |
| STORAGE-003 | AC-03 | **none** | `TEST-STORAGE-003-01` |
| STORAGE-004 | AC-01 | `test_storage.py` resolution cases | — |
| STORAGE-004 | AC-02 | `test_storage.py` unsupported-provider cases | `TEST-STORAGE-004-01` |
| STORAGE-005 | AC-01 | `test_a_refusal_is_recorded_as_firmly_as_a_success` | `TEST-STORAGE-005-01` |
| STORAGE-005 | AC-02 | **none** | `TEST-STORAGE-005-02` |
| STORAGE-008 | AC-01 | signature covers type and length | `TEST-STORAGE-008-01` |
| STORAGE-008 | AC-02 | `test_signed_urls_name_the_bucket_and_key_and_nothing_else_secret` | `TEST-STORAGE-008-01` |
| STORAGE-008 | AC-03 | `test_a_name_that_tries_to_leave_its_prefix_cannot` | — |
| STORAGE-017 | AC-01 | digest cases in `test_storage.py` | `TEST-STORAGE-017-01` |
| STORAGE-017 | AC-02 | **none** | `TEST-STORAGE-017-02` |
| STORAGE-017 | AC-03 | `test_a_storage_event_is_written_to_the_general_audit_table` | — |
| STORAGE-017 | AC-04 | confirmation path | — |
| STORAGE-018 | AC-01 | **none** | `TEST-STORAGE-018-01` (blocked) |
| STORAGE-018 | AC-02 | **none** | `TEST-STORAGE-018-02` |
| STORAGE-018 | AC-03 | `core/file_scan.py` single-statement quarantine | — |
| STORAGE-019 | AC-01 | `test_an_object_with_no_row_is_reported_and_nothing_is_deleted` | `TEST-STORAGE-019-01` |
| STORAGE-019 | AC-02 | `test_a_partial_listing_reports_no_orphans_at_all` | — |
| STORAGE-019 | AC-03 | `test_a_ready_row_whose_object_is_elsewhere_is_unverifiable_not_missing` | `TEST-STORAGE-019-02` |
| STORAGE-019 | AC-04 | three skip-path tests | — |
| STORAGE-020 | AC-01 | `test_two_hooks_both_register_and_both_are_offered_the_upload` | — |
| STORAGE-020 | AC-02 | `test_a_repeated_name_is_refused_rather_than_replacing_the_first` | — |
| STORAGE-020 | AC-03 | `test_a_throwing_hook_does_not_become_the_uploads_problem` | — |

Stories 006, 009–013, 015 and 016 have criteria and no tests, because they have
no code.

## Gaps, stated rather than left to be found

| # | Gap | Consequence |
|---|-----|-------------|
| G1 | **No real upload in CI.** Generator Integration has Postgres and no bucket | The signing, the PUT and the digest are proven against MinIO locally and dev by hand. `FOLLOW_UPS.md` F22 |
| G2 | **No test for 404-not-403** on another tenant's file id | The choice is a deliberate anti-enumeration measure and nothing asserts it |
| G3 | **No concurrency test for the quota** | The second check is asserted by reading the code, not by racing two tickets |
| G4 | **The reconciliation sweep's own audit write is unproven** under the restricted role | It switches from provisioning to a tenant context to insert; no isolation test exercises that path |
| G5 | **No scanner anywhere**, so the quarantine refusal is proven by unit reasoning only | `TEST-STORAGE-018-01` is BLOCKED, not passing |
| G6 | **No manual pass has been executed at all** | Fourteen cases, every verdict blank |
| G7 | **No independent review** — code, architecture, security or privacy | Four gates unmet |

G4 is the one I would close first: it is a small `.sql` test, it covers a writer
that crosses a tenant boundary deliberately, and it is exactly the kind of path
that looks correct and is not.

## What CI actually runs on every push

| Job | Covers |
|-----|--------|
| CI | ruff, mypy, vitest, pytest, build |
| Generator Integration | Generates both profiles at four matrix rows, then lint, typecheck, test, build, Playwright, the RLS suite and its mutation check |
| Security | CodeQL, secret scanning, gitleaks |

The RLS suite is where `00018` and `170` are proven; it reported
`files governance isolation: ok` on 2026-09-16.
