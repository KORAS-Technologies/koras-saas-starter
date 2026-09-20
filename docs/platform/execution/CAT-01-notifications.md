# CAT-01 — Notification and communication framework

| | |
|---|---|
| **Category ID** | CAT-01 |
| **Feature name** | Notification and communication framework |
| **Owner** | CAT-01 lead |
| **Written** | 2026-09-19 |
| **Status** | Phase 0 and Phase 1 built 2026-09-19. Phases 2 to 5 planned |
| **Read first** | `docs/platform/master-platform-plan.md` §7, §9; `docs/platform/feature-dependency-map.md`; `docs/platform/gap-defect-register.md` NOTIF rows |

## Objective

Give a generated KORAS product one way to tell a person something, across
channels, honouring what they asked to receive, recording that it happened, and
surviving a process restart. Today a product has exactly two messages — an AI
approval notice and a scheduled report — both composed inline, neither recorded,
and one of them sent in the wrong person's language.

## Repository scope

| Repository | Allowed | What |
|---|---|---|
| `koras-saas-starter` | **Yes — owner** | The framework, the tables, the UI, the templates, the capability |
| `output/koras-e2e-shop` | Yes, after the integration gate | Validation, by hand-carried sync commit |
| `koras-control-plane` | Yes, Phase 4 only | The delivery-health read, implemented there against the contract |
| `docoris` | **No** | A real product. Its notification architecture is read as a requirements source and nothing is written to it |

## Dependencies

| Dependency | Class | State |
|---|---|---|
| Auth, tenant context, forced RLS | HARD | Satisfied |
| Settings framework | HARD | Satisfied. Three notification definitions already exist |
| Audit action registry | HARD | Satisfied |
| i18n, three catalogues | HARD | Satisfied |
| Navigation registry | HARD | Satisfied |
| `packages/ui` primitives | HARD | Satisfied |
| Email transport | HARD | Satisfied |
| **PLAT-F1 job contract** | **HARD from Phase 3** | Built 2026-09-19 |
| Domain event bus | OPTIONAL | Deliberately absent. This category supplies the interim |
| Realtime transport | OPTIONAL | Phase 1 polls |
| SMS provider | FUTURE | Phase 5 |

**Hard blockers.** None as of 2026-09-19: PLAT-F1 was built the same day, so
Phase 3 is unblocked too.

**What Phases 0 and 1 delivered**, built and verified on 2026-09-19 against a
freshly generated product — lint, typecheck, test and build across 71 tasks, in
three capability variants:

- The capability gates seven paths and can be excluded; `requires` refuses a
  producer without a store.
- `00032_notifications.sql` with forced row-level security, four policies, an
  isolation suite, and a check constraint that refuses a link the product did
  not make.
- A kind registry, a store that refuses a programming mistake and swallows a
  delivery one, four routes, and no route that writes a notification.
- A bell with an unread count, a drawer, a notification centre, and `Banner`
  and `ToastProvider` primitives.
- One producer: the assistant's approval notice, which now reaches the product
  as well as the inbox, in the same words.
- A nightly sweep in two windows, always on.
- `notifications.inAppEnabled` honoured; the other two unsurfaced until the
  phases that honour them.

## Shared contracts

**Produced — `NotificationEmitter`.** One in-process dispatch point, with three
rules:

1. **Notification subscribes; audit does not.** Audit stays a direct
   in-transaction call. Making audit a subscriber turns a durable record into a
   delivery problem.
2. **A notification never fails the transaction that caused it.** The in-app row
   is written in that transaction; everything that leaves the process happens
   after commit.
3. **An unresolvable recipient alerts an administrator rather than being
   dropped.** A message nobody received and nobody knows about is worse than an
   error.

The default implementation is a no-op, so CAT-02 may emit before this exists.

**Consumed — the PLAT-F1 job contract**, from Phase 3.

## Required documents

Following the factory's own convention — `docs/adr/` for why,
`docs/` top level for how a subsystem works, `docs/features/<slug>/` for what a
feature is:

| Document | When |
|---|---|
| `docs/adr/0008-koras-platform-job-and-notification-contracts.md` | Written 2026-09-19; amend if a decision changes |
| A feature directory under `docs/features/` with a README, the feature, user stories, acceptance criteria, architecture, security, testing and a manual test plan | Phase 0, before Phase 1 code |
| A top-level notification architecture document describing what was built | After Phase 3 |
| Rows in `docs/platform/gap-defect-register.md` | Continuously |

