# Feature status

Planner tracking for every feature in the catalogue. Status vocabulary is
`docs/features/README.md`. Last reviewed 2026-09-19.

It covered only Storage & Audit Governance until 2026-09-19, which is why the
SAG sections carry story identifiers and the settings section does not: that
work was run as eleven phases against a written brief rather than decomposed
into stories, and inventing story numbers for it after the fact would make the
two halves of this file look more alike than they are.

## SAG-F1 — Storage Architecture & Data Protection

| Story | Title | Class | Status |
|-------|-------|-------|--------|
| STORAGE-001 | Storage provider abstraction | EXTEND | Built |
| STORAGE-002 | Storage metadata registry | EXTEND | Built |
| STORAGE-003 | Tenant-isolated object storage | EXISTING | Built |
| STORAGE-004 | Configurable storage providers | EXISTING | Built |
| STORAGE-005 | Storage quotas | EXTEND | Built |
| STORAGE-006 | Object lifecycle | NEW | Built — purge and retention; ARCHIVE still blocked |
| STORAGE-007 | File versioning | NOT REQUIRED | Closed |
| STORAGE-008 | Secure signed URLs | EXISTING | Built |
| STORAGE-009 | Daily backup | NEW | **Built 2026-09-16** |
| STORAGE-010 | Cross-provider backup | NEW | **Built 2026-09-16** — the settings already promised it |
| STORAGE-011 | Backup integrity verification | NEW | **Built 2026-09-16** |
| STORAGE-012 | Object restore | NEW | **Built 2026-09-16** — permission and two people, no entitlement |
| STORAGE-013 | Snapshot restore | NEW | Not started — operator work with a runbook, not a button |
| STORAGE-014 | Storage usage metrics | NOT REQUIRED | Closed — no metric API |
| STORAGE-015 | Storage administration contracts | NEW | Built — `GET /governance` |
| STORAGE-016 | Storage configuration inheritance | NEW | Built — tenant may lengthen only |
| STORAGE-017 | Object integrity at upload | NEW | Built |
| STORAGE-018 | Malware scan seam and quarantine | NEW | Built |
| STORAGE-019 | Bucket/index reconciliation | NEW | Built |
| STORAGE-020 | Multi-consumer upload hooks | EXTEND | Built |

**14 built · 1 planned · 3 blocked · 2 closed**

## SAG-F2 — Audit Storage, Retention & Archival

| Story | Title | Class | Status |
|-------|-------|-------|--------|
| AUDIT-001 | Canonical audit event model | EXISTING | Built |
| AUDIT-002 | Audit event publisher | EXISTING | Built |
| AUDIT-003 | Audit ingestion | NOT REQUIRED | Closed — synchronous write is better here |
| AUDIT-004 | Tenant-isolated audit storage | EXTEND | Built |
| AUDIT-005 | Audit search | NEW | Built |
| AUDIT-006 | Audit filtering | NEW | Built |
| AUDIT-007 | Audit retention policies | EXTEND | Built |
| AUDIT-008 | Audit archival | NEW | Planned |
| AUDIT-009 | Audit purge | EXTEND | Built — hold-aware since 2026-09-16 |
| AUDIT-010 | Legal / compliance hold | NEW | Built |
| AUDIT-011 | Audit export | NEW | Built |
| AUDIT-012 | Audit export jobs | EXTEND | Built |
| AUDIT-013 | Customer audit viewer contract | NEW | Built — the page and its e2e suite |
| AUDIT-014 | Control Plane audit contract | EXISTING | Built |
| AUDIT-015 | Audit RBAC | EXTEND | Built — `audit.view`, and the security class needs a manager |
| AUDIT-016 | Audit integrity | EXISTING | Built |
| AUDIT-017 | Audit observability | NOT REQUIRED | Closed — no metric API |
| AUDIT-018 | Audit configuration inheritance | NEW | Built |
| AUDIT-019 | Audit action registry | NEW | Built |
| AUDIT-020 | Audit event classification | NEW | Built |
| AUDIT-021 | Storage operations recorded | NEW | Built |

