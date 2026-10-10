# Feature catalogue

Feature-scoped documentation for the KORAS SaaS Starter: what a piece of work
is for, the stories it decomposes into, the criteria that decide whether it is
done, and the tests — automated and manual — that say so.

## Why this directory exists, and how it relates to the rest

The starter had no feature catalogue before 2026-09-16. Documentation lived as
flat `SCREAMING_SNAKE.md` files in `docs/` plus decision records in `docs/adr/`,
and that convention is unchanged: **an architecture document still lives at the
top level, and this directory does not duplicate it.**

The division of labour:

| Kind of document | Where | Example |
|------------------|-------|---------|
| Why a decision was taken | `docs/adr/` | `docs/adr/0003-koras-storage-audit-governance.md` |
| How a subsystem works | `docs/` top level | `docs/STORAGE_ARCHITECTURE.md` |
| What a feature is, its stories, criteria and tests | `docs/features/<slug>/` | this directory |
| What several features share, and who may build what when | `docs/platform/` | `docs/platform/master-platform-plan.md` |

`docs/platform/` was added on 2026-09-19, for the first piece of work here that
planned three feature categories at once: it holds the audit they share, the
dependency classification deciding which may run in parallel, and the ownership
map that keeps two of them out of the same file. A feature directory still owns
its own stories, criteria and tests.

A generated **product** uses a different and narrower layout —
`docs/features/<feature-id>-<slug>/` with six named sections, defined
authoritatively in
`profiles/product/template/.claude/orchestration/documentation-policy.yaml`.
That layout is for work done *inside a product*, by the product's own agents,
with QA evidence at canonical paths. This directory is the factory's own, for
work on the templates themselves. The two are deliberately not the same shape,
because the factory has no manual QA environment and no product to screenshot.

## Catalogue

### Engineering framework

Not a product capability: the orchestration contract the product profile
ships, and the one feature directory here that describes how features
themselves are built.

| Feature | Directory | Status as of 2026-09-19 |
|---------|-----------|-------------------------|
| Multi-agent framework V2.1 | `engineering-framework/` | Shipped 2026-09-19. Architecture in `docs/ENGINEERING_FRAMEWORK.md`; as of 2026-09-19 not yet exercised by a real product lifecycle. |


### Storage & Audit Governance

A platform capability in two independently manageable halves.

| Feature | Directory | Status as of 2026-09-16 |
|---------|-----------|-------------------------|
| Storage Architecture & Data Protection | `docs/features/storage-architecture/` | Part built |
| Audit Storage, Retention & Archival | `docs/features/audit-storage/` | Part built |

**"Part built" means what it says, and the distinction matters more than usual
here.** Migration `00018_files_governance.sql` added columns for integrity,
classification, retention, legal hold, scanning, archival and backup state.
Roughly half of them are written by something. A reader who inferred capability
from the schema would conclude this feature is finished; it is not. Each
feature's `user-stories.md` marks every story `EXISTING`, `EXTEND`, `NEW` or
`NOT REQUIRED` against what is actually in the repository.

The decision record for both halves is
`docs/adr/0003-koras-storage-audit-governance.md`, with
`docs/adr/0004-storage-provider-abstraction.md`,
`docs/adr/0005-storage-object-hierarchy.md` and
`docs/adr/0006-backup-strategy.md` carrying the detail of three of its
decisions.

### Settings & Preferences Framework

Three levels — platform default, organisation, person — resolved once per
request and read by shared components rather than fetched page by page.

| Feature | Directory | Status as of 2026-09-19 |
|---------|-----------|-------------------------|
| Settings & Preferences Framework | `docs/features/settings-framework/` | Part built |

`Part built` here does not mean half the stories shipped. Every phase shipped
and every automated check passes; it is not `Done` because no manual pass and no
independent review have been run, and because five `grid.*` settings are
registered that nothing honours. `docs/features/STATUS.md` names both.

The decision record is `docs/adr/0007-koras-settings-framework.md`, amended
twice. The as-built description is `docs/SETTINGS_ARCHITECTURE.md` and the
day-to-day is `docs/SETTINGS_DEVELOPER_GUIDE.md`.

**This directory holds the design documents as they were written, before the
work, and they are not edited to match what was built.** A design document
revised after the fact stops being a record of what was decided. Where it and
the as-built document disagree — the value tables were renamed, for one — the
as-built one is right.

### Data import and migration framework

Upload a file, map its columns, see what would happen, and — from Phase 2 —
commit. The engine knows no product's table names; a product declares what may
be imported the way it already declares reports, settings and audit actions.

| Feature | Directory | Status as of 2026-09-19 |
|---------|-----------|-------------------------|
| Data import and migration framework | `docs/features/data-import/` | Part built |

`Part built` here means Phase 1 of four. A run reaches `validated`, which is a
terminal state that wrote nothing; there is no commit route, no commit task and
no control on the page that could write a row. Three Phase 1 plan items were
deliberately not built and are named in `data-import/architecture.md` rather
than left to be rediscovered.

The plan is `docs/platform/execution/CAT-02-data-import.md` and the decision
record is `docs/adr/0009-import-runs-are-not-a-third-export.md`.

### Local ZITADEL follow-ups (Phase 4.3A)

Five plans identified while reviewing PR #66 and deliberately kept out of it.
These are plans only. ADR 0018 is the decision record still awaiting approval.

| Feature | Directory | Status as of 2026-10-10 |
|---------|-----------|-------------------------|
| Local ZITADEL follow-ups to Phase 4.3A | `docs/features/local-zitadel-follow-ups/` | Planned |

## Status vocabulary

The starter has no prior status convention for features, so this one is
declared here rather than assumed:

| Status | Meaning |
|--------|---------|
| Planned | Written down, not started |
| Blocked | Cannot start; the blocker is named |
| In progress | Being built |
| Part built | Some stories are done and shipped; others are not |
| Built | Every story done, and verified |
| Done | Built, plus the Definition of Done satisfied — reviews, evidence, acceptance |

**Nothing here is `Done`.** No security review, privacy review or manual test
pass has been executed against any of this work as of 2026-09-19, and the
Definition of Done in
`profiles/product/template/.claude/orchestration/definition-of-done.md` is
explicit that a feature is not done while any applicable condition is unmet.

## A note on when this was written

This package was written on 2026-09-16, **after** part of the implementation
rather than before it. That is the wrong order and it is recorded rather than
disguised: the stories below are reconstructed from work already shipped in
commits `3897870`, `734d25d`, `1041420` and `e9f3dfe`, which is why so many are
marked `EXISTING`. The acceptance criteria for those stories were written
against behaviour that already exists, so they describe rather than constrain
it — an important difference when reading them, and the reason each such
criterion names the test that actually asserts it.