## Phases

### Phase 0 — Contracts and the capability

- Write the emitter interface and the event-name vocabulary, with a no-op
  default, so CAT-02 can emit on day one.
- Give the `notifications` capability a template-map entry and a defaults entry
  so that it gates something and can be excluded (**PLAT-DEF-006**).
- Decide and record which of the new tables are foundation and which are gated,
  by the manifest's own rule: a table is gated only when no foundation code and
  no foundation migration reaches it.
- Mark the three notification settings unsurfaced until Phase 2 honours them
  (**NOTIF-DEF-001**), so no customer is offered a switch that does nothing.
- Write the registry conventions down once (**PLAT-DEBT-002**).
- Correct the dependency-map row for this package (**NOTIF-DEF-004**).

**Exit:** a generated project with and without the capability differs, and the
difference is what the template map says it is.

### Phase 1 — In-app notifications, toast, banner

- A tenant-owned notification table with forced RLS, four policies and a
  numbered isolation test; read state per member; a retention class.
- Routes: list, unread count, mark read, mark all read. The unread count is
  cheap enough to poll.
- A bell in the product header with an unread count; a drawer; a notification
  centre page registered as a navigation module.
- Toast and banner primitives in `packages/ui`. Migrating the thirty existing
  hand-rolled alert regions is **out of scope** and stays out.
- Notification audit actions registered (**NOTIF-DEF-002** begins closing).
- Every new string in all three language catalogues.

**Exit:** a person sees a notification without a page reload having been
promised, dismisses it, and the count is right. A browser test asserts the bell,
the drawer, focus handling and Escape.

### Phase 2 — Channels, templates, recipients, preferences

- A channel seam; email becomes the first adapter rather than the only path.
- A template registry with the same conventions as the reporting and settings
  registries, with the layout shared and the strings coming from the message
  catalogue (**NOTIF-GAP-002**).
- A recipient resolver taking a rule rather than a hardcoded permission
  (**NOTIF-GAP-004**).
- `core/notify.py` moves onto the dispatch point and stops composing HTML
  inline.
- The three preference settings become true and are surfaced again
  (**NOTIF-DEF-001**), including organisation defaults, which the scope they are
  already declared with supports.
- The recipient's own language is resolved through the settings resolver
  (**NOTIF-DEF-003**).

**Exit:** switching off notification emails switches off notification emails,
asserted by a test. The approval notice arrives in the approver's language.

**Met 2026-09-19, with one criterion narrowed and the narrowing recorded.**
`core/dispatch.py` is the seam, `core/recipients.py` the resolver, and
`tests/unit/test_dispatch.py` carries the exit criterion as a test with that
name. The narrowing: `notifications.emailEnabled` is **organisation-scoped**
rather than per person. A mail goes to an address; the product learns its
members' addresses from the platform's member list, which carries an email
and a role and no ZITADEL subject — so a recipient it can mail is one it
cannot match to a member, and a person-level switch could never be read.
Offering the rung anyway would have been the failure `surfaced=False` exists
to prevent. It becomes per person when the platform answers a subject beside
the address; F26 in `docs/FOLLOW_UPS.md`.

**`notifications.digestFrequency` stays unsurfaced.** A digest needs an outbox
to accumulate into, which is Phase 3, so Phase 2 deliberately did not build
one. The template registry also landed in a narrower form than planned: a
template is a function from a language to a rendering, registered by the
producer beside its kind rather than in a central registry. One producer does
not justify a registry, and the conventions are the same the moment a second
one needs it.

### Phase 3 — Outbox, delivery log, retry

*Requires PLAT-F1.*

- An outbox row written in the causing transaction; a worker task that dispatches
  after commit; deduplication by the outbox row rather than by hope
  (**PLAT-GAP-004**).
- A delivery record per message with the provider message id the sender already
  returns and every call site discarded as of 2026-09-19 (**NOTIF-GAP-005**).
- Retry with a declared policy and a terminal state that is visible rather than
  silent (**PLAT-GAP-003**).
- Escalation: a rule that widens the recipient set when a critical notification
  is unacknowledged.

**Exit:** a mail server refusing connections for ten minutes loses no
notification, and the delivery log says what happened to each.

### Phase 4 — Digests and announcements

