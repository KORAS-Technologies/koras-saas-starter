# Data import and migration framework

Let a customer load their existing records into a KORAS product without a
developer: upload a file, map its columns, see what would happen, fix what is
wrong, and commit.

**Phase 1 shipped 2026-09-19 and Phase 2 on 2026-09-20.** Phase 1 stops at the
dry run: a run reaches `validated`, which wrote nothing, and a person reads the
report. Phase 2 is the commit, and it writes through a `Writer` the product
declares on its target — the only thing in the path that may write a record,
and what keeps the rule the plan states first: no product table name reaches
the engine.

A target with no writer is not committable, and that is absent rather than
disabled all the way down: the API answers `committable: false`, the page draws
no control, and the route refuses. A disabled button promises a thing the
product cannot do.

**This paragraph said Phase 2 was not built until 2026-09-22**, two days after
it shipped, in the document that introduces the feature.

**Two independent reviews have run, and both returned BLOCK.**

The first, on 2026-09-19, covered Phase 1: one critical finding, two high and
three medium, all six fixed, three low carried. `review.md` is the record.

The second, on 2026-09-22, covered Phase 1 and Phase 2 together with four
reviewers, one per seam. **It found that Phase 2 had never worked**: the commit
path could not succeed on any run of any product, because the run was never
moved into the state `record_commit` requires. Two critical, eight high,
eighteen medium. `phase-2-review.md` is the record, and it opens with why every
gate in the estate was green over it.

## The documents

| Document | What it answers | Written |
|----------|-----------------|---------|
| `docs/platform/execution/CAT-02-data-import.md` | The plan: phases, stories, acceptance criteria, dependencies | Before |
| `docs/adr/0009-import-runs-are-not-a-third-export.md` | Why an import run has its own table rather than reusing the export pattern | Before Phase 1 code |
| `architecture.md` (here) | What was actually built, and where it departs from the plan | After |
| `manual-test-plan.md` (here) | The cases no automated test in this estate reaches | After |
| `review.md` (here) | The first independent review, its six findings and what each one broke | After Phase 1 |
| `phase-2-review.md` (here) | The second, over both phases: four reviewers, and the commit path that had never run | After Phase 2 |
| `templates-and-formats-analysis.md` (here) | The gap analysis and design for downloadable templates, XLSX and the preview counts, with the twelve decisions it put to the owner | Before the template code |
| `docs/adr/0012-import-template-versioning.md` | What a template carries, how a file is judged, and the resolution of those twelve | Before the template code |

The plan is left as it was written. Where it and `architecture.md` disagree,
the as-built one is right — a design document edited after the fact stops being
a record of what was decided and becomes a second, worse description of the
code.

## The one-paragraph summary

`koras-import` is a product-profile Python package holding the engine: the
target declaration, the registry, the CSV reader, the mapping resolver, the row
validator and the state machine. It knows no table name of any product. A
product declares what may be imported in `services/api/koras_api/imports/targets.py`,
an empty list in the generated product, exactly as it declares reports, audit
actions and settings. The API carries a run store over two tables,
`import_runs` and `import_row_errors`, both with row-level security enabled and
forced. The dry run is the first enqueued job in this product — PLAT-F1's first
caller — and runs as the tenant rather than as provisioning, because it is work
one organisation asked for rather than a sweep across every one. The page is
`/dashboard/imports`, behind `imports.manage` and behind no plan.

## Capability

`data_import`, **off by default**. Unlike reporting and the governance pair, an
import target is something a product declares; a product that declares none
would get a page listing nothing and two tables nothing writes to. Turned on
with `--with data_import`.

By the rule in `profiles/product/manifest.yaml`, gating the migration is
allowed here because no foundation code and no foundation migration reaches
either table. That is the test `audit_events` failed until 2026-09-16.

## What is deliberately not here

- **Delete, merge and replace** are absent from the operation set. The brief
  says delete must not be enabled by default; it is not in this plan at all.
- **JSON.** Declared in `Format` so the vocabulary is settled, refused by
  the reader and by the template renderer by name. Deferred on 2026-09-29 by
  ADR 0012 D4. XLSX reads and renders since the same day.
- **A commit that completes with errors, progress counts during a commit, a
  manual-review duplicate strategy, an annotated error file for re-import, and
  per-row outcomes from the writer.** Each was put to the owner on 2026-09-29
  and refused or deferred; ADR 0012 has the table.
- **Anything about Docoris, Dianova or the shop.** The engine takes a
  declaration and nothing else.
