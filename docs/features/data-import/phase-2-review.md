# Data import — the second review, over Phase 1 and Phase 2

Run 2026-09-22, against commit `e20d73b`. Four independent reviewers, one per
seam: the engine, the API and schema, the worker, the frontend. None of them
saw another's report.

**Verdict: BLOCK, from all four.** That is eight for eight across this
repository's independent reviews, and the rate is not going down.

**The headline is not a defect in a feature. It is that Phase 2 has never
worked.** The commit path cannot succeed on its first run, or any run, for any
product. Two reviewers found it separately, from opposite ends — one from the
state table, one from the call sites — and it was confirmed here by executing
the state machine rather than by reading it.

## Why Phase 1's review did not find it

`review.md` records the first review, run 2026-09-19 against `15639ab`. Phase 2
shipped on 2026-09-20, the day after, and no review ran against it. Every gate
in the estate was green over it: the generator's `product-import.test.ts`
asserts the *shape* of the commit — two `session.commit()` calls, a rollback
before every recorded failure, `record_commit` before `fail` — and every one of
those statements is true of code that fails on every run.

That is the same class named in `CLAUDE.md` after FW-HARDEN-001: an assertion
that asks what a contract *says* rather than what it *does*. It is the third
time in this repository that the class has produced a green suite over broken
work, and the second time the independent gate after the work was the only
thing that caught it.

## Findings

| ID | Severity | Summary | Seam |
|----|----------|---------|------|
| IMP2-01 | **Critical** | The commit can never succeed: `begin_commit` has no caller, so the run reaches `record_commit` in a state the machine refuses | worker + store |
| IMP2-02 | **Critical** | The failure path is refused by the same missing edge, so a failed commit records nothing, tells nobody, and strands the run forever | worker |
| IMP2-03 | High | The target's own permission is enforced on four routes of nine; one of the five returns the customer's raw cell values | API |
| IMP2-04 | High | The unconfigured-queue branch of `commit` answers 500 rather than 503, and strands the run | API |
| IMP2-05 | High | "Download every problem" cannot be correct: the API pages by a key it never returns, and the client sends a different number | API + web |
| IMP2-06 | High | The page stops updating the moment somebody confirms an import | web |
| IMP2-07 | High | A `_csv.Error` escapes `ReadRefused` and becomes a 500 on a customer's own file | engine |
| IMP2-08 | High | The error report is quoted but not formula-guarded, and the module that documents the guard does not carry it | engine + web |
| IMP2-09 | High | Re-validating a run within the hour enqueues nothing and answers 202 | API |
| IMP2-10 | High | The outcome of the irreversible action is announced to nobody, and focus is dropped — SET-24 again, four days later | web |
| IMP2-11 | Medium | A state conflict on `PUT /mapping` is a 500 | API |
| IMP2-12 | Medium | `validate` enqueues before it commits the state change — the window `commit` documents avoiding | API |
| IMP2-13 | Medium | The state machine is advisory: no status predicate on the `UPDATE`, no row lock | store |
| IMP2-14 | Medium | Nothing reclaims a stranded run, and `committing` has no way out at all | worker |
| IMP2-15 | Medium | `MAX_SOURCE_BYTES` bounds the transfer, not the memory | API + worker |
| IMP2-16 | Medium | The source file's category is never checked, and reading it through an import writes no audit row | API |
| IMP2-17 | Medium | Nothing stops the product's writer from splitting the atomic unit | worker |
| IMP2-18 | Medium | `float()` accepts `nan`, `inf` and `1e400` as a decimal | engine |
| IMP2-19 | Medium | The parsed date is discarded and the original string is handed on | engine |
| IMP2-20 | Medium | An unmapped match key silently disables duplicate detection | engine |
| IMP2-21 | Medium | A NUL byte passes every check and fails at the database | engine |
| IMP2-22 | Medium | Two foreign-key columns used by regular deletes have no index | schema |
| IMP2-23 | Medium | One `busy` flag for five actions, so Confirm reads "Importing…" during a download | web |
| IMP2-24 | Medium | A stale problem table survives a successful re-check | web |
| IMP2-25 | Medium | `refresh()` discards every error, so a dead session polls forever in silence | web |
| IMP2-26 | Medium | Untranslated technical strings reach the customer | web |
| IMP2-27 | Medium | The e2e suite runs with no API, so three of its four tests cannot fail | web |
| IMP2-28 | Medium | No test exercises the commit's state machine at all | tests |

