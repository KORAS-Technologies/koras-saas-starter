# Platform gap and defect register

| | |
|---|---|
| **Purpose** | Every gap, defect, debt item and decision found by the master platform audit of 2026-09-19, each with one ID, one severity, one owner and one status. |
| **Opened** | 2026-09-19, by the master planning pass covering CAT-01 notifications, CAT-02 data import and CAT-03 Stripe provisioning. |
| **Scope** | Findings scoped to one of the three categories, plus cross-cutting findings that block more than one. |

## Rules of this register

- **IDs are never reused or renumbered.** `PLAT-*` is cross-cutting, `NOTIF-*`,
  `IMPORT-*` and `BILL-*` are per category. `-GAP-` is something absent,
  `-DEF-` is something present and wrong, `-DEBT-` is something present and
  known to be the wrong shape.
- **This register does not restate the other three.** `docs/RISK_REGISTER.md`
  owns defects found in operation, `docs/FOLLOW_UPS.md` owns deliberate
  omissions, `docs/SYNC_BACKLOG.md` owns cross-repository drift. Where a
  finding belongs to one of those, the row points at it and adds nothing.
- **A gap is not a requirement.** A gap that becomes work is delivered by a
  phase in a category manifest, and the row records which phase.
- **Every row says how it was established.** "Verified by search" means a grep
  across `profiles/`, `generators/` and `tooling/` returned nothing; a claim
  that something is absent is a claim, and an unchecked one decays like any
  other.
- Statuses: `OPEN`, `PLANNED` (a phase owns it), `IN_PROGRESS`, `BLOCKED`,
  `FIXED`, `VERIFIED`, `DEFERRED`, `WONT_FIX`.

## Summary

45 rows as of 2026-09-19. By type: 31 GAP, 12 DEF, 2 DEBT. By severity:
4 Critical, 16 High, 18 Medium, 7 Low.

The four Critical rows are PLAT-GAP-001, PLAT-DEF-001, BILL-DEF-001 and
BILL-GAP-002. Only the first blocks a category from starting.

**One row has since been withdrawn.** BILL-DEF-002 was opened from an audit
report and did not survive being checked against the migrations on 2026-09-19.
It is struck through rather than deleted, because a register that quietly loses
rows is one nobody can audit.

---

## Cross-cutting — PLAT

