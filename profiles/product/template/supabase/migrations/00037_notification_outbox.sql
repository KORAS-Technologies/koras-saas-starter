-- Migration: 00037_notification_outbox
--
-- A message that has been decided but not yet sent, and what happened when it
-- was tried.
--
-- ── Why a table rather than a background task ────────────────────────────────
--
-- Until now `dispatch` handed its prepared mail to the caller and the caller
-- handed it to a FastAPI background task. That is the arrangement PLAT-F1 was
-- built to replace everywhere else: a background task runs in the API process
-- and is lost when it restarts, so a deploy during a send loses the send with
-- no record that it was ever owed. A mail server refusing connections for ten
-- minutes loses every notification raised in those ten minutes, and nothing
-- anywhere says so.
--
-- A row written **in the transaction that decided to send it** cannot be lost
-- that way. If the transaction rolls back there was no notification; if it
-- commits, the message is owed and something will keep trying. That is the
-- same rule the feed row already follows, applied to the half that leaves the
-- building.
--
-- ── Why the delivery record is on the same row ───────────────────────────────
--
-- Two tables were considered -- one for what is owed, one for what happened --
-- and rejected. Every question anybody asks joins them ("what happened to the
-- notice we sent Ada on Tuesday"), a message has exactly one final outcome,
-- and a second table would need its own retention, its own policy and its own
-- sweep. The cost of one table is that a retried message overwrites its own
-- last error; `attempts` and `last_failed_at` are what make that legible, and
-- a per-attempt history is Phase 4's problem if anybody ever wants one.
--
-- ── What a provider message id is for ────────────────────────────────────────
--
-- `koras_email.Sent` has carried `message_id` since it was written and every
-- call site discarded it. It is the only thing that connects a row here to a
-- line in a mail provider's own log, which is where the answer lives when a
-- customer says a message never arrived. NOTIF-GAP-005.

create table public.notification_outbox (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,

  -- The notification kind, dotted, as the registry declares it. Not a foreign
  -- key: the registry is code, the way reports and audit actions are.
  kind          text not null,

  -- Where it is going, and what it says. Held rather than re-rendered: the
  -- words were chosen in the caller's transaction against state that may have
  -- changed by the time this is sent, and a retry that re-rendered could send
  -- a different message from the one that was decided.
  recipient     text not null,
  locale        text not null default 'en',
  subject       text not null,
  body_text     text not null,
  body_html     text not null,

  status        text not null default 'pending',
  attempts      integer not null default 0 check (attempts >= 0),

  -- What the transport called it. Null until something accepts it, and the
  -- only handle on a provider's own record of the same message.
  message_id    text,
  -- True when it was recorded rather than sent, because no host is configured.
  -- A run that reports success having delivered nothing must not look
  -- identical to one that delivered; `koras_email` says so and nothing acted
  -- on it until this column existed.
  simulated     boolean not null default false,

  -- A safe sentence. Never a stack and never a provider body: a bounce message
  -- can quote the recipient's own mail, which is theirs and not ours to store.
  error         text,

  created_at     timestamptz not null default now(),
  -- When it may next be tried. Set forward by each failure, so a backing-off
  -- message is simply one whose turn has not come.
  next_attempt_at timestamptz not null default now(),
  last_failed_at  timestamptz,
  sent_at         timestamptz,

  constraint notification_outbox_kind_is_dotted
    check (kind ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  constraint notification_outbox_status_known
    check (status in ('pending', 'sending', 'sent', 'failed', 'abandoned')),
  -- A message that says it was sent names when, and one that gave up says why.
  -- Both are the kind of thing that is obviously true until a code path writes
  -- one without the other.
  constraint notification_outbox_sent_has_a_time
    check (status <> 'sent' or sent_at is not null),
  constraint notification_outbox_abandoned_has_a_reason
    check (status <> 'abandoned' or error is not null)
);

-- The worker's query: what is owed, oldest first, whose turn has come.
create index notification_outbox_due_idx
  on public.notification_outbox (next_attempt_at)
  where status in ('pending', 'sending');

create index notification_outbox_tenant_idx
  on public.notification_outbox (tenant_id, created_at desc);

alter table public.notification_outbox enable row level security;
alter table public.notification_outbox force row level security;

-- ── Who may see a message waiting to be sent ─────────────────────────────────
--
-- **Nobody, as a customer.** There is no select policy for a tenant and that is
-- the decision: this table holds the rendered body of every notification,
-- including one addressed to a colleague, and a member who could read it could
-- read what the product told somebody else. The feed is where a person sees
-- their own notifications, keyed to their own subject.
--
-- What reads and writes this is the provisioning context -- the API writing a
-- row in the transaction that decided to send it, and the worker sending it.
-- Both already run under that flag for every other sweep.

drop policy if exists "notification_outbox_provisioning" on public.notification_outbox;
create policy "notification_outbox_provisioning"
  on public.notification_outbox for all
  using (public.is_provisioning())
  with check (public.is_provisioning());

-- The tenant's own context may **insert** and nothing else.
--
-- The API writes this row inside a customer's request, on the customer's own
-- session, so that it commits or rolls back with the thing that caused it.
-- Insert alone: a caller that could update could mark a message sent that
-- never was, and one that could select could read a colleague's mail.
drop policy if exists "notification_outbox_insert_own_tenant" on public.notification_outbox;
create policy "notification_outbox_insert_own_tenant"
  on public.notification_outbox for insert
  with check (tenant_id = public.current_tenant_id());