Fifteen Low findings are carried in the closing section rather than numbered
individually.

---

### IMP2-01 — The commit can never succeed. **Critical.**

`core/imports.py:340` defines the move into `committing`:

```python
async def begin_commit(session: AsyncSession, run: Run) -> None:
    await _advance(session, run, RunState.COMMITTING, started_at=...)
```

`grep -rn "begin_commit" profiles/` returns two hits: that definition and its
`__all__` entry. **Nothing calls it.** The route stops at `request_commit`, and
`tasks/imports.py` never moves the run.

So the run is still `commit_requested` when `record_commit` advances it straight
to `COMMITTED`. Executed rather than read:

```
commit_requested -> committed        may_move=False
commit_requested -> failed           may_move=False
edges out of commit_requested: {'committing', 'cancelled'}
```

The sequence, every time, for every product:

1. `_write` runs the product's writer. The customer's rows are in the session.
2. `record_commit` raises `TransitionRefused`.
3. The bare `except Exception` rolls back. **Every written row is discarded.**
4. `failure` is set to "the records could not be written".

Phase 2's acceptance criterion — a commit that raises partway leaves zero rows —
is met by accident, because every commit leaves zero rows.

**It is not fixable by adding the call alone.** `Run` is a frozen dataclass and
`_advance` never refreshes it, so `begin_commit(session, run)` followed by
`record_commit(session, run)` would still evaluate `require_move` against the
stale `commit_requested`. The snapshot has to be replaced between the two.

### IMP2-02 — The failure path is refused by the same missing edge. **Critical.**

`tasks/imports.py` opens a second transaction after the rollback and calls
`store.fail`, which is `commit_requested → failed`. That edge does not exist
either, so this raises as well — and nothing catches it. It escapes past
`_tell`, so no notification is sent, and `attempts=1` means there is no retry.

The run is then unreclaimable by anything in the codebase: `commit_requested`
has edges only to `committing` and `cancelled`.

This path is reachable independently of IMP2-01, through the two earlier
`failure` assignments — an unknown target, and a target that lost its writer.

The code at the notification site already anticipates this case in a comment,
"the `fail` above may have been refused by the state machine", without handling
it.

### IMP2-03 — The target's own permission is enforced on four routes of nine. **High.**

IMP-06's stated rule was that every route resolving a target checks it. Three
routes were left *not resolving* a target, so the check does not arise:

| Route | Checks the target | What it returns |
|---|---|---|
| `GET /imports/targets` | no | every target's key and field names |
| `GET /imports` | no | every run's columns and mapping |
| `POST /imports` | **yes** | |
| `GET /imports/{id}` | no | one run's columns and mapping |
| `GET /imports/{id}/analysis` | **yes** | |
| `PUT /imports/{id}/mapping` | **yes** | |
| `POST /imports/{id}/validate` | no | triggers work on a gated target |
| `POST /imports/{id}/commit` | **yes** | |
| `GET /imports/{id}/errors` | no | **the raw cell values** |
| `POST /imports/{id}/cancel` | no | cancels another member's run |

A product declares `payroll.employees` behind `payroll.manage`. A member holding
`imports.manage` but not `payroll.manage` is refused by `/analysis` — the route
IMP-06 fixed — and served by `/errors`, which hands back up to 500 rows of
salary values from the same file. They can also cancel the run.

The generator test meant to prevent this cannot fail: it pins the number of
checks at four, and its second assertion compares `_target(` matches against
`_require_target(` matches — a regex that matches the substring inside every
occurrence of the thing it is counting against.

### IMP2-05 — "Download every problem" cannot be correct. **High.**

The store pages the report by the table's primary key:

```sql
where run_id = cast(:id as uuid) and id > :after order by id limit :limit
```

