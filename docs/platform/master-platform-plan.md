# Master platform plan

| | |
|---|---|
| **Purpose** | One coordinated plan for three feature categories — notifications, data import, and Stripe product and price provisioning — resting on one audit rather than three. |
| **Written** | 2026-09-19, against `develop` at `f198908`. |
| **Mode** | Planning. No application code was written by the pass that produced this. |
| **Companions** | `docs/platform/master-capability-matrix.md`, `docs/platform/feature-dependency-map.md`, `docs/platform/parallel-execution-plan.md`, `docs/platform/gap-defect-register.md`, and one manifest per category under `docs/platform/execution/`. |

---

## 1. Executive summary

Three feature categories were asked for. The audit says they are not three
similar pieces of work, and treating them as three would be the first mistake.

**One of them is not a starter category at all.** All billing code lives in
`koras-control-plane`, because `docs/BILLING_DESIGN.md` decided that no product
ever holds a provider credential and no product ever calls the provider. The
starter's `packages/billing` is three lines and that document says it may be
removed. So CAT-03 is Control Plane work, and the starter-first rule is the one
rule in the brief that must be set aside here — applying it would put a payment
secret in every generated repository. What CAT-03 needs is real and specific:
deterministic lookup keys, an idempotency key on outbound calls, a provisioner
that creates provider products and prices from the Koras catalogue, and a drift
check for the catalogue rather than only for subscriptions.

**One of them is blocked by something neither category owns.** Nothing in this
repository can enqueue a background job. ARQ is present, the worker runs, the
sweeps are real — and every one of them is cron. The three request paths that do
work after responding use FastAPI background tasks, which die with the process.
Data import is a background-job feature in its first phase; it cannot honestly
start until an enqueue seam exists. The gap is small — a seam in the API, a task
registry beside the existing cron registry, and a retry policy — and it is the
single highest-leverage item in this plan, because it also unblocks reliable
notification delivery. It is called PLAT-F1 and it closes a question a real
product already raised.

**One of them has a name reserved and nothing behind it.** `notifications` is
declared as a capability in both profile manifests, gates no files, has no
defaults entry, and its package is `export {}`. Meanwhile three notification
preference settings are registered, translated into three languages, drawn on
the preferences page, and read by no code at all — and so are three file
settings. A customer can switch off notification emails today and still receive
them. That is the sharpest single defect the audit found, and it is an exact
repeat of the failure the settings framework introduced `surfaced=False` to
prevent.

**The requirements for two of the three are already written, by the product
that needs them.** `docoris` is a real KORAS product carrying a 439-line
platform capability inventory, a 229-row gap register, and drafted architecture
documents for both import and notifications, with a clean split between the
reusable engine and the product-specific parts. This plan reuses that work
rather than re-deriving it, and adopts three of its fifteen platform gaps.

The audit also found four documentation defects, one of them on the file every
session reads first: `CLAUDE.md` said restore does not ship. It ships — a
migration, a router, a worker task, a page and a browser test. The docoris audit
had found the same thing independently and written "Believe the code."

---

## 2. Repository audit — what was inspected

| Repository | Role | What was read |
|---|---|---|
| `koras-saas-starter` | The factory. Exhaustively audited | Both profile manifests and defaults; the whole generator source tree and its 54 test suites; the three template layers; all 31 product migrations and 24 RLS tests; the API's 15 routers and 22 core modules; 13 Python packages; the TypeScript packages; the worker, scheduler and gateway services; `.claude/` at the root and the product overlay; all 40 documents in `docs/`, the 7 ADRs and the 3 feature directories; the 4 documentation tests |
| `koras-control-plane` | The platform authority. Audited for billing and the catalogue | The billing adapter package; the API's billing, signup, portal and entitlement modules; the reconciliation engine; 45 migrations; the in-code plan and entitlement catalogue; the console and portal billing pages; 26 documents and 12 runbooks |
| `docoris` | A real product. Read, not modified | Its platform capability inventory, gap register, open decisions, and its drafted import and notification architectures |
| `output/koras-e2e-shop` | The reference product. Read, not modified | Its project manifest, to establish which capabilities a generated product records |

**Method.** Four parallel audits — notifications, import and jobs, billing
across both repositories, and shared foundations — each instructed to establish
absence by search rather than by not having found something, and to report paths
rather than impressions. Every load-bearing claim in this plan was then
re-verified directly: the absent enqueue call, the unread settings, the two
documentation defects, and the queue package's split layout.