| ID | Type | Title | Severity | Evidence | Resolution | Phase | Status |
|----|------|-------|----------|----------|------------|-------|--------|
| PLAT-GAP-001 | GAP | Nothing can enqueue a background job. The ARQ enqueue call, pool constructor and client type appear nowhere in the repository — ARQ runs cron only, and every asynchronous request path uses FastAPI background tasks, which die with the process. | Critical | Verified by search across `profiles/`, `generators/` and `tooling/` on 2026-09-19. The worker's function list holds one stub, `example_task`. | **Built 2026-09-19.** `koras-queue` carries the seam, the API opens one queue per process, and `tasks/product.py` gained `PRODUCT_TASKS` beside the cron list. Closes docoris OD-19 and GR-002. | PLAT-F1 | FIXED |
| PLAT-GAP-002 | GAP | `koras-queue` is a one-line comment file, and four package manifests declare a dependency on it — the product API, the Control Plane API, the worker and the scheduler. | High | The shared layer holds the source file with one comment in it; the product and control-plane layers hold only a manifest. | **Built 2026-09-19.** It carries the seam, and both profile manifests now declare the queue library rather than one of them declaring nothing at all. | PLAT-F1 | FIXED |
| PLAT-GAP-003 | GAP | No retry, backoff or dead-letter configuration anywhere. The queue library's defaults are taken implicitly, and a 300-second job timeout is the only bound expressed. | High | Verified by search for the retry, result-retention and dead-letter settings. | **Built 2026-09-19.** A retry policy is declared per task and applied by the wrapper, which the queue library does not do on its own; a terminal failure logs the task, the tenant and the attempt count. **No dead-letter queue**, deliberately: a destination nothing reads is not evidence, and every task that matters owns a row whose status is where a person actually looks. | PLAT-F1 | FIXED |
| PLAT-GAP-004 | GAP | No transactional outbox. The mail package's own docstring records that delivery is at-least-once and that a caller who must not repeat a message has to arrange that itself — and nothing does. | High | Verified by search for an outbox table, a relay, and sent-at or processed-at columns. | CAT-01 Phase 3 builds one for notifications. Generalising it beyond notifications waits for a second subject. | CAT-01 P3 | PLANNED |
| PLAT-GAP-005 | GAP | No domain event spine. There is an audit record with no consumers, a file-hook registry covering two moments in the life of one subject, and a task queue. None of the three is a bus. | Medium | Verified by search for the publish, subscribe and emit vocabulary. Matches docoris OD-3 and GR-064. | Deliberately not built by this plan. CAT-01 gives notification one in-process dispatch point, which an outbox or a bus can later sit behind without changing its callers. | — | DEFERRED |
| PLAT-GAP-006 | GAP | The run-a-job-and-record-its-outcome pattern exists twice, independently: report exports and audit exports each have their own table, status vocabulary, expiry sweep and download route. A third subject would make three. | Medium | `00014_report_schedules.sql` and `00022_audit_exports.sql`; `core/audit_export.py` and the export half of `routers/reporting.py`. | CAT-02 needs a fourth. Extract the shape, or accept the duplication deliberately and write down why. Decide before the import tables are designed. | CAT-02 P0 | OPEN |
| PLAT-GAP-007 | GAP | No application metrics, no readiness probe distinct from liveness, no dependency health in the health route, and no correlation id propagated across a request. | Medium | `packages/observability` and `koras-observability` are stubs; `main.py.hbs` records that a request-id header is deliberately absent; the metrics route is the reporting catalogue, not Prometheus. Named in `docs/features/STATUS.md` as the blocker on two stories. | Outside these three categories, and named because each of them defines observability requirements that this bounds. | — | OPEN |
| PLAT-GAP-008 | GAP | The scheduler service ships two jobs whose bodies are `pass`. It is required and on by default in the control-plane profile. | Low | `profiles/_shared/template/services/scheduler/koras_scheduler/main.py`. The real Control Plane repository has a working scheduler; the template it was generated from does not. | A `docs/SYNC_BACKLOG.md` question rather than a starter build: decide whether the template should carry what the Control Plane grew. | — | OPEN |
| PLAT-DEF-001 | DEFECT | Six settings are registered, translated into en, de and es, and drawn on the settings pages, and **no code reads any of them**: three under `notifications` and three under `files`. | Critical | Verified 2026-09-19: the only references outside the declaration are the message catalogues, the TypeScript key union and two tests. The upload route enforces a hardcoded 5 GiB and never consults the size setting. | **Half fixed 2026-09-19**: the three `notifications.*` are resolved — one honoured, two unsurfaced. The three `files.*` are untouched and still drawn: the upload route enforces a hardcoded 5 GiB and consults none of them. CAT-02 Phase 1 owns the rest. | CAT-01 P1 (done), CAT-02 P1 | OPEN |
| PLAT-DEF-002 | DEFECT | `CLAUDE.md` states that restore does not ship and is blocked on ADR 0006 question 3. Restore ships: a migration, a router, a worker task, a page and a browser test, all listed in the storage-governance template map. | High | `CLAUDE.md:293` against `00026_restore_requests.sql`, `routers/restore.py`, `tasks/storage_restore.py`, the restore page and `e2e/restore.spec.ts`. Found independently by the docoris audit, which wrote "Believe the code." | Corrected on 2026-09-19, with the correction recorded rather than made silently — the convention R-042 established for this file. | — | FIXED |
| PLAT-DEF-003 | DEFECT | `docs/DEPENDENCY_MAP.md` documents a dependency graph for eleven TypeScript packages that are two-line stubs declaring no dependencies at all. | Medium | `docs/DEPENDENCY_MAP.md:60-77` against the eleven package manifests. | **Fixed 2026-09-19** by the first option: the table says it is the intended graph, names the eleven stubs, marks each row with a dagger, and says where the substance actually is. The rows stay because the *direction* is the decision; a package growing real content is a row that stops being marked. | — | FIXED |
| PLAT-DEF-004 | DEFECT | Two of R-042's four mechanical documentation checks read only the top level of `docs/`. Every file under `docs/features/` and `docs/platform/` is unchecked for invented paths and invented identifiers. | Medium | `tests/docs/file-references.test.ts:120-125` and `tests/docs/identifiers.test.ts:175-178` both read the directory without recursing; `tests/docs/hedged-claims.test.ts` does recurse. | Make both walk the tree as the hedge check does. Expect a first run to find real breakage in the six feature documents already there. | — | OPEN |
| PLAT-DEF-005 | DEFECT | The product manifest describes the API service as a REST and WebSocket API. No WebSocket server or client exists; the only streaming is server-sent events on the assistant route. | Low | Verified by search; the four matches are all server-sent events. | One word in a manifest description. | — | OPEN |
| PLAT-DEF-006 | DEFECT | The `notifications` capability is declared true in both profile manifests, has no template-map entry and no defaults entry. It gates nothing, and excluding it removes nothing while appearing to succeed. | High | `profiles/product/manifest.yaml:47` and `profiles/control-plane/manifest.yaml:49`; no capability entry in either template map; the only artefact is a two-line stub package. | **Fixed 2026-09-19.** The capability gates seven paths, has a defaults entry, and `requires` refuses `--with ai --without notifications`. Verified by generating three variants: with, without, and with the assistant — all three lint, typecheck and build, and the `--without` variant carries none of the seven files. | CAT-01 P0 | FIXED |
| PLAT-DEF-007 | DEFECT | A generated product's own Node tests were red on `develop`. `navigation.test.ts` asserts the resolved sidebar as an exact list, and the settings framework added a `preferences` module to the registry on 2026-09-19 without updating it. | High | Found on 2026-09-19 by running a freshly generated product's `pnpm turbo run test` while adding a second module — two assertions failed, and only one of the two extra entries was the new work. | **Fixed 2026-09-19**: the expectation names the ungated administration modules in one place rather than in two literals, so the next one is added once. The wider point is that the starter's own suite is green while the thing it generates is not, and only a generation run closes that gap. | — | FIXED |
| PLAT-DEBT-001 | DEBT | The API declares a FastAPI floor at which, this repository records, every route returning nothing with a 204 fails at import. **It did not reproduce.** | Medium | Recorded in `CLAUDE.md` and inherited by docoris as GR-067. Checked on 2026-09-19 while adding a third such route: 0.115.0, 0.115.1, 0.115.2 and 0.115.4 all import a 204 route returning `None`, bare and with dependencies through `include_router`. | Either the claim is wrong or it needs a condition nobody wrote down. The floor was **not** moved, because moving it would assert the premise. Re-verify against the exact dependency set that produced the report, then correct `CLAUDE.md` or raise the floor with evidence. | — | OPEN |
| PLAT-DEBT-002 | DEBT | Six import-time registries share one set of conventions — build once, duplicate key raises, sorted iteration, unknown key raises, empty product-owned extension file — and the conventions are written down nowhere but in each registry's own docstring. | Low | The reporting, audit-action, settings, file-hook, AI and navigation registries. | CAT-01 and CAT-02 each add a seventh and an eighth. Write the convention down once, in `docs/ARCHITECTURE.md`, before they do. | CAT-01 P0 | PLANNED |

