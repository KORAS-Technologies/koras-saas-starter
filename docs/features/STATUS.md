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
passes. It is not `Done`, and the two reasons are worth naming rather than
leaving in a table:

1. **No manual pass has been run.** `manual-test-plan.md` has fifteen cases and
   fifteen blank verdicts as of 2026-09-19. A blank verdict is not a pass.
2. **No independent review.** Eleven phases across three repositories,
   including three new tables with row-level security, a check constraint that
   refuses secrets, and a platform write route that needed an ADR to justify
   its direction — none of it has had eyes other than the ones that wrote it.

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

### What has no automated proof

The round trip. Changing a setting and watching a table repaginate needs an API,
a database and rows; the e2e harness starts the web application alone. Sixteen
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
| `notifications.digestFrequency` | 4 | Not started — needs the Phase 3 outbox |
| Outbox, delivery log, retry | 3 | Not started |

### What has no automated proof

A notification arriving. The unit suite proves the seam decides correctly and
the browser suite proves the bell and the drawer render; nothing exercises a
producer through a real database to a real inbox. No mail has been sent by
this path from a deployed product.

## Data import and migration framework

Phase 1 of four, shipped 2026-09-19. Stories are `IMPORT-US-*` in
`docs/platform/execution/CAT-02-data-import.md`.

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
| IMPORT-US-007 | Download a file naming every bad row | 2 | Not started |
| IMPORT-US-008 | Choose whether a duplicate is skipped or updated | 2 | Part built — the operation is chosen and stored; nothing acts on it yet |
| IMPORT-US-009 | A commit that either fully happens or does not | 2 | Not started |
| IMPORT-US-010 | See my past imports and what each did | 2 | Part built — the history renders; there is nothing committed to see |
| IMPORT-US-016 | Every import attributable and audited | 2 | Not started — the run records who asked; no audit action is registered yet |
| IMPORT-US-018 | Be told when a long import finishes | 2 | Not started — CAT-01's emitter exists and is not called |
| IMPORT-US-011 | Save a mapping and reuse it | 3 | Not started |
| IMPORT-US-012 | Cancel a running import | 3 | Part built — `cancel` refuses a commit in flight by state; there is no commit to cancel |
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

### What is deliberately unbuilt, and why

Three Phase 1 plan items were not built. Each is a row in
`docs/platform/gap-defect-register.md` and each is named in
`docs/features/data-import/architecture.md`: `files.maxFilesPerUpload` is
unsurfaced rather than enforced, the upload flow was not extracted into a
shared primitive, and the preview does not go through the shared data table.
None of them touches the safety properties.

### What has no automated proof

Everything a person does with a real file. The e2e harness starts the web
application alone, so its four browser checks cover routing, refusal and
degraded rendering and nothing that needs an API, a queue or a bucket. No file
has been imported through a deployed product, and `koras-e2e-shop` — the one
repository in the estate with a domain that could declare real targets — has
not been synced.
`docs/features/data-import/manual-test-plan.md` has twenty-two cases and
twenty-two blank verdicts.

## Recommended order

**SAG-F2 has no unbuilt stories left.** Everything below is either review,
a decision, or work that belongs to SAG-F1.

1. **Independent security review** of what has shipped. Eight commits of
   governance code — migrations, policies, two destructive sweeps, an
   authorization asymmetry, an export path that moves records out of the
   product — have had no independent eyes, and the gap widens with each
   feature rather than closing.
2. **A manual pass.** Twenty-five cases, every verdict still blank, and the
   export and hold flows have never been exercised by a person.
3. **Answer ADR 0006 question 1.** It blocks five storage stories and is half
   a day of somebody's decision rather than of engineering.
4. **Declare the two capabilities.** Everything has landed in the foundation,
   so every product carries holds, audit search, export and two sweeps whether
   it wants them or not.
5. **STORAGE-015**, the platform contract, so the console can show governance
   state across the estate.
