# Feature dependency map

| | |
|---|---|
| **Purpose** | Every dependency between the three feature categories and the foundations they rest on, each edge classified so that the plan serialises only what must be serialised. |
| **Written** | 2026-09-19, from the master audit. |
| **Companion** | `docs/platform/parallel-execution-plan.md` turns these edges into a schedule and a file-ownership map. |

## Classification

| Class | Meaning | Consequence |
|-------|---------|-------------|
| **HARD** | The dependent cannot safely begin until the dependency exists. Building it anyway produces work that must be rewritten, not merely extended. | Serialise |
| **SOFT** | The dependent can begin against an agreed contract while the implementation proceeds separately. | Parallel, behind a contract |
| **OPTIONAL** | The dependent works without it, and is better with it. | Never a blocker |
| **FUTURE** | Named so it is not rediscovered. Outside this plan. | Record and move on |

A **SOFT** edge is only honest if the contract is written down before both
sides start. The four contracts this plan needs are in
`docs/platform/master-platform-plan.md` §9 and each is repeated in the manifest
of the category that consumes it.

## The graph

```
                      Auth / ZITADEL          Tenant context + forced RLS
                             \                        /
                              \                      /
                               +--------+  +--------+
                                        |  |
                     Permissions    Settings    Audit    Storage    i18n
                         |             |          |         |         |
                         +------+------+----+-----+----+----+----+----+
                                |           |          |         |
                                |           |          |         |
                         +------v-----------v----------v---------v------+
                         |   PLAT-F1  —  the job contract               |
                         |   enqueue seam + product task registry       |
                         |   + retry policy   (MISSING as of 2026-09-19)|
                         +------+--------------------------+------------+
                                |  HARD                    |  HARD
                                |                          |
                     +----------v-----------+   +----------v-----------+
                     |  CAT-01 Notifications |   |  CAT-02 Data Import  |
                     |  P0 contract          |   |  P0 contract         |
                     |  P1 in-app + toast    |<--|  P1 upload/map/dry   |
                     |  P2 channels + prefs  |SOFT  P2 commit + errors  |
                     |  P3 outbox + delivery |   |  P3 formats + retry  |
                     |  P4 digest + announce |   |  P4 chunked/resumable|
                     |  P5 SMS               |   +----------------------+
                     +----------+------------+
                                | SOFT (read model only)
                                |
                     +----------v-------------------------------+
                     |  koras-control-plane                     |
                     |  CAT-03 Stripe provisioning              |
                     |  P1 lookup keys + idempotency            |
                     |  P2 provisioner + catalogue drift        |
                     |  P3 versioning + currency + free plan    |
                     |  P4 console + go-live                    |
                     +------------------------------------------+
                        rests on: Koras product catalogue (EXISTS),
                        provider adapter (EXISTS), webhook (EXISTS),
                        reconciliation engine (EXISTS)
```

CAT-03 sits below the line because it is in a different repository and shares no
file with the other two. Its only edge to them is SOFT and optional.

## Edges, one row each

### Into PLAT-F1, the job contract

| Dependency | Class | Why |
|---|---|---|
| Worker service and its cron extension point | HARD, and satisfied | The place a task registry goes already exists beside `PRODUCT_CRON_JOBS` |
| Redis connection settings | HARD, and satisfied | The worker already requires a Redis URL with no localhost default |
| Tenant context | HARD, and satisfied | A job must declare a tenant or the transaction refuses to open; the worker already verifies isolation at startup |
| Audit | SOFT | A job that fails should record it; the action registry takes a new action without change |
| Metrics | FUTURE | Queue depth and failure rate belong on a metrics endpoint the repository does not have — PLAT-GAP-007 |

### CAT-01 Notifications

| Depends on | Class | Why, and what it means for scheduling |
|---|---|---|
| Auth, tenant, RLS | HARD, satisfied | Every notification row is tenant-owned |
| Settings framework | HARD, satisfied | Preferences are settings, not a second store. The three definitions already exist |
| Audit | HARD, satisfied | A dispatch is an event worth recording — NOTIF-DEF-002 is that it is not recorded today |
| i18n | HARD, satisfied | A notification a customer reads is in the customer's language |
| Navigation registry | HARD, satisfied | The notification centre is a module like any other |
| `packages/ui` primitives | HARD, satisfied | Toast, banner, drawer and bell are built from what is there |
| **PLAT-F1 job contract** | **HARD for P3 and later. Not for P0-P2** | In-app notification rows are written in the same transaction as the event, which needs no queue. Email dispatched reliably, retried and logged, does |
| Email transport | HARD, satisfied | SMTP, three locales, a recording sender when unconfigured |
| Domain event bus | **OPTIONAL** | CAT-01 provides one in-process dispatch point every caller uses. If a bus is ever built, that point becomes its first subscriber and no caller changes |
| Realtime transport | OPTIONAL | Phase 1 polls the unread count. Server-sent events exist for the assistant and could be reused; no evidence yet says they must be |
| Control Plane announcements | FUTURE | Phase 4 reads on the existing platform contract; a push from the platform is outside this plan |
| SMS provider contract | FUTURE | Phase 5, and only behind the Phase 2 channel seam |