`id` is `bigint generated always as identity` — global across every run and
every tenant. The select does not return it, and `ImportRowErrorView` does not
carry it. The browser therefore sends the only number it has, which is the
**file row number**.

On a fresh database the cursor runs ahead of the ids and the loop stops early:
bad rows are missing from the file the customer is told contains every problem.
With earlier runs in the table the cursor lags and pages repeat: the CSV lists
rows twice. Neither says anything.

The loop's own docstring claims it is "bounded by the number the run itself
recorded rather than by trust in the loop terminating". `errors_total` is never
read there.

This cannot be fixed in the client. The view needs the key, or an opaque cursor.

### IMP2-06 — The page stops updating the moment somebody confirms. **High.**

`ImportPanel` polls on `IN_FLIGHT = new Set(['validating', 'committing'])`. The
commit route returns the run in `commit_requested`; only the worker moves it to
`committing`, later. So the effect returns immediately, no interval is ever
created, and the page never asks again.

An administrator confirms, the card freezes on the request sentence, the worker
writes the rows and finishes, and the page still says it has not started. A
person who assumes it failed clicks Confirm again and gets a 409 rendered as a
red error banner over a successful import.

The panel's own docstring says it "polls the way it already polls a dry run".

### IMP2-07 — A `_csv.Error` escapes `ReadRefused`. **High.**

`_bounded` refuses a **line** over 32 KiB. `csv` bounds a **field**. A quoted
field spanning many short lines is under the line limit on every line and over
the module's 131072-byte field limit in total. Reproduced on Python 3.13.7:

```
longest line: 1003   MAX_CELL: 32768
UNHANDLED _csv.Error : field larger than field limit (131072)
```

Two ordinary ways in: one unterminated double quote anywhere in the file, which
`csv` absorbs to end of file rather than raising; or a legitimate long free-text
cell. `read_header` succeeds first, so the failure lands mid-flow.

The routes catch `ReadRefused` and `MappingRefused` only, so the analysis and
mapping routes answer **500**. The page calls analysis automatically after an
upload, so the customer gets a server error and no way forward. `count_rows`
fails the same way.

`_bounded`'s docstring says it bounds the input "instead" of raising the
process-wide field limit, which is the one thing it does not do.

### IMP2-08 — The error report is quoted but not formula-guarded. **High.**

`reading.py`'s module docstring names the control and says where it lives: the
danger is on the way back out, a spreadsheet opening an error file would
evaluate it, "which is why the writer escapes".

`writing.py` contains no escaping and writes no CSV. The error CSV is built in
the browser, with RFC-4180 quoting and nothing else. Quoting defends the
delimiter; Excel and LibreOffice strip the quotes and then evaluate a leading
`=`, `+`, `-` or `@`.

Both fields that carry it are attacker-chosen: the offending cell, and the
file's own column heading. A cell holding a `HYPERLINK` formula fails its check,
so it is *guaranteed* to reach the report. An operator downloads every problem
and opens it on their own machine, with their own trust settings. The file in
this product most likely to contain hostile text is the one with no guard.

### IMP2-09 — Re-validating within the hour enqueues nothing and answers 202. **High.**

`Enqueued` carries `duplicate` and documents it. A grep for readers of that
field across both templates finds **no caller that reads it** — the two import
routes are the only enqueuers, and both read `simulated` alone.

The queue refuses a deterministic job id while either the job key or the result
key exists, and arq's default result lifetime is an hour. So: a person
validates, the report shows errors, they re-map and press Validate again. The id
`validate:{run_id}` is still held, the enqueue is refused, the route answers 202
and moves the run to `validating` — with no job anywhere. The run sits there
forever.

Re-mapping and re-validating is the ordinary flow for a file with errors.

### IMP2-10 — SET-24, again, four days later. **High.**

The confirm block is gated on `status === 'validated'`. The moment `confirm()`
succeeds the status changes, so the button the person just activated unmounts
and focus falls to `BODY`. The outcome that replaces it is a bare paragraph: not
in a live region, not focused on mount, no `tabIndex`.

