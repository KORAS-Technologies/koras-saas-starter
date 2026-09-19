# Parallel execution plan

| | |
|---|---|
| **Purpose** | Which categories may run at the same time, what must be finished first, and the file-ownership map that keeps two agents out of the same file. |
| **Written** | 2026-09-19. |
| **Rests on** | `docs/platform/feature-dependency-map.md` for the edges; this document turns them into a schedule. |

## The second wave, from 2026-09-19

The first wave is built: PLAT-F1, CAT-01 Phases 0 and 1, CAT-03 Phases 0 and 1.
The table below is the original plan and is kept because its reasoning still
holds; this section is what the next three actually collide over.

| Work | Verdict | Why |
|---|---|---|
| **CAT-02 Phases 0-1 — data import** | **START NOW** | Unblocked the moment PLAT-F1 landed |
| **CAT-01 Phase 2 — channels and templates** | **SAFE TO PARALLELIZE** with CAT-02, under one rule | They meet in two files and nowhere else |
| **F27 — the settings framework reviewed** | **PARALLEL AS A REVIEW; its fixes are not** | A review reads. What it finds wants to be fixed in a file CAT-01 Phase 2 is editing |
| **CAT-03 Phase 2 — the provisioner** | **PERFECTLY PARALLEL, and deferred anyway** | A different repository and not one shared file — but its value is capped until F21 activates the account |

### Where CAT-02 Phase 1 and CAT-01 Phase 2 actually meet

Two files, and they were both already named in the ownership map below:

- **`profiles/product/manifest.yaml`.** CAT-02 declares a new capability and its
  path list; CAT-01 Phase 2 extends the notification capability's list with the
  template registry. One hand applies both blocks, as the map says.
- **`packages/i18n/src/messages/{en,de,es}.ts`.** Both append. Append-only in
  three files in lockstep is low conflict risk and high breakage risk if one
  language is forgotten, which a generator test already catches.

**And two collisions that look real and are not.** CAT-02 does *not* touch
`settings_catalogue/standard.py`: the three `files.*` settings are already
surfaced, and what is wrong with them is that nothing enforces them — the fix is
in the presign route, not the catalogue. And CAT-02 does not wait for CAT-01's
channel seam, because the emitter contract it consumes shipped in Phase 0 with a
no-op default.

**The one to watch is the generator's settings test.** `product-settings.test.ts`
asserts exact counts of surfaced and unsurfaced settings, and CAT-01 Phase 2
changes both when it re-surfaces `notifications.emailEnabled`. That file has
already been edited twice for counts in one day. If both streams touch it, the
second one to merge rebases rather than guesses.

### Reserved ranges, re-allocated

CAT-01 took `00032` from its own range, and F27's secret-guard fix took `00033`
out of it — a correction to shipped code needed a number and the ranges are for
planned work. The rest stand: CAT-02 takes migrations `00036`-`00039` and RLS
tests `320`-`340`; CAT-01 keeps `00034`-`00035` and `290`-`310`. **A fix to
shipped code takes the next free number and says so here**, rather than waiting
for a range.

### Why F27 is different

It is not a code stream. Its first half is a review, which reads and reports and
collides with nothing. Its second half is fifteen manual cases against a running
stack, which is a person at a browser rather than an agent — so it competes for
*your* time rather than for any file. Run the review alongside the other two and
hold its fixes until one of them lands, or take the review's findings as a third
stream once they exist.

---

## Verdict per category

| Work | Verdict | Why |
|---|---|---|
| **PLAT-F1 — the job contract** | **START FIRST, alone** | Two categories depend on it, it is small, and both would otherwise build a workaround that has to be removed. One or two days |
| **CAT-01 Notifications, Phases 0-2** | **SAFE TO PARALLELIZE with PLAT-F1** | Writes rows in the transaction that caused them, and dispatches mail the way the one existing mail does. Needs nothing PLAT-F1 builds |
| **CAT-01 Notifications, Phase 3+** | **PARALLEL AFTER PLAT-F1** | The outbox and the delivery log need to enqueue |
| **CAT-02 Data Import** | **BLOCKED until PLAT-F1 lands** | Import is a background-job feature at Phase 1. The documented workaround — a cron polling for queued runs every minute — is drift, and docoris named it as such before writing it |
| **CAT-03 Stripe provisioning** | **SAFE TO PARALLELIZE, from now** | A different repository, no shared file with either other category, and every foundation it needs exists |
| **CAT-02 ↔ CAT-01** | **PARALLEL WITH CONTRACT** | One emitter interface with a no-op default. Neither waits |