### CAT-02 Data Import

| Depends on | Class | Why, and what it means for scheduling |
|---|---|---|
| Auth, tenant, RLS | HARD, satisfied | Import runs and rows are tenant-owned |
| Storage upload ticket | HARD, satisfied | The source file is an ordinary upload with the imports category |
| Storage governance | HARD, satisfied | The source file and the error file inherit retention, hold and reconciliation without being told to |
| Audit | HARD, satisfied | Every run state change is an action; per-row audit is the run, never one event per row |
| Permissions | HARD, satisfied | One new string in both languages, plus a route that checks it |
| Settings framework | HARD, satisfied | Row ceilings and file limits are settings. Three file settings already exist and are enforced by nothing |
| **PLAT-F1 job contract** | **HARD, from P1** | A dry run of a real file cannot happen in a request. Polling a cron every minute is the workaround docoris wrote down, and it is a workaround |
| Export engine | SOFT, satisfied | The error file is written by copying how an audit export is written. Nothing is imported from it |
| **PLAT-GAP-006 decision** | HARD for the data model, not for the code | Import needs a fourth run-and-record table. Whether it is a fourth instance or the reason to extract the pattern must be decided before the migration is written |
| Malware scan seam | HARD, satisfied | The predicate exists; CAT-02 narrows it for the parse path |
| Shared data table | SOFT | Phase 1 previews a bounded head of the file, which the client-side table draws. Server pagination is a separate, owned change |
| Upload primitive | SOFT | Phase 1 extracts the existing Files-page flow into `packages/ui` |
| **CAT-01 notification contract** | **SOFT** | Import emits five events. A no-op emitter satisfies the contract, so CAT-02 never waits for CAT-01 |
| Validation package | OPTIONAL | `packages/validation` is a stub; Phase 1 shares the row schema with the single-record route instead |
| AI-assisted mapping | FUTURE | The AI foundation could suggest a mapping. Named so it is not rediscovered |
| Connectors to other systems | FUTURE | Named in the brief; no phase in this plan builds one |

### CAT-03 Stripe provisioning

| Depends on | Class | Why |
|---|---|---|
| Koras product catalogue | HARD, satisfied | It is the system of record; the provisioner reads it and writes to the provider, never the reverse |
| Provider adapter | HARD, satisfied | Two operations are added to a protocol that names no vendor |
| Environment guard | HARD, satisfied | A live key is refused outside production at construction; the provisioner inherits it |
| Reconciliation engine | HARD, satisfied | The catalogue drift check is a new check in an existing registry with an existing policy vocabulary |
| Webhook and event log | OPTIONAL | Provisioning is outbound; the webhook is inbound. They meet only at the subscription row |
| Terraform | **Explicitly not a dependency** | No Terraform in either repository manages the provider, and none should. Terraform owns infrastructure; the catalogue owns commerce |
| Generator provisioning | **Explicitly not a dependency** | The registration payload carries no commercial field, and adding one would put pricing in a product repository |
| CAT-01 notifications | SOFT, and optional | A drift finding or a failed provisioning run is worth telling somebody about. The Control Plane is not code-synced from the starter, so it would implement the contract rather than receive it |
| Audit | HARD, satisfied | Every provisioning and reconciliation action is auditable in the Control Plane's own audit |
| Live mode | Not a code dependency | `docs/FOLLOW_UPS.md` F21: a person at a dashboard |

## The three edges that decide the schedule

1. **PLAT-F1 → CAT-02 is HARD from Phase 1.** Import is a background-job
   feature; there is no version of it that is not.
2. **PLAT-F1 → CAT-01 is HARD only from Phase 3.** Phases 0 to 2 write rows in
   the transaction that caused them, and dispatch mail exactly as the one
   existing mail does. So CAT-01 can start immediately and CAT-02 cannot.
3. **CAT-01 → CAT-02 is SOFT.** One emitter interface, five event names, and a
   no-op default. Neither category waits for the other.

Everything else is either satisfied today or outside this plan.

## What is deliberately not a dependency

- **A domain event spine.** Building one now would mean designing the platform's
  event vocabulary from two subjects, which is one fewer than the number that
  makes the vocabulary honest. CAT-01's dispatch point is the interim, and it is
  an interim with a stated upgrade path rather than an accident.
- **Server-side pagination.** Real, needed eventually, and not needed to preview
  the first two hundred rows of a file.
- **Metrics.** Every category below names what it would emit. None of them
  builds an endpoint to emit it to.