- A digest job honouring the frequency setting that has offered three values and
  been read by nothing (**NOTIF-GAP-009**), grouping by subject.
- Grouping and deduplication of near-identical notifications.
- Platform announcements read from the Control Plane over the existing platform
  contract, rendered as a banner (**NOTIF-GAP-008**).
- Delivery health exposed for platform monitoring, in the shape the governance
  contract already uses: counts, never content.

### Phase 5 — SMS

- One adapter behind the Phase 2 channel seam. Opt-in, quiet hours, time zone
  and a cost ceiling are **preconditions, not follow-ups**. SMS is used
  conservatively: time-critical messages only, and never as a default.

## User stories

Role vocabulary is the closed organisation role set: owner, admin,
billing admin, security admin, member.

| ID | As a | I want | So that | Phase |
|---|---|---|---|---|
| NOTIF-US-001 | member | to see a count of things needing my attention | I do not have to check every page | 1 |
| NOTIF-US-002 | member | to open a list of my notifications and mark them read | the count means something | 1 |
| NOTIF-US-003 | member | immediate confirmation that what I just did worked | I am not left guessing | 1 |
| NOTIF-US-004 | member | a persistent bar for a condition that persists | a dismissible toast does not hide something that still applies | 1 |
| NOTIF-US-005 | member | notifications in my own language | I can read them | 2 |
| NOTIF-US-006 | member | to choose which notifications reach my email | my inbox reflects what I asked for | 2 |
| NOTIF-US-007 | organisation admin | to set defaults for everyone in my organisation | a new colleague starts sensibly | 2 |
| NOTIF-US-008 | organisation admin | to know a notification was delivered, and when | I can answer "I never got it" | 3 |
| NOTIF-US-009 | security admin | every notification about a security decision recorded in audit | the record survives the notification | 1 |
| NOTIF-US-010 | member | one summary rather than forty messages | a busy day is readable | 4 |
| NOTIF-US-011 | platform administrator | to publish an announcement to every product | maintenance is not a surprise | 4 |
| NOTIF-US-012 | platform administrator | delivery failure rates per product | I find a broken mail configuration before a customer does | 4 |
| NOTIF-US-013 | support user | to see what a customer was sent without seeing its contents | I can help without reading their mail | 3 |
| NOTIF-US-014 | developer | to emit a notification without knowing which channels exist | adding a channel changes no caller | 0 |
| NOTIF-US-015 | member | a time-critical message by SMS, only if I asked for it | urgency does not become nuisance | 5 |

## Acceptance criteria — the ones that decide the phase

- **P1.** A notification created for tenant A is invisible to tenant B, asserted
  by a numbered RLS test. The unread count is per member, not per tenant.
  Marking read is idempotent. The drawer traps focus and Escape returns it.
- **P2.** With the email preference off, no email is sent and the in-app
  notification still appears — one test, both halves. A template renders in all
  three languages, with the recipient's language deciding, not the actor's.
- **P3.** A dispatch that raises is retried according to a declared policy and
  ends in a state that is visible. Two dispatches of one outbox row send one
  message. A notification failure never rolls back the transaction that caused
  it.
- **P4.** A digest respects the frequency setting, including "never".
- **P5.** No SMS is sent without a recorded opt-in. A message outside quiet hours
  is held, not dropped.

## Security requirements

- Every notification row is tenant-owned with forced RLS and a numbered
  isolation test. No cross-tenant read, including through the unread count.
- **A notification body is not an audit detail and an audit detail is not a
  notification body.** The audit envelope refuses credential-shaped keys; a
  notification may carry a person's name and a link and must carry no secret.
- Recipient resolution is server-side. A browser-supplied recipient list is
  never trusted.
- A link in a notification points at the product's own origin. Building one from
  a request header is how a notification becomes a phishing vector.
- Delivery records are readable by a support role **without** exposing the
  message body.
- The delivery-health read for the platform carries counts, never content — the
  rule the governance contract already applies.
- Rate limiting: a loop that emits per row must not become a mail flood. A
  per-tenant per-hour ceiling, refused loudly.
- SMS carries a cost and therefore an abuse path. Phase 5 does not ship without
  a ceiling.

## Database impact

Reserved migration range **`00032`–`00035`**, RLS test range **`290`–`310`**.
Every table: tenant-owned, `enable` and `force`, four policies, one numbered
isolation test, and a retention class named at creation rather than added later.