**The structural fact that shaped everything.** The starter's root
`packages/`, `services/`, `apps/`, `python-packages/` and `supabase/` are
empty. Real code lives in `profiles/_shared/template/` and the two profile
template trees. Every deliverable in this plan is a template change, a manifest
entry, a defaults entry, a template-map entry and a generator test — not an
application change.

---

## 3. Capability matrix

Full detail is in `docs/platform/master-capability-matrix.md`. The summary:

| Capability | Status | Needed by |
|---|---|---|
| Auth, tenancy, forced RLS | EXISTS | All |
| Permissions | EXISTS + EXTENSION POINT | CAT-01, CAT-02 |
| Settings | EXISTS + EXTENSION POINT | All |
| Audit | EXISTS + EXTENSION POINT | All |
| Storage, and its governance | EXISTS + EXTENSION POINT | CAT-02 |
| Reporting and export | EXISTS + EXTENSION POINT | CAT-02, as the shape to copy |
| Navigation registry, app shell | EXISTS + EXTENSION POINT | CAT-01, CAT-02 |
| i18n | EXISTS + EXTENSION POINT | CAT-01, CAT-02 |
| Email transport | EXISTS | CAT-01 |
| Koras product catalogue, entitlement resolution | EXISTS (Control Plane) | CAT-03 |
| Provider adapter, webhook, reconciliation engine | EXISTS (Control Plane) | CAT-03 |
| **Background job enqueue** | **MISSING** | **CAT-01 P3+, CAT-02 from P1** |
| Retry, dead letter | MISSING | CAT-01, CAT-02 |
| Transactional outbox | MISSING | CAT-01 |
| Domain event bus | MISSING, deferred on purpose | — |
| In-app notifications, toast, banner | MISSING | CAT-01 |
| Notification templates, channels, recipients, delivery log | MISSING or PARTIAL | CAT-01 |
| Import engine, mapping, row errors | MISSING | CAT-02 |
| Server-side pagination, upload primitive | PARTIAL | CAT-02 |
| Lookup keys, outbound idempotency, price provisioner, catalogue drift | MISSING | CAT-03 |
| Application metrics, readiness, correlation id | MISSING | All, and outside this plan |

---

## 4. Reusable shared foundations

Six things every category must reuse rather than reinvent. Each already has a
worked example, and the brief's rule against parallel frameworks is enforced by
naming the example:

| Foundation | The pattern to copy | Where it is already done |
|---|---|---|
| **The registry** | Build once at import; a duplicate key raises with a traceback rather than a 500 for a customer; iteration is deterministically sorted; an unknown key raises rather than defaulting; a starter-owned file plus an empty product-owned file is the extension point | Six times: reporting, audit actions, settings, file hooks, AI, navigation |
| **The row before the artefact** | Insert a status row and commit, do the work, update the row, sign a short-lived download, expire it on a sweep | Audit exports and report exports |
| **The request, the second person, the worker** | A request row, an approval by somebody else, a worker that acts on approved rows only | Restore requests, and legal holds |
| **The capability gate** | A manifest entry, a defaults entry, a template-map path list, `{{#if capability.x}}` in templates, and a generator test that generates both with and without | AI, reporting, audit governance, storage governance |
| **Server-decided visibility** | A pure function deciding hidden, locked or available before any resolver runs, applied identically by the sidebar and the middleware | The reporting visibility rule and the navigation registry |
| **The refusal that says which** | 401 for who you are, 403 for what you may do, 402 for what you have bought, 404 for what you may not know exists | Throughout the API |

**The rule that keeps a capability honest**, written in the product manifest and
worth restating because breaking it has happened: *a table is gated only when no
foundation code and no foundation migration reaches it.* The audit table sat
inside the reporting gate until 2026-09-16, which meant a product generated
without analytics recorded nothing, and the absence looked exactly like an empty
table. CAT-01 and CAT-02 each create tables; each must decide gating by this
rule and write down the answer.

---

## 5. Architectural conflicts

Five, and the first two change the plan.

**5.1 — Starter-first against the billing boundary.** The brief says reusable
capability belongs in the starter first. The billing design says no product ever
holds a provider credential. These cannot both apply to CAT-03. The billing
design wins: the reusable part of billing *is already* in the starter, and it is
the entitlement *reader*. The provider half belongs to the one repository that
holds the key. Recorded so that a later reader does not find CAT-03 in the
Control Plane and conclude the rule was forgotten.

