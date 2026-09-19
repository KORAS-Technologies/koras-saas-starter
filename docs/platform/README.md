# Platform planning

Cross-category planning for the KORAS platform: one audit, one capability
matrix, one dependency map, one register, and one execution manifest per
feature category.

## Why this directory exists, and how it relates to the rest

`docs/features/` holds one directory per *feature* — what it is, its stories,
its criteria, its tests. This directory holds what sits **above** a feature: the
audit that several features share, the dependency classification that decides
which may run in parallel, and the ownership map that keeps two of them out of
the same file. It was created on 2026-09-19, for the first piece of work in this
repository that planned three feature categories at once.

The division of labour, extending the table in `docs/features/README.md`:

| Kind of document | Where | Example |
|------------------|-------|---------|
| Why a decision was taken | `docs/adr/` | `docs/adr/0008-koras-platform-job-and-notification-contracts.md` |
| How a subsystem works | `docs/` top level | `docs/STORAGE_ARCHITECTURE.md` |
| What a feature is, its stories, criteria and tests | `docs/features/<slug>/` | `docs/features/settings-framework/` |
| What several features share, and who may build what when | `docs/platform/` | this directory |

## Contents

| Document | What it answers |
|----------|-----------------|
| `docs/platform/master-platform-plan.md` | The audit, the conclusions, the roadmap, the readiness verdict per category |
| `docs/platform/master-capability-matrix.md` | For every platform capability: does it exist, where, who needs it, what to do |
| `docs/platform/feature-dependency-map.md` | The dependency graph, each edge classified HARD / SOFT / OPTIONAL / FUTURE |
| `docs/platform/parallel-execution-plan.md` | Which categories may run at once, and the file-ownership map that makes it safe |
| `docs/platform/gap-defect-register.md` | Every gap and defect found, with an ID, an owner and a status |
| `docs/platform/execution/CAT-01-notifications.md` | The notification category, executable on its own |
| `docs/platform/execution/CAT-02-data-import.md` | The data-import category, executable on its own |
| `docs/platform/execution/CAT-03-stripe-billing.md` | The Stripe provisioning category, executable on its own |

## Three registers already exist, and this adds a fourth on purpose

`docs/RISK_REGISTER.md` owns defects found in operation. `docs/FOLLOW_UPS.md`
owns work deliberately left undone. `docs/SYNC_BACKLOG.md` owns the
same-thing-true-in-one-place-only class. `docs/platform/gap-defect-register.md`
owns findings scoped to a feature category, under the category's own ID series.

Where a finding already has an entry in one of the three, this register points
at it rather than restating it. A second description of one problem is how two
of them come to disagree — the rule `docs/FOLLOW_UPS.md` states in its own
header, applied here.

## The check that does not reach this directory

`tests/docs/hedged-claims.test.ts` walks `docs/` recursively, so every hedged
claim in these documents needs a date in its own paragraph, heading or table
row. `tests/docs/file-references.test.ts` and `tests/docs/identifiers.test.ts`
read only the top level of `docs/` plus `CLAUDE.md`, so a path or an identifier
named here is checked by nobody. That asymmetry is recorded as PLAT-DEF-004,
and it is why every proposed-but-unbuilt path in these documents is written
without backticks: a path in backticks is a claim that it exists.