**The shortest honest schedule.** CAT-03 and CAT-01 P0-P2 start now, in
parallel, in two repositories. PLAT-F1 starts now in the third slot and finishes
inside a couple of days, at which point CAT-02 starts and CAT-01 unblocks its
Phase 3. Nothing waits on anything it does not have to.

## Sequence

```
day 0      PLAT-F1 ........... job contract          [starter]
           CAT-01 P0 ......... contracts + capability [starter]
           CAT-03 P1 ......... lookup keys + idempotency  [control plane]

day 2      PLAT-F1 lands ....................... CAT-02 unblocks
           CAT-01 P1 ......... in-app + toast + banner
           CAT-02 P0/P1 ...... registry, upload, map, dry run
           CAT-03 P2 ......... provisioner + catalogue drift

           ... CAT-01 P2-P5, CAT-02 P2-P4, CAT-03 P3-P4 run independently ...

gate       Integration gate ... one generated product carrying all of it,
                                lint, typecheck, test, RLS suite, browser suite

           Regression ......... generator integration, both profiles,
                                with and without each new capability

           Sync ............... koras-e2e-shop by hand-carried commit;
                                docoris by choice, per its own roadmap
```

## Shared-file ownership map

Two categories editing the same file without coordination is the failure this
table exists to prevent. **Owner** means that category's lead makes the change;
another category asks rather than edits.

| File or area | Owner | Shared? | Coordination |
|---|---|---|---|
| `profiles/product/manifest.yaml` — capabilities, defaults, template map | **Platform** | Yes, by all three | Each category submits its capability block; the platform owner applies them. Two categories editing this file at once is a guaranteed conflict and a guaranteed silent gating bug |
| `profiles/product/defaults.yaml` | **Platform** | Yes | Same rule |
| `supabase/migrations/` numbering | **Platform** | Yes | **Reserved ranges, allocated once:** CAT-01 takes `00032`–`00035`, CAT-02 takes `00036`–`00039`, PLAT-F1 takes none. A category that needs a fifth asks rather than taking `00040` |
| `supabase/tests/` numbering | **Platform** | Yes | CAT-01 takes `290`–`310`, CAT-02 takes `320`–`340` |
| `services/worker/koras_worker/worker.py.hbs` | **Platform** | Yes | **No *product* edits it** — that is what the task registry is for, and a product that edited it would carry a conflict into every sync. A *category* may: a starter-owned task has to be bound somewhere, and CAT-01 added a cron there on 2026-09-19. Amended because the original row read as absolute and would have told CAT-02 it was blocked when it is not |
| `services/worker/koras_worker/tasks/product.py` | **PLAT-F1** | Yes | PLAT-F1 adds the task list beside the cron list; categories append to it |
| `packages/permissions/src/index.ts` + the Python mirror | **Platform** | Yes | One string per category, applied together. A generator test fails if the two languages drift, so a half-applied change is caught |
| `packages/branding/src/index.ts.hbs` navigation registry | **CAT-01**, then CAT-02 | Yes | CAT-01 adds the notification centre module in P1; CAT-02 adds the import module in P1. Sequence them a day apart, or hand both literals to one owner |
| `packages/i18n/src/messages/{en,de,es}.ts` | **Platform** | Yes | Append-only, three files in lockstep; a test fails on any catalogue missing a key. Low conflict risk, high breakage risk if one language is forgotten |
| `services/api/koras_api/settings_catalogue/standard.py` | **Platform** | Yes | The six unenforced settings (PLAT-DEF-001) are fixed here, by whichever category reaches them first. CAT-01 owns the notification three, CAT-02 owns the file three |
| `services/api/koras_api/core/audit.py` action groups | **Platform** | Yes | Each category declares its own action group in its own module and extends the registry at import, which is how every existing capability does it. No shared edit |
| `services/api/koras_api/main.py.hbs` router registration | **Platform** | Yes | Two new routers, both capability-gated. Order is load-bearing — a static sub-path must be registered before an id route |
| `packages/ui/src/data-table/` | **CAT-02** | Yes | Only if server pagination is funded. CAT-02 Phase 1 avoids needing it |
| `packages/ui/src/` new primitives | **CAT-01** | No | Toast, banner, drawer, bell are new files |
| `packages/ui/src/upload/` | **CAT-02** | No | New files, extracted from the Files page |
| `core/notify.py` | **CAT-01** | No | CAT-01 P2 moves it onto the dispatch point |
| `generators/create-koras-app/tests/` | Each category | No | One new test file per category; `product-notifications.test.ts` and `product-import.test.ts` |
| `docs/platform/gap-defect-register.md` | Each category | Yes | Append and update own rows only. Do not renumber |
| `koras-control-plane` entirely | **CAT-03** | No | No other category touches that repository |
| `output/koras-e2e-shop` | **Integration** | Yes | Synced once, after the integration gate, by hand-carried commit. Never during a category's phases |
| `docoris` | **Nobody, by default** | — | A real product. It is touched only if its own roadmap asks, and never to validate the factory |

