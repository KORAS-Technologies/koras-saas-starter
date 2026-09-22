# Data import — manual test results

Against `manual-test-plan.md`. **Four of forty cases have been executed.** Every
other verdict is still blank, and this document says which and why rather than
leaving forty blanks to be counted again.

Opened 2026-09-22, after the second independent review
(`../../phase-2-review.md`) found that the commit path had never worked.

## What was executed, and against what

| # | Case | Verdict | Date |
|---|------|---------|------|
| 23 | Check a clean file, then confirm | **PASS** | 2026-09-22 |
| 24 | Count rows in the target table afterwards | **PASS** | 2026-09-22 |
| 25 | Confirm twice; one copy of the records exists | **PASS** | 2026-09-22 |
| 26 | A writer that raises leaves **zero** rows | **PASS** | 2026-09-22 |

These four were chosen rather than the first four of the plan, because they are
the ones that decide whether the review's critical finding is actually fixed.
Case 26 is the phase's own acceptance criterion.

### The estate

A product generated from the starter at this commit, `--with data_import`, into
a scratchpad; a PostgreSQL 15 in the local docoris stack, with all thirty of the
product's migrations applied and the round-trip seed; and the API's own
`koras_e2e_app` role, which is `nobypassrls`, so every row-level policy applies.

Two things had to be added, because a generated product cannot run these cases:

- **A committable target**, `probe.contacts`, with a real writer. The generated
  product declares none and should not — a target names a table the product
  owns, and the starter owns no domain.
- **A table for it**, `probe_contacts`, with tenant-scoped row-level security.

Both are in `../runs/2026-09-22-01/` and neither is part of the starter. This is
the same shape as F27's TEST-SET-01 blocker — a case that needs a product with a
domain — answered by building the smallest domain that makes the case runnable
rather than by recording it blocked.

### What was real, and the one thing that was not

Real: the worker task, the run store, the state machine, the target's writer,
the transaction, row-level security, and the tenant context. The run is driven
through `commit_run` itself, not through a reimplementation of it.

Stubbed: the object store, which returns the bytes of a real CSV. MinIO is
running locally and could have served it; the bucket is not the property under
test, and every byte the parser sees is the same either way.

Not covered by this run: the HTTP routes, the browser, the queue, and the
notification. Cases 23–26 are the worker's half of those plan rows.

## The results

```
CASE 23  worker returned {'status': 'ok', 'created': 3, 'updated': 0, 'skipped': 0}
CASE 23  run status = 'committed'  error = None
CASE 24  probe_contacts 0 -> 3
CASE 24  rows carrying the run id = 3
CASE 25  second commit returned {'status': 'skipped', 'reason': 'not claimable'}
CASE 25  probe_contacts after replay = 3
CASE 26  worker returned {'status': 'failed', 'reason': 'the records could not be written'}
CASE 26  run status = 'failed'  error = 'the records could not be written'
CASE 26  probe_contacts 3 -> 3  (must be unchanged)
```

Case 26's writer writes two of the three rows and *then* raises. A writer that
raised before writing anything would leave zero rows whatever the transaction
did, and would prove nothing.

## Mutation-checked

The four cases were re-run with the claim removed from the worker — the code
exactly as Phase 2 shipped it:

```
CASE 23  run status = 'failed'  error = 'the records could not be written'
CASE 24  probe_contacts 0 -> 0
FAIL: case 23: run is 'failed', expected 'committed'
FAIL: case 24: 0 rows written, expected 3
```

That is the defect reproduced, and it is what every commit of every product did
between 2026-09-20 and 2026-09-22.

## What this run found that nothing else did

**The first version of the fix was wrong, and only a real database said so.**
The claim commits its own transaction, and the worker's tenant context is set
with `set_config(..., true)` — transaction-local. So the commit ended the
transaction those settings belonged to, and the re-read immediately after ran
with no tenant: row-level security matched nothing, `store.get` answered `None`,
and the worker logged that the run had vanished.

It is not an error and it does not raise. Against the state machine alone, and
against every unit test in the estate, the fix looked correct. The tenant is
declared again after the claim now.

That is the second time in three days that the thing catching a real defect was
an estate the code had to actually run in — the first being the settings form's
server/client boundary, which no suite here could see.

## It is a test now, not a story

`tests/integration/test_import_commit_rls.py` ships in every product generated
with `data_import`, and runs against the round trip's own database in
`Generator Integration`. It skips without `E2E_DATABASE_URL`, which is the same
switch the browser round trip uses and the same reason: a suite that fails on a
laptop with no Postgres is a suite people stop running.

Four cases, and each was verified by mutation — the fix removed, the test red,
the fix restored, the test green:

| Mutation | What it restores | Cases that go red |
|---|---|---|
| The claim removed | Phase 2 exactly as it shipped | 2 of 4 |
| The tenant re-declaration removed | The first attempt at the fix | 3 of 4 |
| `commit_requested → failed` removed | The stranding half | 1 of 4 |

**The third mutation is the one worth reading.** It left the first three cases
green, because their writer fails *after* the claim and `committing → failed`
has always existed. A test for a failure *before* the claim — a target with no
writer — was added for that alone, and it is the only thing in the estate that
would notice the edge disappearing.

## What is not executed

Thirty-six cases. They fall into three groups.

**Cases 1–22, Phase 1.** Nothing blocks them: they need the API, a bucket and a
queue, all of which are available locally, plus a browser. They were not run
because the review's critical finding was in Phase 2 and the hours went there.

**Cases 27–40 other than those above.** The audit assertion, the notification
and its language, the error-report download and its escaping, and the German
pass. Several of these were *changed* by this review's fixes — the report
download's paging, the formula guard, the polling, the focus — so they are the
cases most worth running next, and none of them has been.

**Nothing is permanently blocked.** Unlike F27's TEST-SET-01, every remaining
case here has an estate that could run it.
