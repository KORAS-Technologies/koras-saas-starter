# Data import Phase 1 — review

Run 2026-09-19, against commit `15639ab`, the day Phase 1 shipped. Scope: the
engine (`koras-import`), the run store, the routes, the dry-run job, the two
tables and their policies, and the page.

**Verdict: BLOCK.** One critical finding, two high, three medium. The critical
one is not in the import feature at all — it is what the import feature does to
a sweep that was already there, which is the class of defect a review of the
diff alone would not find.

That makes three for three: both independent reviews of the governance work
returned BLOCK and every finding was real, the settings review returned BLOCK
from both reviewers, and this one does too. The pattern is worth naming rather
than treating each as a surprise — work written and reviewed inside one session
is not reviewed.

## Findings

| ID | Severity | Summary | State |
|----|----------|---------|-------|
| IMP-01 | **Critical** | An import permanently disables object retention for the whole product | **Fixed** |
| IMP-02 | **High** | The whole source file is read into API memory, unbounded, on a route any administrator can call repeatedly | **Fixed** |
| IMP-03 | **High** | `decode()` can never report a replaced character, so a banner the page draws can never appear | **Fixed** |
| IMP-04 | Medium | A comma or dot followed by three digits is parsed silently and is 1000× wrong half the time | **Fixed** |
| IMP-05 | Medium | A state conflict on `validate` answers 500, after the job is already enqueued | **Fixed** |
| IMP-06 | Medium | A target's own permission is enforced on one route of three that resolve a target | **Fixed** |
| IMP-07 | Low | Three smaller things, carried | Open |

---

### IMP-01 — An import permanently disables object retention. **Critical.**

`import_runs.source_file_id` is `references public.files(id) on delete restrict`,
and it is the **only** foreign key onto `public.files` in the whole schema. The
object-retention sweep in `tasks/storage_lifecycle.py` has therefore never had
to cope with a refusal, and does not:

```python
await session.execute(_MARK_PURGED, {"id": row.id})   # status = 'purged', committed
await session.commit()
...
store.delete(row.storage_key)                          # the bytes are gone
...
await session.execute(_DELETE_ROW, {"id": row.id})     # raises ForeignKeyViolation
await session.commit()
```

There is no `try` around `_DELETE_ROW`. So for any file that is an import
source and reaches its retention date:

1. the row is marked `purged` and committed — the index now claims the object is gone;
2. **the object is actually deleted from the bucket**, while a run still points at it;
3. the delete of the row raises, uncaught, and the sweep aborts;
4. every other file due that night is not purged;
5. on the next run `retry_stranded` picks the same row up first, `store.delete`
   succeeds again (S3 deletes are idempotent), and `_DELETE_ROW` raises again.

**The sweep now dies on its first statement, every night, for as long as the
product runs.** No customer file is ever purged again. The first symptom is a
compliance failure, and nothing reports it: the job logs an exception into a
stream nobody reads, and the product's own governance contract goes on
answering that retention is configured.

The `on delete restrict` was chosen for a reason — ADR 0009 says a source file
"is evidence of where rows came from". That reasoning confuses two things. The
run's provenance is its columns, its mapping, its counts, its operation and who
asked; all of that is on the run row and none of it is in the file. The bytes
are the customer's own file and are subject to the same retention as any other
file they uploaded — arguing otherwise means an import is a way to make a file
immortal, which is the opposite of what a retention floor is for.

**Fixed in two places, because either alone leaves the class open.**
`source_file_id` is now nullable with `on delete set null`, so retention reaches
an import source exactly as it reaches anything else and a run whose source has
expired answers through `SourceRefused("import.source.missing")` — a path that
already existed and was already translated in three languages. And
`purge_expired` and `retry_stranded` now treat a row they cannot delete as
stranded and carry on, so the next foreign key onto `files` cannot recreate
this.

ADR 0009 is amended rather than silently contradicted.

### IMP-02 — The source file is read whole, unbounded. **High.**

`core/imports.py:source_bytes` selects `size_bytes` from `public.files` and
**never reads it**. The column was selected for a check nobody wrote, which is
as close to a signed confession as this kind of defect gets. Its docstring says
the read is "bounded by the upload ceiling rather than by hope"; the upload
ceiling is `files.maxUploadSizeMb`, whose default is 5000.

`GET /imports/{id}/analysis` and `PUT /imports/{id}/mapping` both call it, both
are reachable by any member with `imports.manage`, and neither is rate-limited
beyond the shared authenticated limiter. Three concurrent calls against a 4 GB
upload take the API process out. A person who mis-mapped a column and pressed
the button twice is a plausible way to get there by accident.

**Fixed.** `MAX_SOURCE_BYTES` is 64 MiB — comfortably above `max_rows` of
50,000 at any realistic row width, and far below anything that threatens the
process. It is checked in `source_bytes` against the recorded size before the
object is fetched, and again at `POST /imports` so a person is told when they
start rather than after they have mapped forty columns.

### IMP-03 — A replaced character can never be reported. **High.**