---

## CAT-01 Notifications — NOTIF

| ID | Type | Title | Severity | Evidence | Resolution | Phase | Status |
|----|------|-------|----------|----------|------------|-------|--------|
| NOTIF-GAP-001 | GAP | No in-app notifications of any kind: no table, no feed, no read state, no bell, no drawer, no centre. | High | 31 product migrations, none for notifications; `packages/notifications` is a stub; the bell glyph exists in the icon union and is rendered by nothing. | **Built 2026-09-19.** `00032_notifications.sql`, a kind registry and store, four routes, a bell with an unread count, a drawer and a notification centre, plus a nightly sweep in two windows. | CAT-01 P1 | FIXED |
| NOTIF-GAP-002 | GAP | No notification or email template catalogue. The one real transactional mail composes its HTML inline. | High | `core/notify.py` builds a table-based HTML document in a private helper; the mail message catalogue holds sixteen keys, fourteen of them for one feature. | Phase 2 adds a template registry following the reporting and settings registry conventions. | CAT-01 P2 | PLANNED |
| NOTIF-GAP-003 | GAP | No channel abstraction. The mail package is SMTP and the call site knows it. | Medium | The sender factory returns an SMTP sender or a recording sender; there is no channel type. | Phase 2 introduces the channel seam, with email as the first implementation, so that SMS and in-app are adapters rather than a second engine. | CAT-01 P2 | PLANNED |
| NOTIF-GAP-004 | GAP | No recipient resolution. The one place that needs recipients asks the platform for the member list and filters it by a hardcoded permission. | Medium | `core/notify.py` resolves owners plus holders of one permission, in one function, for one event. | Phase 2 generalises it into a recipient resolver taking a rule rather than a hardcoded permission. | CAT-01 P2 | PLANNED |
| NOTIF-GAP-005 | GAP | No delivery log. The message id the sender returns is discarded at every call site; there is no per-message record, no bounce handling and no provider callback. | High | The sender result type against its two call sites. SMTP offers no delivery callback, so a log is the only evidence a message existed. | Phase 3 writes a delivery row before the send and updates it after. | CAT-01 P3 | PLANNED |
| NOTIF-GAP-006 | GAP | No SMS capability. | Low | Verified by search for the four common providers. | Phase 5, deliberately last, and behind the channel seam built in Phase 2. | CAT-01 P5 | PLANNED |
| NOTIF-GAP-007 | GAP | No toast and no banner primitive. Roughly thirty hand-rolled alert and live regions do the job, each differently. | Medium | Across the login form, the settings page, the audit panel and the data table. No toast library is a dependency of anything. | **Built 2026-09-19** — `Banner` and `ToastProvider` in `packages/ui`, with the toast/banner/notification division written into both. The thirty existing call sites are **not** migrated, as planned: this gives the next one somewhere to go. | CAT-01 P1 | FIXED |
| NOTIF-GAP-008 | GAP | The Control Plane can publish nothing to a product: no announcement, no maintenance banner, no platform message. | Medium | Verified by search across the control-plane template; the real Control Plane repository has none either. | Phase 4, as a read on the existing platform contract rather than a push. | CAT-01 P4 | PLANNED |
| NOTIF-GAP-009 | GAP | The digest-frequency setting offers never, daily and weekly, and no digest job exists. | Medium | Verified by search; the only matches for digest are checksum code. | Phase 4. | CAT-01 P4 | PLANNED |
| NOTIF-DEF-001 | DEFECT | The three notification preference settings are drawn on the preferences page and read by nothing. The approval mail is sent without consulting the email-enabled toggle. | Critical | Instance of PLAT-DEF-001, verified 2026-09-19. | **Fixed 2026-09-19.** `notifications.inAppEnabled` is honoured — the layout reads it and does not draw the bell, and the centre says why it is empty. The other two are marked unsurfaced until Phase 2's channel seam and Phase 4's digest job exist. No control is now offered that changes nothing. | CAT-01 P1 | FIXED |
| NOTIF-DEF-002 | DEFECT | The approval notice writes no audit event. It runs in a background task after the response, so a failure is a log line and there is no record that a notice was attempted, to whom, or whether it was real or simulated. | High | `core/notify.py` logs and swallows; no email or notification action key exists in the foundation audit registry. Report delivery, by contrast, records its own action. | Phase 1 registers notification audit actions; Phase 3 records every dispatch. | CAT-01 P1 | OPEN |
| NOTIF-DEF-003 | DEFECT | The approval notice is composed in the *requester's* accepted language rather than each recipient's stored language, although the member language preference has existed since F20 closed on 2026-09-15 and now lives in the settings framework. | Medium | `core/notify.py:26-31` records the reason, which was true when written and stopped being true when F20 landed. | Phase 2 resolves the recipient's language through the settings resolver. | CAT-01 P2 | OPEN |
| NOTIF-DEF-004 | DEFECT | `docs/DEPENDENCY_MAP.md` declares that notifications depends on email and config. The package declares no dependencies and imports nothing. | Low | Instance of PLAT-DEF-003. | **Fixed 2026-09-19** by correcting the map, not by building the package: in-app notifications are a table and a router in the API and components in `packages/ui`, and none of the feature is in `packages/notifications`, which is still two lines. PLAT-DEF-003 carries the general fix. | CAT-01 P0 | FIXED |