**5.2 — Cron against on-demand.** The worker's product extension point takes
cron jobs only. Every feature that must do work *when something happens* has to
either edit a generated, starter-owned file or poll on a schedule. Both are
wrong, and docoris chose to record the conflict rather than write the
workaround. PLAT-F1 resolves it.

**5.3 — Two background-export implementations.** Report exports and audit
exports each have a table, a status vocabulary, an expiry sweep and a download
route, built independently. Import needs a fourth. Three instances of a pattern
is the point at which either the pattern is extracted or the duplication is
chosen deliberately and written down. The decision is due before CAT-02's
migration is written, and it is a decision, not a defect.

**5.4 — Settings that promise and do not deliver.** The settings framework
introduced an unsurfaced flag with an explicit rationale: a control that changes
nothing is worse than one that is not offered. Six settings ship fully surfaced
and are read by nothing. The framework and its own catalogue disagree.

**5.5 — Audit as record against audit as event.** There is a durable audit table
with no consumers and no dispatch. It is tempting to make notification a
subscriber of it. docoris looked at this and ruled against it, and the ruling is
right: audit stays a direct in-transaction call, and notification gets its own
dispatch point. An audit row that must be delivered is no longer an audit row.

---

## 6. Dependency map

Full detail in `docs/platform/feature-dependency-map.md`. The three edges that
decide the schedule:

| Edge | Class | Consequence |
|---|---|---|
| PLAT-F1 → CAT-02 | **HARD from Phase 1** | CAT-02 waits. Import is a background-job feature |
| PLAT-F1 → CAT-01 | **HARD from Phase 3 only** | CAT-01 starts immediately; Phases 0-2 write rows in the transaction that caused them |
| CAT-01 → CAT-02 | **SOFT** | One emitter interface, five event names, a no-op default. Neither waits |

CAT-03 has no edge into either other category except a SOFT, optional one, and
shares no file with them.

---

## 7. The three categories

### CAT-01 — Notifications and communication

| | |
|---|---|
| **Scope** | In-app notifications with a bell, an unread count, a drawer and a centre; toast and banner primitives; a channel seam with email as the first adapter; a template catalogue; recipient resolution; preferences that are honoured; a dispatch point; an outbox with retry, deduplication and a delivery log; digests; announcements; SMS last |
| **Repositories** | `koras-saas-starter` (owner). `output/koras-e2e-shop` for validation after the gate. `koras-control-plane` for the delivery-health read in Phase 4 |
| **Forbidden** | `docoris`. A second queue, a second audit, a second settings hierarchy, a second telemetry stack |
| **Dependencies** | Everything satisfied except the job contract, which is HARD from Phase 3 |
| **Phases** | P0 contracts and the capability · P1 in-app, toast, banner · P2 channels, templates, recipients, preferences honoured · P3 outbox, delivery log, retry · P4 digests and announcements · P5 SMS |
| **Risks** | The dispatch point becoming an event bus by accident; the template catalogue growing a general-purpose expression language; SMS arriving before consent, quiet hours and a cost ceiling exist |
| **Shared contracts produced** | `NotificationEmitter` — consumed by CAT-02 and by any later feature |

### CAT-02 — Data import and migration

| | |
|---|---|
| **Scope** | Upload, analyze, map, transform, validate, preview, background import, results, retry — for CSV first, then XLSX and JSON; an import-target registry a product declares against; row-level errors and a downloadable error file; duplicate detection; saved mapping profiles; cancellation; chunked resumable processing for large files |
| **Repositories** | `koras-saas-starter` (owner). `output/koras-e2e-shop` for validation, where a real domain to import into already exists |
| **Forbidden** | `docoris`, `koras-control-plane`. No product-specific table name reaches the engine |
| **Dependencies** | HARD on the job contract from Phase 1. SOFT on the notification contract, the upload primitive and the shared data table |
| **Phases** | P0 registry and contract · P1 CSV upload, map, dry run, preview · P2 commit, row errors, error file · P3 XLSX and JSON, mapping profiles, retry, cancellation · P4 chunked and resumable |
| **Risks** | A partial commit, which the requirements forbid outright; a 300-second job timeout against a fifty-thousand-row file; parsing an unscanned file; a preview that tries to render the whole file through a client-paginated table |
| **Shared contracts produced** | `ImportTarget` — the declaration a product makes so the engine never knows a product table |

