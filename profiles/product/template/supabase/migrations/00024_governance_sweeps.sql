-- What the worker may see of the two export tables, and of the holds it closes.
--
-- Every sweep this migration exists for runs in the worker, which holds no
-- customer token and therefore no tenant context. Three things it could not do:
--
--   * know which stored objects an export claims, so reconciliation reported
--     every export a customer had ever produced as an orphan;
--   * remove an artifact once its expiry passed, which until now happened only
--     if somebody opened the exports list;
--   * close out a bounded legal hold, so the row went on reading `active` for
--     ever after it had stopped holding anything.

-- Audit exports: read and delete, because the expiry sweep does both.
drop policy if exists "audit_exports_select_provisioning" on public.audit_exports;
create policy "audit_exports_select_provisioning"
  on public.audit_exports for select
  using (public.is_provisioning());

drop policy if exists "audit_exports_delete_provisioning" on public.audit_exports;
create policy "audit_exports_delete_provisioning"
  on public.audit_exports for delete
  using (public.is_provisioning());

-- Reporting's exports are read differently, and the difference is deliberate.
-- `130_report_schedules_isolation.sql` asserts that the worker sees no report
-- export at all, and that property is worth keeping: such a row carries the
-- report, the filename and who asked for it, and the sweep needs none of them.
-- It needs storage keys.
--
-- So a function returning keys and nothing else, `security definer` so it can
-- read past the tenant policies, with the provisioning context as a condition
-- of the select rather than a statement before it -- a SQL function returns its
-- last statement, so a guard written as an earlier statement guards nothing.
--
-- `report_exports` arrives with the reporting capability. A product generated
-- without it has no such table, so the body is assembled conditionally: a
-- migration that fails on a legitimately absent table stops every later one.
do $$
declare
  extra text := '';
begin
  if to_regclass('public.report_exports') is not null then
    extra := ' union all '
          || 'select storage_key from public.report_exports '
          || ' where tenant_id = p_tenant_id and storage_key is not null '
          || '   and public.is_provisioning()';
  end if;

  execute 'create or replace function public.claimed_storage_keys(p_tenant_id uuid) '
       || 'returns setof text as $fn$ '
       || 'select storage_key from public.audit_exports '
       || ' where tenant_id = p_tenant_id and storage_key is not null '
       || '   and public.is_provisioning()'
       || extra
       || '$fn$ language sql stable security definer set search_path = public, pg_temp';
end $$;

comment on function public.claimed_storage_keys(uuid) is
  'Storage keys an export claims, for the reconciliation sweep. Keys only: an '
  'object with no files row is not an orphan merely because files does not '
  'know it. Returns nothing outside the provisioning context.';

-- A bounded hold stops holding at its end date -- `under_legal_hold` has always
-- read `ends_at`, so enforcement was never wrong. What was wrong is the label:
-- the row went on saying `active`, so the holds list and the platform's
-- governance counts both overstated how much of the estate was under hold.
--
-- The policy is written as tightly as a policy can be: only a row that is
-- active, bounded and past its date may be updated at all, and only into
-- `expired`. It cannot release a hold, cannot activate one, and cannot touch an
-- open-ended one -- those stay decisions with a person behind them.
drop policy if exists "legal_holds_expire_provisioning" on public.legal_holds;
create policy "legal_holds_expire_provisioning"
  on public.legal_holds for update
  using (
    public.is_provisioning()
    and status = 'active'
    and ends_at is not null
    and ends_at < now()
  )
  with check (public.is_provisioning() and status = 'expired');