A screen-reader user confirms an irreversible write of thousands of records and
receives no signal that it happened — not when it is requested, and not when it
completes.

This is the same defect as SET-24, fixed in `SaveOutcome` on 2026-09-22, in a
different feature. The fix shape already exists in this repository.

---

## The rest

IMP2-11 through IMP2-28 are recorded in the table above with their seam. Each
was verified against the code by the reviewer that raised it; the three that
turn on a race — IMP2-12, IMP2-13 and IMP2-17 — had their ingredients verified
in the installed arq and in the SQL, but were not reproduced.

Fifteen Low findings are carried rather than fixed: a machine key in the target
picker, a download that can abort in Firefox, "Show the problems" having no
pending state, an orphaned file on a failed start, the reader's renamed-column
record dropped at the view, a failed dry run showing no counts,
`target.formats` declared and never enforced, `requested_by` accepting the
empty string, three tests that restate a constant, `writing.py` and `jobs.py`
having no tests at all, a transaction held open across an object fetch, an
indeterminate commit reported as a failure, a failed run announceable as a
success, a refusal-code map covering three codes of five, and a re-mapped run
keeping the previous report.

## The carried findings, with a decision each

Eighteen medium and fifteen low. **None is dismissed**; each is carried with a
reason, and a finding disproved by later evidence is marked disproved rather
than deleted. Status is one of *carried* (real, not fixed), *fixed*, or *disproved*.

| ID | Sev | Finding | Impact if left | Decision | Status |
|----|-----|---------|----------------|----------|--------|
| IMP2-11 | Med | A state conflict on `PUT /mapping` is a 500 | A second tab saving a mapping on a running run gets an opaque error after the file has been fetched and parsed | Fix with the `may_move` guard `validate` already uses | carried |
| IMP2-12 | Med | `validate` enqueues before it commits the state change | A worker can read a run still `mapped` and strand it; low probability, unrecoverable outcome | Swap the two statements; needs the 503 path reworked with it | carried |
| IMP2-13 | Med | The state machine is advisory — no status predicate, no row lock | Two administrators confirming at once both succeed; the duplicate write is stopped only by the queue's lock | Add `where status = :expected` and check the rowcount | carried |
| IMP2-14 | Med | Nothing reclaims a stranded run, and `committing` has no way out | A worker killed mid-commit leaves a run no person and no sweep can move | Needs a reaper sweep; `import_runs_queued_idx` already exists for it and nothing reads it | carried |
| IMP2-15 | Med | `MAX_SOURCE_BYTES` bounds the transfer, not the memory | A 64 MiB file of short rows is ~270 MB resident per request, and analysis is unrated | Stream the parse, or cache the analysis per run | carried |
| IMP2-16 | Med | The source file's category is never checked, and reading it writes no audit row | A member can feed an `exports` file to a run; the read is unlogged while the download path is logged | Check `category = 'imports'` in `check_source`; add the file id to `import.run.started` | carried |
| IMP2-17 | Med | Nothing stops a product's writer splitting the atomic unit | A writer that commits between batches reintroduces the partial import the phase forbids | Wrap the writer in `begin_nested()` so it is detectable | carried |
| IMP2-18 | Med | `float()` accepts `nan`, `inf`, `1e400` as a decimal | `NaN` reaches a numeric column and every later `SUM` over that tenant is `NaN` | Reject non-finite values in `_check_decimal` | carried |
| IMP2-19 | Med | The parsed date is discarded and the original string handed on | The `%d/%m/%Y`-only decision does not survive to the writer, and `_DATE_FORMATS` is not exported | Normalise to ISO in the mapped row | carried |
| IMP2-20 | Med | An unmapped match key silently disables duplicate detection | A `skip_duplicate` or `upsert` run reaches the writer with no key; duplicates or a constraint abort | `resolve` should refuse a mapping omitting a match key for those operations | carried |
| IMP2-21 | Med | A NUL byte passes every check and fails at the database | One NUL in row 40,000 discards all 40,000, after a dry run said the file was clean | Strip or refuse C0 controls in the reader | carried |
| IMP2-22 | Med | Two foreign-key columns used by regular deletes have no index | The nightly retention sweep scans `import_runs` per file purged | Add both indexes in a later migration | carried |
| IMP2-23 | Med | One `busy` flag for five actions | Confirm reads "Importing…" during a download — the page claims an irreversible write is running when none is | Discriminated pending state | carried |
| IMP2-24 | Med | A stale problem table survives a successful re-check | A clean re-check renders the previous run's problems beneath a summary saying there are none | `setProblems(null)` at the top of `check` and `confirm` | carried |
| IMP2-25 | Med | `refresh()` discards every error | An expired session polls forever in silence | Surface the error and stop | carried |
| IMP2-26 | Med | Untranslated technical strings reach the customer | A German customer sees "the bucket answered 403" | Two catalogue keys | carried |
| IMP2-27 | Med | The e2e suite runs with no API, so three of four tests cannot fail | The only browser evidence the feature has proves almost nothing | Move them to the `roundtrip` project, which now has a database | carried |
| IMP2-28 | Med | No test exercises the commit's state machine | — | **Fixed**: `tests/integration/test_import_commit_rls.py`, four cases, each mutation-checked | fixed |