### CAT-03 — Stripe product and price provisioning

| | |
|---|---|
| **Scope** | Deterministic lookup keys; idempotency on outbound calls; a provisioner that reads the Koras catalogue and creates provider products and prices; reconciliation and drift detection for the catalogue; price versioning and grandfathering; multiple currencies; a free-plan and custom-price path; a console view of the event log; the go-live runbook |
| **Repositories** | `koras-control-plane` (owner). `koras-saas-starter` for exactly one documentation correction |
| **Forbidden** | Any product repository. No provider credential, no price id and no amount may reach one |
| **Dependencies** | All satisfied. The catalogue, the adapter, the webhook, the environment guard and the reconciliation engine all exist |
| **Phases** | P0 documentation correction · P1 lookup keys, idempotency, one entitlement catalogue · P2 provisioner and catalogue drift · P3 versioning, currency, free plan · P4 console and go-live |
| **Risks** | A provisioner that deletes; a dev run reaching live mode; a price change that silently rewrites what existing customers were sold; the two entitlement catalogues drifting further |
| **Shared contracts produced** | None. It consumes the notification contract if CAT-01 lands first, and implements it locally if not |

---

## 8. Parallel execution recommendation

| Work | Verdict |
|---|---|
| PLAT-F1 job contract | **START FIRST**, alone, one to two days |
| CAT-01 Phases 0-2 | **CAN START INDEPENDENTLY**, alongside PLAT-F1 |
| CAT-03, all phases | **CAN START INDEPENDENTLY**, different repository |
| CAT-01 Phase 3 and later | **CAN START AFTER** PLAT-F1 |
| CAT-02, all phases | **MUST WAIT** for PLAT-F1 |
| CAT-02 against CAT-01 | **PARALLEL WITH CONTRACT** |
| Anything touching `docoris` | **BLOCKED**, and deliberately |

The schedule and the file-ownership map are in
`docs/platform/parallel-execution-plan.md`.

---

## 9. Shared contracts

Four, written here so that a SOFT dependency is genuinely soft. Each is repeated
in the manifest of the category that consumes it. Names are proposed and become
binding when PLAT-F1 and CAT-01 Phase 0 land.

**9.1 — The job contract (PLAT-F1, owned by Platform).**
An enqueue function callable from a request, taking a task name, a tenant, a
payload and an optional idempotency key; a product-owned task list beside the
existing cron list, so that no category edits the generated worker file; and a
declared retry policy per task rather than inherited defaults. A job declares a
tenant or its transaction refuses to open, which the worker already enforces at
startup. Closes docoris OD-19.

**9.2 — The notification emitter (CAT-01 Phase 0, owned by CAT-01).**
One in-process dispatch point every caller uses, with three rules taken from the
docoris design because they are right: notification subscribes and audit does
not; a notification never fails the transition that caused it; and an
unresolvable recipient alerts an administrator rather than being dropped. The
default implementation is a no-op, so a category may emit before CAT-01 exists.

**9.3 — The import target (CAT-02 Phase 0, owned by CAT-02).**
A product declares what may be imported: the target, the operations allowed, the
match keys, the allowed and required fields, and the permission the execute
needs. The engine never names a product table. This is the same shape as the
product reports list and the product settings list, and it is what keeps the
engine promotable and the targets local.

**9.4 — The billing catalogue contract (CAT-03 Phase 1, owned by CAT-03).**
The Koras catalogue is the system of record; the provider holds a representation
of it. A lookup key is derived deterministically from product, plan, interval
and currency. The provisioner creates and updates; it never deletes, and it
never reads the provider as truth. Reconciliation classifies every finding as
safe to repair, requiring review, or manual.

---

## 10. Repository ownership

| Area | Owner | Rule |
|---|---|---|
| `koras-saas-starter` templates, generator, manifests | Platform, with category leads submitting blocks | The manifest and the migration numbering go through one hand |
| Notification code, tables, UI, templates | CAT-01 | — |
| Import code, tables, UI, registry | CAT-02 | — |
| `koras-control-plane` entirely | CAT-03 | No other category enters that repository |
| `output/koras-e2e-shop` | Integration | Synced once, after the gate, by hand-carried commit |
| `docoris` | Nobody, by default | A real product. Read for requirements, never written to validate the factory |
| `docs/platform/` | Shared | Append and update own rows; never renumber |

The detailed file-level map, including the reserved migration ranges, is in
`docs/platform/parallel-execution-plan.md`.