**18 built · 0 planned · 0 blocked · 3 closed**

## Blockers, and who owns them

| Blocker | Blocks | Owner |
|---------|--------|-------|
| Nothing provisions a bucket | AUDIT-008 | Answered 2026-09-16 for backup: a manual step, as `STORAGE_BUCKET` already is. The archive destination is still nobody's |
| No entitlement codes in the platform catalogue | STORAGE-012; audit export is gated by permission alone | Control Plane work, governed by F3/F2b |
| ~~Everything shipped into the foundation~~ | ~~every story~~ | Closed 2026-09-16: `audit_governance` and `storage_governance` are declared, both on by default |
| No metric API in the repository | STORAGE-014, AUDIT-017 | Open framework decision |
| The two capabilities are undeclared | Every gated surface | Generator work; both off by default when declared |

## Definition of Done — where both features stand

| Condition | SAG-F1 | SAG-F2 |
|-----------|--------|--------|
| Stories done or closed with a reason | partial | partial |
| Automated tests pass, evidenced | yes, for built stories | yes, for built stories |
| Tenant isolation proven as the restricted role | yes — fourteen suites, mutation-tested | yes — the same |
| Independent code review | **no** | **no** |
| Security review | **no** | **no** |
| Privacy and compliance review | **no** | **no** |
| Manual QA executed with evidence | **no** — 14 cases, all blank | **no** — 11 cases, all blank |
| Documentation updated | yes | yes |
| `final-acceptance` READY | **no** | **no** |

**Neither feature is Done, and neither is close to it.** The gap is not code; it
is that nothing independent has reviewed the code, and nobody has run the
software against a real environment and written down what happened.

## Settings & Preferences Framework

Feature directory `docs/features/settings-framework/`. As built:
`docs/SETTINGS_ARCHITECTURE.md`. Decision record
`docs/adr/0007-koras-settings-framework.md`.

| Phase | What it delivered | Status |
|-------|-------------------|--------|
| 1 | Audit, architecture, implementation plan, ADR | Built |
| 2 | `koras-settings` — definitions, registry, coercion, resolver | Built |
| 3 | Three tables, the snapshot, three isolation suites | Built |
| 4 | The catalogue: 32 definitions in seven categories | Built |
| 5 | The store and the eight product routes | Built |
| 6 | The provider, the form, the field renderers | Built |
| 7 | The two customer pages, i18n in three languages | Built |
| 8 | The Control Plane's half, against an extended contract | Built |
| 9 | The shop: the sync, and a page with enough rows to page | Built |
| 10 | Verification across all three repositories | Built |
| 11 | As-built documentation, sync matrix, manual test plan | Built |

**Status: Part built, not Done.** Every phase shipped and every automated check
passes. It is not `Done`, and the two reasons were worth naming rather than
leaving in a table:

1. **No manual pass has been run.** `manual-test-plan.md` has fifteen cases and
   fifteen blank verdicts as of 2026-09-19. A blank verdict is not a pass.
2. **No independent review.** Eleven phases across three repositories,
   including three new tables with row-level security, a check constraint that
   refuses secrets, and a platform write route that needed an ADR to justify
   its direction — none of it has had eyes other than the ones that wrote it.

**Both were addressed on 2026-09-19 and 2026-09-21, and it is still not Done.**
Reason 2 closed first: the review ran on 2026-09-19 and returned BLOCK from
both reviewers — twenty-one *numbered* findings, four fixed the same day,
seventeen carried by number, **plus an eighteenth** the review named in prose
rather than in its table and the closure cycle numbered SET-22. The carried set
is therefore eighteen, SET-05 to SET-22, which is what the register
enumerates. `review.md` is that record.

The F27 closure cycle then ran on 2026-09-21 and did three things.

**It reconciled all eighteen carried findings against a running product**, in
`finding-matrix.md`: eleven reproduced by probe, three by reading, one
(**SET-21**) did **not** reproduce as written — the worker's sweeps do declare
the provisioning context, so the comment the review called wrong is accurate —
and one had no behaviour to run. Nothing was marked fixed because code looked
as though it addressed it.

