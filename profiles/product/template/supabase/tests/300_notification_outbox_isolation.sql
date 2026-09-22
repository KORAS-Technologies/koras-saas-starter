-- The outbox holds the words of every notification, including somebody else's.
--
-- That is what makes its policies different from every other table here. A feed
-- row is addressed to a person and they may read it; an outbox row is the
-- rendered body of a message addressed to *anybody* in the organisation, so a
-- member who could select from this table could read what the product wrote to
-- a colleague.
--
-- So there is no tenant select policy at all, and this suite's job is to prove
-- that absence rather than assume it. The API inserts, the worker reads and
-- writes under provisioning, and a customer's own context can do neither.

\set ON_ERROR_STOP on
begin;

-- The literal role, as every other suite here uses. It was `:app_role` until
-- 2026-09-22, which made this the only suite that needed a psql variable the
-- caller had to supply -- and `local/scripts/test-rls.sh` supplies it only when
-- `RLS_APP_ROLE` is set, which it is not by default. So a product running its
-- own suite got `syntax error at or near ":"` on this file and nothing else.
--
-- `generator-integration.yml` passes `-v app_role=...` to every file, so the
-- starter's own gate was green over a suite no generated product could run.
set local role koras_rls_test;

-- Two organisations, and a message owed to each.
set local app.provisioning = 'on';

insert into public.tenants (id, slug, name, zitadel_org_id, status)
values
  ('00000000-0000-0000-0000-000000000001', 'alpha', 'Alpha', 'org-alpha', 'active'),
  ('00000000-0000-0000-0000-000000000002', 'beta', 'Beta', 'org-beta', 'active')
on conflict (id) do nothing;

insert into public.notification_outbox
  (id, tenant_id, kind, recipient, locale, subject, body_text, body_html)
values
  ('00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000001', 'ai.approval_requested',
   'alpha@example.test', 'en', 'Alpha subject', 'alpha text', '<p>alpha</p>'),
  ('00000000-0000-0000-0000-0000000000b1',
   '00000000-0000-0000-0000-000000000002', 'ai.approval_requested',
   'beta@example.test', 'en', 'Beta subject', 'beta text', '<p>beta</p>');

set local app.provisioning = '';

do $$
declare
  seen integer;
begin
  -- ── A customer cannot read their own organisation's outbox ────────────────
  --
  -- Not a weaker claim than cross-tenant isolation: a stronger one. Alpha's
  -- own rows are invisible to Alpha, because the table has no select policy
  -- for a tenant at all. If somebody adds one later "for a status page", this
  -- is the test that stops them doing it by accident.
  perform set_config('app.tenant_id', '00000000-0000-0000-0000-000000000001', true);
  perform set_config('app.zitadel_org_id', 'org-alpha', true);

  select count(*) into seen from public.notification_outbox;
  if seen <> 0 then
    raise exception
      'notification_outbox: a customer read % row(s) of rendered message bodies', seen;
  end if;

  -- ── A customer may insert, because the API writes on their session ────────
  --
  -- The row is written in the transaction that decided to send it, which is a
  -- customer's own request. Insert alone: a caller who could update could mark
  -- a message sent that never was.
  insert into public.notification_outbox
    (tenant_id, kind, recipient, locale, subject, body_text, body_html)
  values ('00000000-0000-0000-0000-000000000001', 'ai.approval_requested',
          'alpha@example.test', 'en', 'Written by the API', 'text', '<p>html</p>');

  -- ── And not into somebody else's ──────────────────────────────────────────
  begin
    insert into public.notification_outbox
      (tenant_id, kind, recipient, locale, subject, body_text, body_html)
    values ('00000000-0000-0000-0000-000000000002', 'ai.approval_requested',
            'beta@example.test', 'en', 'Forged', 'text', '<p>html</p>');
    raise exception 'notification_outbox: a tenant queued a message for another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- ── A customer cannot mark anything sent ──────────────────────────────────
  --
  -- No update policy for a tenant. The statement matches nothing rather than
  -- being refused, which is the same outcome and is why this asserts on the
  -- row rather than on an exception.
  update public.notification_outbox
     set status = 'sent', sent_at = now()
   where id = '00000000-0000-0000-0000-0000000000a1';

  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);
  select count(*) into seen from public.notification_outbox
   where id = '00000000-0000-0000-0000-0000000000a1' and status = 'pending';
  if seen <> 1 then
    raise exception 'notification_outbox: a tenant changed the status of a message';
  end if;

  -- ── The worker sees everything, because nothing else can send it ──────────
  select count(*) into seen from public.notification_outbox;
  if seen < 3 then
    raise exception 'notification_outbox: provisioning saw % row(s), expected at least 3', seen;
  end if;

  raise notice 'notification outbox, nobody reads a colleague''s mail: ok';
end
$$;

-- ── The constraints that keep a row honest ───────────────────────────────────
do $$
begin
  perform set_config('app.provisioning', 'on', true);

  begin
    insert into public.notification_outbox
      (tenant_id, kind, recipient, locale, subject, body_text, body_html, status)
    values ('00000000-0000-0000-0000-000000000001', 'ai.approval_requested',
            'a@example.test', 'en', 's', 't', '<p>h</p>', 'sent');
    raise exception 'notification_outbox: a message said it was sent and named no time';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.notification_outbox
      (tenant_id, kind, recipient, locale, subject, body_text, body_html, status)
    values ('00000000-0000-0000-0000-000000000001', 'ai.approval_requested',
            'a@example.test', 'en', 's', 't', '<p>h</p>', 'abandoned');
    raise exception 'notification_outbox: a message was given up on with no reason';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.notification_outbox
      (tenant_id, kind, recipient, locale, subject, body_text, body_html)
    values ('00000000-0000-0000-0000-000000000001', 'NotDotted',
            'a@example.test', 'en', 's', 't', '<p>h</p>');
    raise exception 'notification_outbox: a kind that is not dotted lower-case was accepted';
  exception
    when check_violation then null;
  end;

  raise notice 'notification outbox, a row cannot lie about itself: ok';
end
$$;

rollback;