---

## 11. Master roadmap

| # | Work item | Category | Depends on | Parallel | Repository | Phase |
|---|---|---|---|---|---|---|
| 1 | Job contract: enqueue seam, task registry, retry policy | Platform | Worker, tenant context (both exist) | Yes | starter | Foundation |
| 2 | Registry conventions written down once | Platform | — | Yes | starter | Foundation |
| 3 | Documentation corrections (restore, dependency map, billing phases, signup header) | Platform, CAT-03 | — | Yes | starter, control plane | Foundation |
| 4 | Unsurface the six settings nothing reads | Platform | — | Yes | starter | Foundation |
| 5 | Notification contract and the capability made real | CAT-01 | 2 | Yes | starter | 0 |
| 6 | Notification store, bell, drawer, centre, toast, banner | CAT-01 | 5 | Yes | starter | 1 |
| 7 | Channels, templates, recipients, preferences honoured | CAT-01 | 6 | Yes | starter | 2 |
| 8 | Outbox, delivery log, retry, deduplication | CAT-01 | 1, 7 | Yes | starter | 3 |
| 9 | Digests and announcements | CAT-01 | 8 | Yes | starter, control plane | 4 |
| 10 | SMS adapter | CAT-01 | 7 | Yes | starter | 5 |
| 11 | Import target registry and contract; the fourth-table decision | CAT-02 | 2 | Yes | starter | 0 |
| 12 | CSV upload, mapping, validation, dry run, preview | CAT-02 | 1, 11 | Yes | starter | 1 |
| 13 | Commit, row errors, downloadable error file | CAT-02 | 12 | Yes | starter | 2 |
| 14 | XLSX and JSON, mapping profiles, retry, cancellation | CAT-02 | 13 | Yes | starter | 3 |
| 15 | Chunked, resumable processing | CAT-02 | 14 | Yes | starter | 4 |
| 16 | Lookup keys, outbound idempotency, one entitlement catalogue | CAT-03 | — | Yes | control plane | 1 |
| 17 | Catalogue provisioner and catalogue drift check | CAT-03 | 16 | Yes | control plane | 2 |
| 18 | Price versioning, currencies, free plan | CAT-03 | 17 | Yes | control plane | 3 |
| 19 | Event console and go-live | CAT-03 | 18, F21 | Partly | control plane | 4 |
| 20 | Integration gate: one product carrying all of it | Integration | 6-15 | No | starter | Gate |
| 21 | Regression: both profiles, with and without each capability | Integration | 20 | No | starter | Gate |
| 22 | Sync the reference product | Integration | 21 | No | koras-e2e-shop | Gate |

---

## 12. Documentation created and updated

Created on 2026-09-19:

```
docs/platform/README.md
docs/platform/master-platform-plan.md
docs/platform/master-capability-matrix.md
docs/platform/feature-dependency-map.md
docs/platform/parallel-execution-plan.md
docs/platform/gap-defect-register.md
docs/platform/execution/CAT-01-notifications.md
docs/platform/execution/CAT-02-data-import.md
docs/platform/execution/CAT-03-stripe-billing.md
docs/adr/0008-koras-platform-job-and-notification-contracts.md
```

Updated on 2026-09-19:

```
CLAUDE.md                  the restore claim corrected, with the correction recorded
docs/features/README.md    a pointer to docs/platform/ in the division-of-labour table
```

No document was duplicated. `docs/BILLING_DESIGN.md`, `docs/ARCHITECTURE.md`,
`docs/IMPLEMENTATION_ROADMAP.md` and `docs/RISK_REGISTER.md` each carry a
correction or an entry that the categories will make as their first phase, and
each is named in the register rather than edited speculatively by a planning
pass.

---

## 13. Gap and defect register

45 findings, in `docs/platform/gap-defect-register.md`: 31 gaps, 12 defects,
2 debt items. Four are Critical — the absent enqueue, the six unread settings,
the split entitlement catalogue and the absent outbound idempotency — and only
the first blocks a category from starting. One is already fixed.

---

## 14. Category execution manifests

All three created:

```
docs/platform/execution/CAT-01-notifications.md
docs/platform/execution/CAT-02-data-import.md
docs/platform/execution/CAT-03-stripe-billing.md
```

Each carries its own scope, allowed and forbidden repositories, dependencies
with classes, contracts, phases, stories, criteria, security requirements,
database impact, test plan, rollout and rollback, sync requirements, definition
of done, and its own gap rows.