**It fixed the four High findings plus SET-23**: SET-05, SET-06, SET-07,
SET-22 and the two accessibility settings that were offered and honoured by
nothing. No schema change, no migration, no API contract widened.

**And it executed eleven of the fifteen manual cases** — nine by 2026-09-21
against a real PostgreSQL with the product's own migrations and its own API,
and two more on 2026-09-22 in a live sitting against the deployed dev product,
including all three Critical cases that could run — TEST-SET-02, an existing organisation did
not follow a later platform change; TEST-SET-03, the provenance of the copy is
recorded; and TEST-SET-13, the locale migration carried every value it was
given. `testing/manual/manual-test-results.md` is the record.

**Twelve of fifteen now pass, and three remain — none of them code.**
TEST-SET-14 ran on 2026-09-22 and FAILED on one of its four sub-claims:
**saving lost focus to `BODY`**, because the save is a server-side redirect,
and the "Saved." confirmation sat in a `role="status"` region present at
document load rather than inserted as a change, so it might never have been
announced. That was **SET-24**.

It was fixed the same day. A shared `SaveOutcome` client component focuses the
confirmation on mount, which closes the announcement without depending on
live-region semantics — a screen reader reads what it lands on. Verified in a
browser against a real API and database, and the assertion mutation-checked:
remove the `focus()` call and it turns red.

The other three are BLOCKED, and they are not the same kind of blocked.

**TEST-SET-01 is permanently blocked, decided 2026-09-22.** It needs a product
page rendering the shared data table over enough rows to page; the estate no
longer contains one. Accepted with the reason recorded and with the trigger
that would let it run again — any product growing such a page. Giving the
generated product one was considered and declined: inventing a page so a test
has somewhere to live is the wrong way round. Most of the case is proven
anyway, on a deployed product and in the browser — the value is chosen,
stored, resolved, persisted and private to its owner, and the shared table
does read `grid.pageSize`. What is unproven is the seam between them.

**TEST-SET-04 and TEST-SET-10 are blocked on availability, not possibility** —
one plain-`member` account and the Control Plane console. TEST-SET-04's
security half is already proven at the API; only the on-page notice is
unseen.

**The live sitting closed TEST-SET-11 and TEST-SET-12.** TEST-SET-11 is the
one that demonstrates the SET-05 correction: one field changed in a
four-field category produced exactly one audit entry, measured as a
before/after difference rather than by looking for a key in the page — the
first attempt was misled that way by an entry an earlier, unfixed save had
written.

**And it found a live defect outside F27.** TEST-SET-01's blocker used to be
"no product page uses the shared data table". `koras-e2e-shop` has one, and
on deployed dev on 2026-09-22 `/dashboard/orders` **returned HTTP 500** while
every other dashboard page answered 200 — so on that date the page that makes
`grid.pageSize` observable could not be observed. That is the shop's own
orders feature, not the settings framework, and it is recorded rather than
fixed under F27.

**TEST-SET-13 was one of them until 2026-09-22**, recorded as permanently
unrunnable because it needs a database on the pre-settings-framework schema
and every one built for that cycle started empty. That was true of every
database *built for the cycle* and false of the estate: `koras-e2e-shop`'s
local PostgreSQL still sat eighteen migrations back, at `00017`. It passed.
The lesson is narrower than "check harder" — a case blocked on *history*
expires silently, and this one had days left.

**The most valuable unexecuted case is TEST-SET-11**, which is the one that
would have demonstrated the SET-05 correction by reading the audit trail after
a save. What stands in for it is a structural assertion that the mechanism is
present — which asserts what the code says rather than what it does, and is the
weaker kind of evidence this repository has been caught by twice.

### Five settings that resolve and do nothing

`grid.allowColumnResize`, `grid.allowColumnReorder`, `grid.rememberFilters`,
`grid.rememberSort` and `grid.rememberColumns` are registered, resolvable,
scoped, audited and **not drawn on any page**, because the shared table does not
honour them. They are in the brief's catalogue, so they are in the registry;
they are marked `surfaced=False` so that nobody is offered a control that
changes nothing.