---

## CAT-02 Data Import — IMPORT

| ID | Type | Title | Severity | Evidence | Resolution | Phase | Status |
|----|------|-------|----------|----------|------------|-------|--------|
| IMPORT-GAP-001 | GAP | No import capability of any kind: no parser, no mapping model, no staging table, no dry run, no router, no page. | High | Verified by search for the format, mapping and bulk vocabulary across all three profiles. | The whole of CAT-02. | CAT-02 P1-P4 | PLANNED |
| IMPORT-GAP-002 | GAP | The imports value in the closed storage category enum is declared and used by nothing. | Low | Verified by search; only the documents and exports values are used. | Phase 1 uses it. The key segment, retention, hold and reconciliation all come free with it. | CAT-02 P1 | PLANNED |
| IMPORT-GAP-003 | GAP | The only spreadsheet reader in the repository parses workbooks into text for AI embedding. There is no structured-record reader. | Medium | `core/knowledge.py` loads a workbook; the spreadsheet library is a declared dependency of the API and of the reporting package, which writes but does not read. | Phase 1 reads CSV; Phase 3 reads XLSX, reusing the dependency that is already declared. | CAT-02 P1, P3 | PLANNED |
| IMPORT-GAP-004 | GAP | No field-mapping model and no saved mapping profiles. | Medium | Consequence of IMPORT-GAP-001. | Phase 1 maps; Phase 3 saves the mapping per tenant per target. | CAT-02 P1, P3 | PLANNED |
| IMPORT-GAP-005 | GAP | No row-level error model and no downloadable error file. | Medium | Consequence of IMPORT-GAP-001. The shape to copy exists: audit exports write the row before the artefact and expire it on a sweep. | Phase 2. | CAT-02 P2 | PLANNED |
| IMPORT-GAP-006 | GAP | The shared data table paginates on the client: it takes the whole array and slices it. It has no total, no page-change callback, no loading state, no sort, no filter and no selection. An import preview cannot be drawn through it beyond a few thousand rows. | High | `packages/ui/src/data-table/data-table.tsx`; its docstring names the lift-the-state seam without building it. | Phase 1 previews a bounded head of the file rather than the file. Server pagination is a shared-component change and is called out in the ownership map. | CAT-02 P1 | PLANNED |
| IMPORT-GAP-007 | GAP | There is no upload component in `packages/ui`. The one file input in the repository is a hidden single-file input on the Files page; no drag and drop, no multi-file, no shared primitive. | Medium | `apps/web/src/app/dashboard/files/FilesPanel.tsx.hbs`. | Phase 1 extracts the existing ticket-and-progress flow into a shared upload primitive rather than writing a second one. | CAT-02 P1 | PLANNED |
| IMPORT-GAP-008 | GAP | No import permission. The catalogue holds sixteen strings and none of them covers importing. | Medium | `packages/permissions/src/index.ts` and its Python mirror. | Phase 1 adds one permission to both languages, which the generator's structural test then keeps level, and a route that checks it. | CAT-02 P1 | PLANNED |
| IMPORT-GAP-009 | GAP | No chunking and no resumability. The 300-second job timeout makes a single-job validation of a large file unsafe, and no sweep in the repository takes a skip-locked cursor. | High | The worker settings; verified by search. | Phase 4, with a per-run cursor. Phases 1 and 2 bound the row count instead and refuse rather than truncate — the rule audit exports already follow. | CAT-02 P4 | PLANNED |
| IMPORT-GAP-010 | GAP | No job cancellation anywhere. | Medium | Verified by search. | Phase 3 cancels by state rather than by killing a job: a cancelled run is not picked up, and a running one finishes its batch and stops. | CAT-02 P3 | PLANNED |
| IMPORT-GAP-011 | GAP | No malware scanner. The scan module is a seam, the withheld set holds only the infected status, and a pending file may be downloaded by design. An import would parse unscanned bytes. | High | `core/file_scan.py`; matches docoris GR-055 and OD-10, both Critical there. | Phase 1 refuses to parse a file whose scan is pending or skipped — narrower than the platform default, and it does not require a scanner to exist. | CAT-02 P1 | PLANNED |
| IMPORT-DEF-001 | DEFECT | The three file settings — maximum upload size, allowed extensions and files per upload — are drawn on the settings page and enforced by nothing; the upload route applies a hardcoded 5 GiB ceiling. | Critical | Instance of PLAT-DEF-001, verified 2026-09-19. | Phase 1 enforces all three at the presign route, which is where a ceiling can still refuse cheaply. | CAT-02 P1 | OPEN |

