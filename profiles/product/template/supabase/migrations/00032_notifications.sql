-- Migration: 00032_notifications
-- Somewhere for a product to tell a person something.
--
-- Until this table existed a generated product had exactly two ways to reach
-- a customer, both of them email, both composed inline, and neither recorded:
-- an assistant action awaiting approval, and a scheduled report. There was no
-- bell, no feed, no read state and no table -- `packages/notifications` was
-- two lines saying to implement it as needed.
--
-- ── One row per recipient, not one row plus a read table ────────────────────
--
-- The alternative was a notification row addressed to a tenant with a
-- `notification_reads` table beside it, which is cheaper for an announcement
-- sent to five hundred people. It was not chosen, for two reasons.
--
-- The policy is the first. A per-recipient row is scoped by
-- `tenant_id = current_tenant_id() and user_id = current_user_id()`, which is
-- the same two-clause predicate `member_setting_values` already uses and is
-- wrong in only one obvious way if it is wrong. A shared row needs a policy
-- that admits a row belonging to *nobody in particular*, and an `or` in a
-- policy is where cross-tenant reads come from.
--
-- The second is that an unread count is the query this table serves most, by
-- a wide margin -- the shell asks for it on every dashboard load. Against
-- per-recipient rows it is one index scan. Against a join it is a join, on
-- every page, for every person.
--
-- The cost is real and is stated rather than discovered: a tenant-wide
-- announcement writes one row per member. At the size a KORAS tenant is today
-- that is tens of rows. If it ever becomes thousands, the fix is a second
-- table for broadcasts, not a rewrite of this one.
--
-- ── Why `url` is a path and not a link ──────────────────────────────────────
--
-- A notification is rendered as something clickable, and a clickable thing
-- whose destination came from a caller is a phishing vector wearing the
-- product's own branding. The check constraint admits a root-relative path
-- and nothing else: no scheme, no host, no protocol-relative `//`.
--
-- ── Retention ───────────────────────────────────────────────────────────────
--
-- Foundation, like the audit sweep and for the same reason: a table every
-- product writes to is a table every product must forget. `purge_notifications`
-- runs nightly and is always on. The provisioning policies below are what let
-- it reach every tenant; without them a sweep would delete on behalf of
-- whichever tenant it happened to be scoped to, which is to say none of them.

create table public.notifications (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants(id) on delete cascade,
  -- ZITADEL subject (sub), as `tenant_members` and `member_setting_values`
  -- hold it. A notification always has exactly one recipient.
  user_id      text not null,
  -- The kind of thing that happened, dotted lower-case, the shape an audit
  -- action key uses. Not a foreign key: the catalogue is code, the same way
  -- audit actions and report keys are, so adding a kind is a definition and a
  -- translation and no migration.
  kind         text not null,
  -- Already translated when it is written. A notification is rendered months
  -- later by a shell that does not know what produced it, so storing a key
  -- and interpolating at read time would need every producer's parameters
  -- kept too. The recipient's language is resolved at write time instead.
  title        text not null,
  body         text not null default '',
  -- Root-relative, or empty. See above.
  url          text not null default '',
  severity     text not null default 'info',
  created_at   timestamptz not null default now(),
  read_at      timestamptz,

  constraint notifications_kind_is_dotted
    check (kind ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  constraint notifications_severity_known
    check (severity in ('info', 'success', 'warning', 'error')),
  constraint notifications_title_not_blank
    check (btrim(title) <> ''),
  constraint notifications_url_is_a_path
    check (url = '' or (url ~ '^/[^/]' and url !~ '[[:space:]]'))
);

-- The unread count and the list, which are the same query with and without a
-- predicate on `read_at`. Descending, because a feed is read newest first.
create index notifications_recipient_idx
  on public.notifications (tenant_id, user_id, created_at desc);

-- The sweep's query: everything older than a date, across every tenant.
create index notifications_age_idx
  on public.notifications (created_at);

alter table public.notifications enable row level security;
alter table public.notifications force row level security;

-- ── A person reads their own, and marks their own ───────────────────────────
--
-- There is no policy admitting an administrator to somebody else's
-- notifications, deliberately. A notification is addressed to a person; an
-- owner who could read every member's feed would be reading their colleagues'
-- mail, and nothing in the product asks to.

drop policy if exists "notifications_select_own" on public.notifications;
create policy "notifications_select_own"
  on public.notifications for select
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

-- Marking read is the only update a person makes. The `with check` repeats the
-- predicate so a row cannot be updated *out* of its own tenant or onto another
-- person -- an update policy without one admits exactly that.
drop policy if exists "notifications_update_own" on public.notifications;
create policy "notifications_update_own"
  on public.notifications for update
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  )
  with check (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

-- ── The product writes for anyone in the tenant ─────────────────────────────
--
-- Insert is scoped to the tenant and *not* to the caller: a notification is
-- usually written for somebody else. The request that uploads a file tells the
-- approvers about it, and none of them is the caller.
drop policy if exists "notifications_insert_own_tenant" on public.notifications;
create policy "notifications_insert_own_tenant"
  on public.notifications for insert
  with check (tenant_id = public.current_tenant_id());

-- A person may dismiss their own.
drop policy if exists "notifications_delete_own" on public.notifications;
create policy "notifications_delete_own"
  on public.notifications for delete
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

-- ── The sweep ───────────────────────────────────────────────────────────────

drop policy if exists "notifications_select_provisioning" on public.notifications;
create policy "notifications_select_provisioning"
  on public.notifications for select
  using (public.is_provisioning());

drop policy if exists "notifications_delete_provisioning" on public.notifications;
create policy "notifications_delete_provisioning"
  on public.notifications for delete
  using (public.is_provisioning());
