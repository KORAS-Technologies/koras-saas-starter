-- Migration: 00027_hold_expiry_pins_the_row
--
-- The sweep that closes out a bounded hold may change its status and nothing
-- else.
--
-- `legal_holds_expire_provisioning` in `00024` has a tight `using` clause --
-- active, bounded, past its end date -- and a `with check` that says only
-- `status = 'expired'`. A row-level security `with check` cannot see the old
-- row, so it cannot say "and everything else is unchanged". One statement on
-- the provisioning context could therefore expire a hold *and* move it to
-- another tenant, or rewrite its reason, in the same UPDATE.
--
-- `00020` says a hold is evidence. Evidence that can be rewritten by the
-- process whose job is to retire it is not evidence. A security review found
-- this on 2026-09-16; nothing reachable does it -- `governance_expiry.py` sets
-- `status` alone -- which is exactly the kind of gap that survives until
-- somebody adds a column to that statement.
--
-- A trigger, because it is the only thing in Postgres that sees both rows.

create or replace function public.legal_hold_expiry_changes_status_only()
returns trigger as $$
begin
  -- Only the platform's own sweep is constrained here. A tenant changing its
  -- own hold goes through the routes, which have the two-person rule and an
  -- audit row; this is about the one actor that has neither.
  if not public.is_provisioning() then
    return new;
  end if;

  if new.tenant_id is distinct from old.tenant_id
     or new.scope is distinct from old.scope
     or new.reason is distinct from old.reason
     or new.requested_by is distinct from old.requested_by
     or new.approved_by is distinct from old.approved_by
     or new.starts_at is distinct from old.starts_at
     or new.ends_at is distinct from old.ends_at
     or new.created_at is distinct from old.created_at then
    raise exception
      'a sweep may change a legal hold''s status and nothing else'
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$$ language plpgsql;

drop trigger if exists legal_holds_expiry_is_status_only on public.legal_holds;
create trigger legal_holds_expiry_is_status_only
  before update on public.legal_holds
  for each row execute function public.legal_hold_expiry_changes_status_only();

comment on function public.legal_hold_expiry_changes_status_only() is
  'Refuses any provisioning-context update to a legal hold that changes more '
  'than its status. A row-level security policy cannot express this: its '
  'with-check clause cannot see the old row.';