---

## 15. Implementation readiness

| Category | Verdict | Why |
|---|---|---|
| **PLAT-F1** | **READY** | Nothing blocks it. The worker, the extension-point pattern and the tenant enforcement all exist |
| **CAT-01 Phases 0-2** | **READY** | Every foundation exists. Phases 0-2 need no queue |
| **CAT-01 Phases 3-5** | **READY WITH DEPENDENCY** | HARD on PLAT-F1, which is one to two days |
| **CAT-02** | **BLOCKED** on PLAT-F1, and on one decision | Import cannot honestly start without an enqueue seam. The decision, due at Phase 0, is whether its run table is a third instance of an existing pattern or the reason to extract it |
| **CAT-03** | **READY** | Different repository, every dependency satisfied. Phase 4's go-live half is gated by F21, which is a person at a dashboard, and the first three phases do not wait for it |

---

## 16. Suggested agent allocation

The product profile ships a 40-agent framework with an orchestration contract,
a registry and a documentation policy. This plan uses it rather than inventing
roles. The factory itself carries only the four common agents, so a factory
category lead is a person or a session, and the specialist agents named below
are the ones a *generated product* would use for the same work.

| Slot | Assignment | Agents from the registry |
|---|---|---|
| A | PLAT-F1 job contract, then platform-owned shared edits | `solution-architect`, `backend-specialist`, `devops-cicd` |
| B | CAT-01 notifications | `solution-architect`, `data-architect`, `backend-specialist`, `frontend-specialist`, `ux-ui-designer` |
| C | CAT-02 data import | `data-architect`, `backend-specialist`, `frontend-specialist`, `workflow-specialist` |
| D | CAT-03 Stripe provisioning, in the other repository | `integration-specialist`, `security-architect`, `backend-specialist` |
| E | Test and review across all four | `unit-test`, `api-integration-test`, `e2e-test`, `security-test`, `code-reviewer`, `architecture-reviewer`, `security-reviewer` |
| F | Integration and sync | `integration-regression`, `migration-upgrade`, `release-manager`, `final-acceptance` |
| G | Documentation | `technical-writer`, `test-documentation` |

The developer pool is three workers isolated by git worktree, which matches the
three parallel slots B, C and D exactly.

---

## 17. Recommended execution order

1. **PLAT-F1**, alone and first. It is small, two categories need it, and
   without it both write a workaround that has to be removed.
2. **In parallel, immediately:** CAT-01 Phase 0-1 and CAT-03 Phase 0-1. Neither
   touches the other; one is in another repository.
3. **The four documentation corrections and the six settings**, by whoever
   reaches them. None takes an hour and each is a claim the repository made on
   2026-09-19 and could not support.
4. **CAT-02 Phase 0**, the moment PLAT-F1 lands — starting with the decision it
   owes about the run table.
5. **Everything else in parallel**, governed by the file-ownership map.
6. **The integration gate**, which cannot be parallel: one generated product
   carrying all of it, through lint, typecheck, tests, the RLS suite against a
   real Postgres, and the browser suite at two widths.
7. **The reference product sync**, once, after the gate.

---

## 18. Next three features

After this plan, and before anything else in these three categories:

1. **PLAT-F1 — the background job contract.** An enqueue seam, a product task
   registry beside the cron registry, and a declared retry policy. It unblocks
   CAT-02 entirely and CAT-01's Phase 3, closes a gap a real product raised as
   its own OD-19, and removes the only reason either category would edit a
   starter-owned file. One to two days, and everything else is cheaper after it.

2. **CAT-01 Phase 1 — in-app notifications, with the toast and banner
   primitives.** The single largest visible hole in a generated product: there
   is no bell, no feed, no read state, and thirty hand-rolled alert regions
   where a toast should be. It needs nothing that does not exist, it gives the
   `notifications` capability something to gate, and it gives every later
   feature — import completion included — somewhere to say what happened.

3. **CAT-03 Phase 1 — lookup keys, outbound idempotency, and one entitlement
   catalogue.** Three small changes in the Control Plane with an outsized
   payoff: a retried checkout stops being able to create a second subscription,
   prices stop being addressed by a hand-pasted id, and the two places that
   disagree about which entitlements a new product gets become one. The
   reporting entitlements being absent from the seed means a product registered
   today is not granted the reports it ships with, and nothing goes red.

All three are independent of each other and can run at once.