| Phase | Tables |
|---|---|
| 1 | Notifications, and per-member read state |
| 2 | None — preferences are settings, and settings already have three tables |
| 3 | The outbox, and the delivery record |
| 4 | Announcements are read from the platform, not stored per tenant |

## APIs

New routes under the customer prefix, capability-gated, each checking its
permission as the first statement of the handler — the repository's convention,
not a dependency and not a decorator. List, unread count, mark read, mark all
read, and from Phase 3 a delivery read for support.

## UI impact

`packages/ui`: a bell, a drawer, a notification centre, a toast and a banner.
`apps/web`: one new dashboard module registered in the navigation registry.
Every surface honours loading, empty, error and unauthorised states, keyboard
operation, visible focus, and reduced motion — a toast that animates is a toast
that must not.

## Background jobs

Phase 3 introduces the first genuinely enqueued job in the repository. Phase 4
adds a digest cron, outside the reserved 03:17–04:39 sweep window, off until a
setting asks for it.

## Audit

New actions registered by this category's own module at import: dispatched,
delivered, failed, read, preference changed, announcement published. Every one
gets a classification decided by the action rather than the call site. Verbose
worker output is logged, never recorded as audit.

## Observability

Emitted where there is somewhere to emit: structured logs with the tenant and
the outbox row, trace context across the queue, and counts on the delivery
record. Queue depth and failure rate belong on a metrics endpoint the repository
does not have (**PLAT-GAP-007**), and this category does not build one.

## Testing

| Kind | What |
|---|---|
| Python unit | Resolver, template rendering in three languages, preference honoured, retry policy, deduplication |
| Node unit | Registry resolution for the new navigation module; the primitives |
| RLS | One numbered isolation test per table; a cross-tenant unread-count case |
| Generator | A `product-notifications.test.ts` asserting the capability gates exactly the declared paths, the module href resolves to a real route, the icon is in the union, the permission strings exist, and every message key is present in all three catalogues |
| Browser | Bell, drawer, focus trap, Escape, toast dismissal, banner persistence, at 375 and 1440 |
| Failure paths | Mail server refusing; an unresolvable recipient; a preference switched off mid-flight |

## Manual QA

A manual test plan in the feature directory, with the fifteen-case shape the
settings framework used. Verdicts recorded as **NOT EXECUTED** until a person
executes them. The settings framework's lesson applies directly: its first case
is the thing the feature exists for and no automated test in this estate reaches
it.

## Migration, rollout, rollback

- **Migration.** Additive. No existing table is altered before Phase 2, which
  changes only the surfaced flags on three setting definitions.
- **Rollout.** The capability is on by default once Phase 1 lands, because a
  product that cannot tell a person anything is worse than one that can. Each
  channel beyond in-app is separately off until configured — the pattern the
  three storage sweeps already use.
- **Rollback.** Phases 1 and 2 roll back by disabling the capability; the tables
  remain and hold rows nothing reads. Phase 3's outbox must drain before the
  worker task is removed, or messages are lost silently. That ordering is the
  one genuinely dangerous step in this category.

## Cross-repository sync

`output/koras-e2e-shop` receives this by hand-carried `chore: sync` commit after
the integration gate, and not before. Nothing syncs it automatically; the drift
check sees only files it never received. The Control Plane is not code-synced,
so Phase 4's platform half is implemented there against the contract.

## Definition of done

Per phase, the applicable subset of: audit completed · architecture documented ·
stories and criteria written · security reviewed · data model reviewed · API
reviewed · implemented · migrations numbered in the reserved range · unit,
integration and RLS tests passing · browser tests passing · manual plan updated
with real verdicts · accessibility validated · tenant isolation validated ·
permissions validated · failure paths tested · retry tested · audit validated ·
observability implemented · documentation updated · rollback documented ·
register updated · sync status recorded · next three features recommended.

## Known gaps, defects and debt

NOTIF-GAP-001 to 009, NOTIF-DEF-001 to 004, and PLAT-GAP-003, 004 and 005, in
`docs/platform/gap-defect-register.md`.

## Next three features, after this category

1. CAT-01 Phase 2 — preferences honoured, which closes the sharpest defect.
2. CAT-02 Phase 1 — the first consumer of the emitter, which proves the contract.
3. A shared check that no setting is surfaced without a consumer, which would
   have caught PLAT-DEF-001 both times it happened.