## Concurrency rules

1. **The platform owner holds the manifest.** Every capability gate, default and
   template-map entry goes through one hand. Breaking this rule once produced a
   product that recorded nothing and nobody noticed, because a missing audit
   table looks exactly like an empty one.
2. **Migration numbers are allocated, never taken.** Two categories picking the
   next free number a day apart produce two `00032`s, and the second one to
   merge is silently skipped by anything that applies in order.
3. **A category never edits a generated file to add its work.** If there is no
   extension point, the answer is to build one, not to edit the file. That rule
   is why `PRODUCT_CRON_JOBS`, the product reports list, the product settings
   list and the file-hook registry exist, and it is what PLAT-F1 extends.
4. **A SOFT dependency is only soft once its contract is written.** CAT-02 may
   emit notification events on day one because the emitter interface and the
   five event names are fixed in `docs/platform/master-platform-plan.md` §9 and
   repeated in both manifests. An unwritten contract is a HARD dependency
   wearing a disguise.
5. **The Control Plane is not code-synced from the starter.** Anything CAT-03
   needs from a shared contract is implemented there against the contract file,
   in parallel, not received from here. This is recorded in
   `docs/features/PROFILE_SYNC_MATRIX.md` and is a fact about the estate rather
   than a preference.

## Branches and worktrees

The repository's own standard is in
`profiles/product/template/.claude/orchestration/WORKTREE-STANDARD.md`, and the
agent registry declares a three-worker pool isolated by git worktree with a
branch pattern of `feature/<feature-id>-<slug>`. That standard is for work
inside a generated product. The factory has no equivalent written down, so this
plan uses the same shape rather than inventing a second:

```
feature/plat-f1-job-contract
feature/cat-01-notifications
feature/cat-02-data-import
```

and in the other repository, `feature/cat-03-stripe-provisioning`.

Each branch must stay independently buildable, testable, reviewable and
mergeable. `develop` is the integration branch for the starter; promotion to
`main` is a release step and is not a definition of done.

## What a parallel run cannot hide

Three things will only be visible when the branches meet, and the integration
gate exists for them:

- **A capability that gates the wrong file set.** Caught by generating both
  profiles with and without each new capability, which the generator integration
  workflow already does for three existing ones.
- **A migration that applies in the wrong order.** Caught by the RLS suite,
  which runs every migration against a real Postgres.
- **A settings key surfaced with no consumer.** Caught by nothing. That is
  PLAT-DEF-001, it has happened twice already, and the integration gate should
  grow a check for it rather than a reviewer remembering.
