-- A notification belongs to one person in one tenant, and to nobody else.
--
-- Three properties, and the second is the one a tenant-only policy gets wrong.
--
-- **A colleague's feed is not readable.** Every other tenant-owned table here
-- admits anybody in the tenant; this one does not, and the difference is
-- deliberate: a notification is addressed to a person, so an owner who could
-- read every member's feed would be reading their colleagues' mail. There is no
-- administrator policy, and this suite is what says that was a decision.
--
-- **Anyone in the tenant may write for anyone in the tenant.** Insert is scoped
-- to the tenant and not to the caller, because a notification is almost always
-- written for somebody else -- the request that uploads a file tells the
-- approvers, and none of them is the caller. So the insert case that must fail
-- is the *cross-tenant* one, not the cross-person one.
--
-- **An update cannot move a row.** Marking read is the only update a person
-- makes, and an update policy without a `with check` would let that same
-- statement rewrite `user_id` and hand the row to somebody else.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-ntf-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-ntf-beta', 'Beta');

insert into public.notifications (id, tenant_id, user_id, kind, title, url)
values
  ('00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000001', 'user-alpha',
   'files.uploaded', 'A file arrived', '/dashboard/files'),
  ('00000000-0000-0000-0000-0000000000a2',
   '00000000-0000-0000-0000-000000000001', 'user-alpha',
   'ai.approval_requested', 'An action needs approval', ''),
  ('00000000-0000-0000-0000-0000000000a3',
   '00000000-0000-0000-0000-000000000001', 'user-alpha-colleague',
   'files.uploaded', 'A file arrived for somebody else', ''),
  ('00000000-0000-0000-0000-0000000000b1',
   '00000000-0000-0000-0000-000000000002', 'user-beta',
   'files.uploaded', 'A file arrived in another tenant', '');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
declare
  visible integer;
  marked timestamptz;
begin
  -- ── reads: mine, and only mine ───────────────────────────────────────────
  select count(*) into visible from public.notifications;
  if visible <> 2 then
    raise exception 'notifications: expected 2 visible rows, saw %', visible;
  end if;

  select count(*) into visible
  from public.notifications where user_id = 'user-alpha-colleague';
  if visible <> 0 then
    raise exception 'notifications: a colleague''s notification was visible';
  end if;

  select count(*) into visible
  from public.notifications
  where tenant_id = '00000000-0000-0000-0000-000000000002';
  if visible <> 0 then
    raise exception 'notifications: another tenant''s notification was visible';
  end if;

  -- The query the shell runs on every dashboard load.
  select count(*) into visible from public.notifications where read_at is null;
  if visible <> 2 then
    raise exception 'notifications: unread count saw % rows, expected 2', visible;
  end if;

  -- ── marking read ─────────────────────────────────────────────────────────
  update public.notifications set read_at = now()
   where id = '00000000-0000-0000-0000-0000000000a1';
  select read_at into marked from public.notifications
   where id = '00000000-0000-0000-0000-0000000000a1';
  if marked is null then
    raise exception 'notifications: could not mark my own notification read';
  end if;

  update public.notifications set read_at = now()
   where user_id = 'user-alpha-colleague';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'notifications: a colleague''s notification was marked read';
  end if;

  -- The case the `with check` exists for: one statement that reads as marking
  -- read and also hands the row to somebody else.
  begin
    update public.notifications
       set read_at = now(), user_id = 'user-alpha-colleague'
     where id = '00000000-0000-0000-0000-0000000000a2';
    raise exception 'notifications: an update moved a row to another person';
  exception
    when insufficient_privilege then null;
  end;

  -- ── writing for a colleague is allowed; writing into another tenant is not ─
  insert into public.notifications (tenant_id, user_id, kind, title)
  values ('00000000-0000-0000-0000-000000000001', 'user-alpha-colleague',
          'files.uploaded', 'Told about a file I uploaded');

  begin
    insert into public.notifications (tenant_id, user_id, kind, title)
    values ('00000000-0000-0000-0000-000000000002', 'user-beta',
            'files.uploaded', 'Across the wall');
    raise exception 'notifications: a row was inserted into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- ── dismissing ───────────────────────────────────────────────────────────
  delete from public.notifications
   where id = '00000000-0000-0000-0000-0000000000a1';
  select count(*) into visible from public.notifications
   where id = '00000000-0000-0000-0000-0000000000a1';
  if visible <> 0 then
    raise exception 'notifications: could not dismiss my own notification';
  end if;

  delete from public.notifications where user_id = 'user-alpha-colleague';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'notifications: a colleague''s notification was deleted';
  end if;

  raise notice 'notifications, one person one feed: ok';
end
$$;

-- ── no subject, no feed ──────────────────────────────────────────────────────
--
-- The worker and the platform's collectors declare a tenant and no person. The
-- tenant policies alone would admit every row in alpha, which is why this case
-- is worth its own block.
do $$
declare
  visible integer;
begin
  perform set_config('app.user_id', '', true);

  select count(*) into visible from public.notifications;
  if visible <> 0 then
    raise exception 'notifications: % rows visible with no subject declared', visible;
  end if;

  raise notice 'notifications, no subject fails closed: ok';
end
$$;

-- ── what the database refuses whatever the caller ────────────────────────────
reset role;

do $$
begin
  begin
    insert into public.notifications (tenant_id, user_id, kind, title, url)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'files.uploaded', 'Click here', 'https://example.invalid/phish');
    raise exception 'notifications: an absolute URL was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.notifications (tenant_id, user_id, kind, title, url)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'files.uploaded', 'Click here', '//example.invalid/phish');
    raise exception 'notifications: a protocol-relative URL was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.notifications (tenant_id, user_id, kind, title)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'NotAKind', 'Untitled');
    raise exception 'notifications: a kind that is not dotted lower-case was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.notifications (tenant_id, user_id, kind, title)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'files.uploaded', '   ');
    raise exception 'notifications: a blank title was accepted';
  exception
    when check_violation then null;
  end;

  raise notice 'notifications, the database refuses a link it did not make: ok';
end
$$;

rollback;
