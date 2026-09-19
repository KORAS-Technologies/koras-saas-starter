# ADR 0008 — The background job contract, and notification's dispatch point

**Status.** Proposed, 2026-09-19. Nothing here is built. It records the two
decisions the master platform plan of 2026-09-19 rests on, so that three feature
categories can be worked in parallel without each answering them differently.
The plan is `docs/platform/master-platform-plan.md`; the findings are
`docs/platform/gap-defect-register.md`.

**Context.** Read across the repository on 2026-09-19: **nothing can enqueue a
background job.** ARQ is present, the worker runs, and nine sweeps are
registered — every one of them cron. The three request paths that continue
working after the response use FastAPI background tasks, which run in the API
process and die with it. The enqueue call, the pool constructor and the client
type appear nowhere in `profiles/`, `generators/` or `tooling/`.

The consequences are already visible, in three places and in two repositories.

- The worker's product extension point takes cron jobs only. A product that
  needs work done *when something happens* must either edit
  `services/worker/koras_worker/worker.py`, which is generated and starter-owned
  and which the next sync reverts, or poll on a schedule. `docoris` recorded
  this as its OD-19 rather than writing the workaround, and its gap register
  carries it as GR-002.
- `python-packages/koras-queue` is a single comment line, and four package
  manifests declare a dependency on it — the product API, the Control Plane API,
  the worker and the scheduler. A package that exports nothing and is depended
  on four times is a promise nobody kept.
- The mail package's own docstring states that delivery is at-least-once and
  that "a caller that must not repeat a message has to arrange that itself".
  Nothing does. One of the two messages a product sends is dispatched in a
  background task after the response, records no audit event, and logs its
  failures.

Two of the three feature categories in the plan need this. Data import is a
background-job feature in its first phase: a dry run of a real file cannot
happen inside a request. Reliable notification delivery needs the same thing
from its third.

There is a second, adjacent question that must be answered at the same time,
because answering it late costs more. The repository has a durable audit table
with no consumers and no dispatch, and it is tempting to make notification a
subscriber of it. It is also tempting to build a general event bus and put both
behind it.

---

## Decision 1 — Build the job contract, and build it first

A product-facing seam for enqueueing work, with three parts:

1. **An enqueue function callable from a request**, taking a task name, a tenant,
   a payload and an optional idempotency key. It returns having handed the work
   over, not having done it.
2. **A product-owned task registry beside the existing cron registry**, so that a
   product — and a feature category — adds an on-demand task without editing a
   generated file. `PRODUCT_CRON_JOBS` already exists precisely so that nobody
   edits `worker.py`; this is the same idea for work that is not periodic.
3. **A declared retry policy per task**, rather than the queue library's defaults
   inherited silently, with a terminal state that is visible rather than a job
   that vanishes.

A job declares a tenant or its transaction refuses to open. That is not new
policy — the database layer already raises on an undeclared transaction and the
worker already refuses to start on a connection row-level security cannot
restrain. It is stated here because an enqueued job is the first place where the
declaration is made by a caller that is no longer on the request.

**Why first, and alone.** It is small; two categories are blocked or degraded
without it; and without it both would build the same workaround — a cron sweep
polling a table for queued work — which would then have to be removed from two
places. A workaround written twice becomes the architecture.

**What this does not decide.** Whether `koras-queue` becomes the home of the
seam or is deleted along with its four dependencies. Either is defensible; what
is not defensible is leaving it as it is.

---

## Decision 2 — Notification gets one dispatch point, and audit stays a direct call

Notification dispatch is **not** a subscriber of the audit record, and **no
general event bus is built** as part of this work.

Instead, one in-process dispatch point that every caller uses, governed by three
rules:

1. **Notification subscribes; audit does not.** An audit row is a durable record
   read by people later. A notification is a delivery obligation. Making audit
   the trigger for delivery means an audit write can fail for a delivery reason,
   and that a record kept for three years is coupled to a mail server.
2. **A notification never fails the transaction that caused it.** The in-app row
   is written inside that transaction, because it is tenant data. Everything
   that leaves the process happens after commit.
3. **An unresolvable recipient alerts an administrator rather than being
   dropped.** A message nobody received and nobody knows about is the worst of
   the available outcomes.

**Why not a bus.** A bus designed from two subjects encodes two subjects'
assumptions. The repository has one in-process hook registry covering two
moments in the life of one subject, and that is the whole of its experience with
dispatch. The upgrade path is explicit: if a bus or an outbox is built later,
this dispatch point becomes its first subscriber and **no caller changes**. That
is what makes deferring it a decision rather than a delay.

**Why not nothing.** Calling the mail function directly from each site is what
the repository does today, once, and it is why the one message that exists
records nothing, is composed inline, and goes out in the wrong person's
language.

---

## Consequences

**Good.**

- Data import becomes possible to build honestly rather than as a polling
  workaround, and `docoris` OD-19 is answered by the factory rather than worked
  around in a product.
- Notification delivery can survive a process restart, be retried under a stated
  policy, and be recorded.
- Two categories proceed in parallel behind written contracts instead of one
  waiting for the other.
- Four package manifests stop depending on a package that exports nothing.

**Costs, stated rather than hidden.**

- A queue that can be enqueued to is a queue that can be filled. A per-tenant
  ceiling is a Phase 1 requirement of whichever category enqueues first, not a
  follow-up.
- Retry means at-least-once, which means every enqueued task must be idempotent
  or must carry a key. This is a real discipline cost on every task written from
  now on, and it is the price of the failure mode being visible instead of
  silent.
- Deferring the event bus means that when a third subject wants dispatch, this
  decision is revisited rather than extended. That is intended: the third subject
  is what makes the vocabulary honest.
- The dispatch point can become an event bus by accident, one convenience
  argument at a time. Whoever owns CAT-01 owns refusing that.

**Rejected alternatives.**

- *Edit the generated worker file per product.* It is starter-owned; the next
  sync reverts it, silently, and the product notices when its work stops
  happening.
- *Poll a table from a cron job every minute.* Works, and is written down in the
  docoris import architecture as the interim. It puts a minute of latency on
  every interactive action, burns a worker slot, and — measured once before, as
  R-018 — a queue polling with nothing to do cost 170,000 polls a day.
- *Make notification a subscriber of `audit_events`.* Rejected in Decision 2.
- *Build the event bus now.* Rejected above, with the upgrade path stated.

## What would change this decision

A second and third subject wanting dispatch — search indexing and a customer
webhook are the two named in the docoris inventory — would make the event bus
worth building, and this ADR would be superseded rather than amended.