---

## CAT-03 Stripe Provisioning — BILL

Every row below is in `koras-control-plane` unless the row says otherwise. The
starter holds no billing code, by an architectural decision recorded in
`docs/BILLING_DESIGN.md`: no product holds a provider credential and no product
calls the provider.

| ID | Type | Title | Severity | Evidence | Resolution | Phase | Status |
|----|------|-------|----------|----------|------------|-------|--------|
| BILL-GAP-001 | GAP | No Stripe lookup keys. Prices are addressed by raw provider id, pasted into the console by hand. | High | Verified by search across the Control Plane's Python, SQL and documentation. | **Half built 2026-09-19.** `price_lookup_key(product, plan, interval, currency)` exists, is pure, and is tested — including that it is stable across environments and that a hyphenated product name still splits into four parts. **Nothing calls it**: the provisioner that creates prices is Phase 2, and the key was decided first on purpose so it is not shaped by the first thing that uses it. Storing it on the plan row is Phase 2. | CAT-03 P1 / P2 | IN_PROGRESS |
| BILL-GAP-002 | GAP | No idempotency key on any outbound provider call. A retried checkout or subscription change creates a second provider object. | Critical | Verified by search in the adapter's provider implementation. Inbound idempotency is sound — the event id is stored before the event is acted on — so the gap is one-directional. | **Fixed 2026-09-19.** Every creating or changing call carries an `Idempotency-Key` derived from a digest of method, path and body — so the same request collapses and a genuinely different one is a different key, which is what stops Stripe refusing the second. The portal session is deliberately excluded: a key would replay an expired link. | CAT-03 P1 | FIXED |
| BILL-GAP-003 | GAP | There is no provisioner. A provider product and its prices are created by hand in the dashboard and their ids pasted into the console plan form. | High | The go-live runbook's step 2 is exactly that sequence; nothing in the code creates a price. | Phase 2 reads the Koras catalogue and creates what is missing, with a dry run, and never the reverse direction. | CAT-03 P2 | PLANNED |
| BILL-GAP-004 | GAP | Drift detection covers subscriptions only. The reconciliation engine has one billing check with automatic repair; no check compares a catalogue plan against its provider product or price. | High | The reconciliation check registry holds one billing check. | Phase 2 adds a catalogue check classifying findings as safe, review-required or manual, and never deleting a provider resource. | CAT-03 P2 | PLANNED |
| BILL-GAP-005 | GAP | No price versioning and no grandfathering. A plan row holds one monthly and one yearly price id; changing a price replaces the reference for everyone who reads it. | High | The plan columns added by the billing migration. Existing subscriptions keep their own price at the provider, so the practical exposure is the catalogue's memory of what was sold rather than the amount charged. | Phase 3 makes the mapping a history rather than a column pair. | CAT-03 P3 | PLANNED |
| BILL-GAP-006 | GAP | Single currency. Nothing in the catalogue expresses a price set per currency. | Medium | The two price id columns carry no currency. | Phase 3, with the Phase 1 lookup key carrying the currency segment from the start so that the change is additive. | CAT-03 P3 | PLANNED |
| BILL-GAP-007 | GAP | No console page over the billing event log. The API lists events; nothing renders them. | Low | Named in the Control Plane's own billing document as outstanding. | Phase 4. | CAT-03 P4 | PLANNED |
| BILL-GAP-008 | GAP | Live mode. The account has neither charges enabled nor details submitted; test mode carries a catalogue, a webhook endpoint, six completed browser checkouts and recorded fixtures. | High | Read from the Control Plane's billing document, verified 2026-09-15. This is `docs/FOLLOW_UPS.md` F21, and it is a person at a dashboard rather than code. | Pointer row. F21 owns it. | — | OPEN |
| BILL-GAP-009 | GAP | A free plan and an enterprise custom price have no path through checkout: the checkout opener requires a price, and a plan without one falls back to provisioning with no card. | Medium | The signup router's price lookup and its fallback branch. | Phase 3 decides whether a free plan is a plan with a zero price or a plan that skips checkout. | CAT-03 P3 | PLANNED |
| BILL-DEF-001 | DEFECT | The five reporting entitlements exist only in a migration. They are absent from the in-code entitlement catalogue that seeds a newly registered product, so a product registered after that migration is not granted them. | Critical | The migration seeds five codes; the in-code catalogue holds six codes and none of them is a reporting one. | **Fixed 2026-09-19.** The five codes are in `ENTITLEMENT_CATALOGUE` with the grants the migration makes, so a newly registered product is seeded them. A new test asserts the two sources agree, which nothing did before. | CAT-03 P1 | FIXED |
| BILL-DEF-002 | ~~DEFECT~~ | Two entitlement-seeding migrations were reported as granting against a plan code that a later migration renamed. **Not a defect.** | — | Checked on 2026-09-19 before acting on it: the storage, AI and reporting entitlement migrations all run *before* the rename, so the code they name exists when they run, and `plan_entitlements` stores `plan_id` rather than a code — so the grants follow the row through the rename. The row was opened from a report rather than from the migrations, which is the mistake this register's own evidence rule exists to prevent. | Withdrawn. The real defect is BILL-DEF-001, which is about the in-code catalogue a *new* product is seeded from and not about any migration. | — | WONT_FIX |
| BILL-DEF-003 | DEFECT | `docs/BILLING_DESIGN.md` in the starter is the authoritative design for both repositories, and its phase table is stale: it records Phase 3 as never run in a browser and the test-mode catalogue as absent, both of which stopped being true on 2026-09-15. | Medium | The starter's phase table against the Control Plane's billing document of 2026-09-15. A `docs/SYNC_BACKLOG.md` shape: one fact, two documents, one of them updated. | **Fixed 2026-09-19** by the second option: the phase table now carries what each phase *contains* and no longer claims how far it got, and points at the Control Plane's billing document for the built state. A design document that tracks progress tracks it wrongly. | CAT-03 P0 | FIXED |
| BILL-DEF-004 | DEFECT | The Control Plane's self-serve signup document states in its header that nothing in it is built. The flow it describes has run six times in a browser. | Low | That header against the same repository's billing document. | **Fixed 2026-09-19.** Corrected in place and dated, rather than deleted: a header describing the day it was written is one every later reader has to date for themselves. | CAT-03 P0 | FIXED |