That is a deliberate half-measure and it is the largest outstanding piece of
this feature. Either the table learns to honour them or they leave the
catalogue; leaving them registered and invisible indefinitely is how a catalogue
stops describing the product.

**Three of the five closed on 2026-09-19.** The shared table learned column
resizing, column reordering and remembering an arrangement, so
`grid.allowColumnResize`, `grid.allowColumnReorder` and `grid.rememberColumns`
are honoured and offered again. The same change gave the table a server-paging
seam, which is IMPORT-GAP-006 from the other side — one component, two features
blocked on it, built once rather than by either alone.

`grid.rememberFilters` and `grid.rememberSort` remain hidden, with a sharper
reason than before: the table has no filter and no sort, so they describe
persistence of state it does not own.

**The list is six rather than four since 2026-09-21**, and the two that joined
it are the same defect found a third time. `accessibility.reducedMotion` and
`accessibility.fontScale` were offered, translated into three languages, drawn
on the preferences page and read by nothing — SET-23, found by G7 R2 and closed
by F27. The heading above says five and is kept: it was true when it was
written, and the count that moves is the one in `product-settings.test.ts`,
which asserts the hidden list by name and would go red if either were offered
again without being wired.

### What has no automated proof

**Less, since 2026-09-20.** The round-trip harness runs the API against a real
database, and `e2e/roundtrip/settings.spec.ts` now covers the first case of the
manual plan — a person changes their page size, it survives a reload, and it is
not what a colleague sees. Building it found that this page threw on every
product whose API answered, because `resetTo` was a closure crossing into a
client component; PLAT-DEF-008.

What is still unproven is everything a person judges rather than asserts.
The sentence below was true until that day and is kept for the record:

> The round trip. Changing a setting and watching a table repaginate needs an API,
> a database and rows; the e2e harness starts the web application alone. Sixteen
browser checks cover routing, refusal and degraded rendering at 1440 and 375,
and none of them covers the thing the feature is for. That is case TEST-SET-01
in the manual plan, and it is first for that reason.

## Notification and communication framework

Phases 0 and 1 shipped 2026-09-19; **Phase 2 the same day**. Stories are
`NOTIF-*` in `docs/platform/execution/CAT-01-notifications.md`.

| Piece | Phase | Status |
|-------|-------|--------|
| The `notifications` table, four policies, an isolation suite | 1 | **Built** |
| Feed routes, bell, drawer, notification centre | 1 | **Built** |
| Toast and banner primitives | 1 | **Built** — migrating the ~30 hand-rolled alert regions stays out of scope |
| A channel seam, with email as the first adapter | 2 | **Built** — `core/dispatch.py` |
| A recipient resolver taking a rule | 2 | **Built** — `core/recipients.py`, `Audience` |
| `core/notify.py` onto the dispatch point | 2 | **Built** — the assistant's notice composes nothing and sends nothing |
| `notifications.emailEnabled` honoured and surfaced | 2 | **Built**, narrowed to organisation scope |
| The recipient's own language | 2 | **Built** for members; an address the platform gave has no resolvable language |
| A template registry | 2 | **Built narrower** — a template is a function registered beside its kind; one producer does not justify a registry |
| `notifications.digestFrequency` | 4 | Not started — the outbox it needed exists now, so this is unblocked rather than waiting |
| Outbox, delivery log, retry | 3 | **Built 2026-09-20** — `notification_outbox`, claimed with `skip locked`, five attempts then `abandoned` with the reason on the row |
| Escalation when a critical notice is unacknowledged | 3 | Not built — nothing in the product has an acknowledgement; a feed row is read or unread, which is a different claim |

### The review

An independent review of the dispatch seam and the table seam ran on
2026-09-20 and returned **BLOCK**: two high, three medium, one low, all
fixed. `docs/features/notifications/review.md` is the record and DISP-01 to
TBL-03 are rows in `docs/platform/gap-defect-register.md`.