The fifteen low findings are listed in "The rest" above. Two have since been
closed by this cycle's work and are marked here rather than quietly dropped:

| ID | Finding | Status |
|----|---------|--------|
| ENG-08 | `test_terminal_states_go_nowhere` restated a constant | fixed — asserts `next_states(state) == frozenset()` |
| ENG-01 | The generator's target-permission assertion could not fail | fixed — asserts per route by name, and mutation-checked |

## Status

**Implementation complete. Not closed.**

The two critical and the eight high findings are fixed, and each fix has a test
that fails without it. The eighteen medium and fifteen low findings are carried
rather than dismissed, and are listed above with their seam.

What closure waits on is the manual matrix: thirty-six of forty cases have not
been run. Four have — 23 to 26, the commit — and they are recorded in
`testing/manual/manual-test-results.md`.

**One defect was found in the fix for another**, which is worth stating in the
record rather than only in the test. The claim commits its own transaction, and
the worker's tenant context is transaction-local; committing dropped it, so the
re-read of the run the worker had just claimed returned nothing under row-level
security. It does not raise. It was invisible to the state machine, to every
unit test here, and to a type checker, and it reproduced only against a real
PostgreSQL with a role that does not bypass policies.
`tests/integration/test_import_commit_rls.py` is the answer, and
`Generator Integration` runs it against the round trip's database.

## What the four reviewers ruled out

Recorded because a checked-and-clean result is evidence too, and so the next
review does not pay for it again.

- **The mapping allowlist holds.** `resolve` refuses an undeclared field, an
  unknown column, a field mapped twice and a missing required field, and the row
  validator keys its output only from the resolved mapping. No source column
  name and no undeclared field can reach the writer.
- **Cross-tenant isolation holds** on runs, row errors and source files. Both
  tables have row-level security enabled and forced with a tenant predicate, the
  request session declares the tenant per transaction, and another tenant's run
  id returns 404.
- **The scan gate is on every byte-reading path** — analysis, mapping, the dry
  run and the commit all reach bytes through one function that refuses
  `pending`, `skipped` and `infected` before the object is fetched.
- **No double-write through the queue.** The in-progress lock outlives the task
  timeout, the try counter is incremented on every pickup, and `attempts=1` is
  correctly plumbed. A worker killed mid-commit does not re-run it; it strands
  the run instead, which is IMP2-14.
- **The worker's dependencies are declared** and every module it reaches by
  `importlib` is copied into its image. That was the defect class fixed when the
  commit shipped, and it stayed fixed.
- **No SQL injection.** Every caller value is bound; the only interpolated names
  come from the store's own keyword arguments.
- **Three of the four atomicity claims in `architecture.md` are true as
  written.** Two sessions and two commits on the path, a rollback before every
  recorded failure, the notice last and swallowing everything. Only the claim
  that the first transaction records `committed` is false — and it is false
  because the transition is refused.