---

## Settings framework — SET

The first independent review of the settings framework, 2026-09-19. Two
reviewers, working in parallel, neither seeing the other's report. **Both
returned BLOCK.** `docs/features/settings-framework/review.md` is the record
and holds the detail; this carries the schedule.

Four were fixed the same day and are listed there rather than here: SET-01 (a
plain member could not use their own preferences page), SET-02 (the one setting
the framework was built to demonstrate could not be changed), SET-03 (the
secret guard looked one level deep and said it looked everywhere) and SET-04
(its word list missed the commonest credential nouns).

| ID | Type | Title | Severity | Status |
|----|------|-------|----------|--------|
| SET-05 | DEFECT | Saving one category creates a personal override for every field in it, detaching a member from their organisation's defaults for settings they never touched | High | OPEN |
| SET-06 | DEFECT | The somebody-chose-this marker and the provisioning snapshot are incompatible as designed: every field on a new tenant reads as modified | High | OPEN |
| SET-07 | DEFECT | The effective-settings route discloses what the tenant-values route gates behind a permission, making that permission decorative | High | OPEN |
| SET-08 | GAP | `system` and deprecated status are enforced on display and on no write path | Medium | OPEN |
| SET-09 | GAP | No size bound on a string, list or object value, on a route needing no permission | Medium | OPEN |
| SET-10 | DEFECT | The audit helper commits, so a multi-key write is not atomic with its own trail | Medium | OPEN |
| SET-11 | DEFECT | A reset announces one value and writes another when the platform row no longer validates | Medium | OPEN |
| SET-12 | DEFECT | The global version is not monotonic and is computed read-then-write | Medium | OPEN |
| SET-13 | DEFECT | Re-seeding pushes today's defaults into an existing tenant and leaves the provenance saying otherwise | Medium | OPEN |
| SET-14 | GAP | The platform write route is unaudited and has no caller | Medium | OPEN |
| SET-15 | GAP | A scope narrowed in a deploy leaves rows that can be neither used nor deleted, and nothing reports them | Medium | OPEN |
| SET-16 | GAP | A string list has no emptiness or duplicate rule; clearing the allowed-extensions field permits nothing | Low | OPEN |
| SET-17 | DEFECT | A refusal a docstring says is recorded is not | Low | OPEN |
| SET-18 | GAP | Skipped values are reported as bare keys, losing which rung holds the bad one | Low | OPEN |
| SET-19 | DEFECT | Caller-supplied strings reach the audit table on the permission-refusal path, unbounded | Low | OPEN |
| SET-20 | GAP | The sensitive flag is honoured in one place and published nowhere, so no surface can mask a field | Low | OPEN |
| SET-21 | DEFECT | Two load-bearing comments describe behaviour the code does not have | Low | OPEN |
| SET-22 | TEST-GAP | No isolation suite ever tries to move a row, so all three `WITH CHECK` clauses are correct and entirely unexercised — deleting any would leave the suites green | High | OPEN |