Neither seam was wrong about what it decided; both were wrong about what
they cost, and one of the table's two new controls did not visibly work.
The dispatch point made about five database round trips per recipient on
the request path, and a resized column could not be made narrower because
the table's layout was `auto`. Both classes were invisible to every
assertion either seam shipped with, because those all ask what was decided
rather than what it cost or whether it took effect.

That is four BLOCKs from four independent reviews here. The rate is not
going down.

### What has no automated proof

A notification arriving. The unit suite proves the seam decides correctly and
the browser suite proves the bell and the drawer render; nothing exercises a
producer through a real database to a real inbox. No mail has been sent by
this path from a deployed product.

## Data import and migration framework

Phases 1 and 2 of four, shipped 2026-09-19 and 2026-09-20. Stories are
`IMPORT-US-*` in `docs/platform/execution/CAT-02-data-import.md`.

| Story | Title | Phase | Status |
|-------|-------|-------|--------|
| IMPORT-US-017 | Declare what may be imported without touching the engine | 0 | **Built** — `ImportTarget`, `TargetRegistry`, and an empty product-owned list |
| IMPORT-US-001 | Upload a spreadsheet of existing records | 1 | **Built** — an ordinary `/files` ticket on the `imports` shelf |
| IMPORT-US-002 | Map my columns to the product's fields | 1 | **Built** |
| IMPORT-US-003 | Be told at mapping time that a required column is missing, by name | 1 | **Built** — a 422 naming the field, from the mapping route |
| IMPORT-US-004 | A dry run that writes nothing | 1 | **Built** — and asserted structurally, not just by behaviour |
| IMPORT-US-005 | See what the first rows will look like | 1 | **Built** — a bounded head of 200 rows, in a plain table rather than the shared one |
| IMPORT-US-015 | A member without the permission is refused | 1 | **Built** — hidden in the sidebar, refused on the route |
| IMPORT-US-006 | Every problem reported in one pass | 2 | **Built early** — `validate` makes one pass and reports every problem in every row, including in-file duplicates |
| IMPORT-US-007 | Download a file naming every bad row | 2 | **Built 2026-09-20** — `allErrors` pages the report to exhaustion and the panel writes a CSV; not the plan's annotated-source artefact, and the difference is recorded |
| IMPORT-US-008 | Choose whether a duplicate is skipped or updated | 2 | **Built 2026-09-20** — the operation reaches the product's writer, which is the only thing that knows how to look a record up |
| IMPORT-US-009 | A commit that either fully happens or does not | 2 | **Built 2026-09-20** — one transaction for the rows and the run's state, a second for the failure after it rolls back, and `attempts=1` |
| IMPORT-US-010 | See my past imports and what each did | 2 | **Built 2026-09-20** — the history renders and a committed run says what it wrote. No progress while it runs, deliberately |
| IMPORT-US-016 | Every import attributable and audited | 2 | **Built by halves 2026-09-20** — three actions registered and emitted from the request; the outcome is the run row rather than a fourth action, because auditing from the worker means the API's whole configuration surface in the worker |
| IMPORT-US-018 | Be told when a long import finishes | 2 | **Built 2026-09-20** — the outbox's second producer, through the one dispatch point. In-app only: a worker has no token, so a subject has no address |
| IMPORT-US-011 | Save a mapping and reuse it | 3 | Not started |
| IMPORT-US-012 | Cancel a running import | 3 | Part built — `cancel` refuses a commit in flight by state, and now there is one. Stopping a commit mid-transaction is not offered and will not be |
| IMPORT-US-013 | Retry a failed import without losing its history | 3 | Not started |
| IMPORT-US-014 | A large file works | 4 | Not started — bounded and **refused** rather than truncated, which is the rule audit exports follow |

### The review

An independent review ran on 2026-09-19, the day Phase 1 shipped, and
returned **BLOCK**: one critical finding, two high, three medium, three low.
All six of the first three grades are fixed; the three low ones are carried.
`docs/features/data-import/review.md` is the record and IMP-01 to IMP-07 are
rows in `docs/platform/gap-defect-register.md`.