`ENCODINGS` ends with `latin-1`, which maps all 256 byte values and therefore
cannot raise. The loop always returns before reaching the `errors="replace"`
fallback, so that line is unreachable and `Decoded.replaced` is **always
`False`**. Confirmed:

```
b'Name\n\x81dam\n'   -> latin-1  replaced = False
bytes(range(256))    -> latin-1  replaced = False
```

The consequences run all the way to the page: `Analysis.replaced` is always
false, so the `imports.replaced` banner — "Some characters in this file could
not be read and were replaced" — can never be shown, in any of the three
languages it was written in. A customer whose export comes back with mangled
names gets no hint at all.

This also survived its own unit test, which is the more useful half of the
finding. `test_a_byte_that_could_not_be_decoded_is_reported_not_hidden`
asserted `found.replaced is True or found.encoding != "utf-8"` — the second
clause is true whenever the first is false, so the assertion could not fail. A
test written as a disjunction over the thing it is checking is not a test.

**Fixed.** `latin-1` is a deliberate last resort rather than a member of the
strict list: the loop tries the strict encodings, and the fallback decodes with
`errors="replace"` and reports it. The test now asserts `replaced is True` and
the encoding separately.

### IMP-04 — An ambiguous decimal is parsed rather than refused. **Medium.**

`_check` for `DECIMAL` does `float(value.replace(",", "."))`. So `1,234` — a US
export meaning one thousand two hundred and thirty-four — becomes `1.234`. The
value is not refused, not flagged, and is wrong by a factor of a thousand. The
same is true in reverse for `1.234` from a German export.

The module already holds the correct rule and applies it to dates three lines
above:

> **There is no `%m/%d/%Y`**: it is indistinguishable from `%d/%m/%Y` for the
> first twelve days of a month, and a date that is silently wrong eleven times
> in twelve is worse than a date that is refused.

A separator followed by exactly three digits, with no other separator present,
is exactly that situation and deserves the same answer.

**Fixed.** Where both separators appear the last one is the decimal point and
the other is thousands, which is unambiguous in every locale. Where one appears
followed by exactly three digits and nothing else, the value is refused with a
new code, `import.error.ambiguous_decimal`, and its own sentence in all three
languages. Everything else parses as before. Phase 1 writes nothing, so the
cost of this today is a preview; the point is that Phase 2 will commit with
this parser.

### IMP-05 — A state conflict on `validate` is a 500. **Medium.**

```python
queued = await jobs.enqueue(...)
if queued.simulated: raise api_error(503, ...)
await store.begin_validation(session, run)   # TransitionRefused, uncaught
```

`TransitionRefused` is a `ValueError` and nothing handles it, so validating a
run that is already `validating` — a double-click, or two tabs — answers 500
with whatever the framework renders. `cancel` catches the same exception and
answers 409; `validate` does not. The job has also already been enqueued by
then, against a run the state machine just refused to move.

**Fixed.** The transition is checked with `may_move` **before** the enqueue, and
a refusal is a 409 carrying `IMPORT_NOT_TRANSITIONABLE`, which already has a
sentence in three languages.

### IMP-06 — A target's own permission is enforced on one route of three. **Medium.**

`_require_target` was added at review time on 2026-09-19 because
`ImportTarget.permission` was declared and enforced nowhere. It went on
`POST /imports` alone. `GET /imports/{id}/analysis` and `PUT /imports/{id}/mapping`
both resolve a target and neither checks it — and `analysis` returns a preview
of the file's rows, so a member holding `imports.manage` but not the target's
own permission can read the contents of an upload the target was meant to gate.

The exposure is small, because the same member can read the file through
`/files`. The inconsistency is the finding: a rule enforced on one of the three
routes that resolve a target is a rule nobody can reason about.

**Fixed.** Every route that resolves a target now checks it.

### IMP-07 — Carried. **Low.**

Three, each recorded rather than fixed, with the reason.

- **`suggest()` shadows fields that normalise alike.** `first_name` and
  `firstname` reduce to the same key and one silently wins. `ImportTarget`
  refuses duplicate field *names* and not duplicate normalised names. No target
  in the estate has such a pair; a `__post_init__` check is the fix and belongs
  with the next target that needs it.
- **A duplicate-row error puts a row number in the `value` column.** `validate`
  sets `value=str(first)` for `import.error.duplicate_in_file`, and the panel
  renders `value` under a heading that says "Value". It should say which row it
  duplicates, in the message rather than in a column that means something else.
  Needs a message with a parameter, which the row-error shape does not carry
  yet.
- **`sniff_delimiter` calls `splitlines()` on the whole text twice** to read the
  first line. With IMP-02's ceiling in place this is 64 MiB twice rather than
  unbounded, so it is now a waste rather than a hazard.

## What this review did not cover

- **The browser.** Nothing here was checked in a running browser; the manual
  plan is `manual-test-plan.md` and every verdict in it is still blank.
- **The policies against a real Postgres.** `320_imports_isolation.sql` passes,
  and it was written by the same session that wrote the policies. An
  independent adversarial pass over the two tables' policies has not been run.
- **Phase 2.** There is no commit path to review.
