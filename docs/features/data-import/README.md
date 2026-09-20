# Data import and migration framework

Let a customer load their existing records into a KORAS product without a
developer: upload a file, map its columns, see what would happen, fix what is
wrong, and commit.

**Phase 1 is built as of 2026-09-19. Phase 2 is not, and the difference is the
whole point of this document.** What ships today stops at the dry run: a run
reaches `validated`, which is a terminal state that wrote nothing, and a person
reads the report. There is no commit route, no commit task, and no control on
the page that could write a row — absent rather than disabled, because a
disabled button promises a thing the product cannot do.

No manual pass has been run against any of it.

## The documents

| Document | What it answers | Written |
|----------|-----------------|---------|
| `docs/platform/execution/CAT-02-data-import.md` | The plan: phases, stories, acceptance criteria, dependencies | Before |
| `docs/adr/0009-import-runs-are-not-a-third-export.md` | Why an import run has its own table rather than reusing the export pattern | Before Phase 1 code |
| `architecture.md` (here) | What was actually built, and where it departs from the plan | After |
| `manual-test-plan.md` (here) | The cases no automated test in this estate reaches | After |

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
- **A commit.** Phase 2.
- **XLSX and JSON.** Declared in `Format` so the vocabulary is settled, refused
  by the reader. Phase 3.
- **Anything about Docoris, Dianova or the shop.** The engine takes a
  declaration and nothing else.