The critical one was not in the import feature. `import_runs` was the only
foreign key onto `public.files` in the schema and it was `on delete
restrict`, so the object-retention sweep — which had never met a refusal —
deleted a customer's bytes, aborted on the row delete, and aborted on the
same row every night after. No customer file would ever have been purged
again, silently. That is the third BLOCK in three independent reviews in
this repository, and the pattern is worth naming: work written and reviewed
inside one session is not reviewed.

**A second review ran on 2026-09-22, over both phases, and returned BLOCK from
all four reviewers** — one per seam, none seeing another's report. It found
that **Phase 2 had never worked**: `begin_commit` was defined, exported and
called by nothing, so every commit asked the state machine for an edge it does
not have, rolled the writer's rows back, and was refused again trying to record
the failure. Every commit of every product wrote nothing, stranded its run and
told nobody.

Two critical and nine high are fixed, each with a test that fails without it.
Seventeen medium and fifteen low are carried with a decision each.
`docs/features/data-import/phase-2-review.md` is the record, and it opens with
why every gate in the estate was green over it: the generator test asserts the
*shape* of the commit, and all of it is true of code that fails on every run.

### What is deliberately unbuilt, and why

Three Phase 1 plan items were not built. Each is a row in
`docs/platform/gap-defect-register.md` and each is named in
`docs/features/data-import/architecture.md`: `files.maxFilesPerUpload` is
unsurfaced rather than enforced, the upload flow was not extracted into a
shared primitive, and the preview does not go through the shared data table.
None of them touches the safety properties.

### What has no automated proof

**Less than it was, and the change is worth reading.** Until 2026-09-22 the
answer here was "everything a person does with a real file", because the e2e
harness started the web application alone. Two things closed most of that.

`tests/integration/test_import_commit_rls.py` runs the commit against a real
PostgreSQL with row-level security on — four cases, each mutation-checked — and
`Generator Integration` runs it on the round-trip row.

And the import page is **rendered in CI at last**. It never had been: a
generated product declares no targets, so `ImportPanel` returned its no-targets
banner and the browser suite asserted that. A fixture target installed by the
workflow from `.github/fixtures/` — inside no template, so it reaches no
product — now makes `e2e/roundtrip/imports.spec.ts` draw the page, the picker,
the history and the report.

What still has no automated proof is the part that needs a writer: an upload
through a bucket, a dry run against a real queue, and a commit that lands rows
in a product's own table. Of `manual-test-plan.md`'s forty cases, ten are
covered — eight executed by hand on 2026-09-22 and two by that browser suite —
and thirty are blank.

## Recommended order

Rewritten 2026-09-22. **Four of the five items this section used to list were
already done when it was read** — the independent security review, ADR 0006's
three questions, the two capability declarations, and STORAGE-015, which the
story table twelve lines above already called Built. A recommendation that
outlives its work sends somebody to do it twice, which is R-042 in the one
document whose whole job is to say where things stand.

What is left is verification and sync, not construction.

1. **Sync `docoris`.** It is the furthest adrift of the live products: its
   starter-range migrations stop at `00028`, so it has no settings framework,
   no notification dispatch point, no outbox and no round-trip harness. The gap
   widens every week and the method is proven — generate twice from one starter
   commit, with and without, and apply only what the delta shows.
2. **One notification through a deployed product.** Not a matrix: one notice,
   caused by a real producer, through the outbox, to an inbox. That is the
   single claim nothing in this estate makes, and the class it would catch —
   a producer that composes nothing, a language resolved from the wrong
   person — has already shipped twice here.
3. **The governance manual pass.** Twenty-five cases, every verdict blank since
   2026-09-16, and the export and hold flows have never been exercised by a
   person. Two of those flows delete.
4. **Data import's remaining thirty cases**, which need the API started with a
   bucket and a queue and a target that declares a writer.
5. **The carried findings**: seventeen medium and fifteen low from the data
   import review, of which IMP2-13, IMP2-14, IMP2-16 and IMP2-21 are the ones a
   customer could meet.

Not listed because they are nobody's engineering: Stripe live mode, the live
teardown sitting, and the two ZITADEL writes per environment. They are in
`docs/FOLLOW_UPS.md` and they do not contend with anything above.