**The finding about the findings.** This is the third and fourth independent
review this repository has commissioned and the third and fourth BLOCK. Two
reviews of the storage and audit governance work returned BLOCK in September
and every finding was real. Four for four is enough to plan around: **work here
that has not been independently reviewed should be assumed to carry defects of
this class**, and a schedule that does not budget for the review has budgeted
for the rework instead.

---

## Findings adopted from the docoris audit

`docoris/docs/requirements/GAP-REGISTER.md` holds 229 rows, fifteen of them
classified as platform gaps — a real product's list of what the factory does
not give it. Three are adopted here, because this plan acts on them:

| docoris ID | Adopted as | Note |
|---|---|---|
| GR-002 | PLAT-GAP-001 | On-demand background work. Docoris raised it as a product question; it is a factory one. |
| GR-064 | PLAT-GAP-005 | No event spine. Deferred here, with a stated interim. |
| GR-055 | IMPORT-GAP-011 | An unscanned file can be read. Narrowed for the import path only. |

The remaining twelve — external identity, per-object authorization, tenant API
keys, full-text search, per-tenant custom domains, file versioning, a working
calendar, document preview, application metrics, a storage category for
template assets, disposal by approval, and a workspace export — are real, and
are outside these three categories. They belong in `docs/FOLLOW_UPS.md` when
somebody funds them.
