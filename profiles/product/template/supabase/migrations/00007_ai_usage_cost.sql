-- AI usage: what a call cost, and a way for the platform to read the month.
--
-- Two additions to `ai_usage_events`, neither of which changes what a tenant
-- can see.
--
-- `estimated_cost_micros` is the vendor's list price for the tokens the call
-- used, in millionths of a US dollar, stamped when the row is written from the
-- prices the routing policy carried. Null when the policy carried none: an
-- estimate of nothing is not zero, and a later price list must not be applied
-- backwards to calls made under a different one.
--
-- The provisioning read policy lets the private platform API -- a machine
-- identity, on the provisioning session, reachable from exactly one router --
-- aggregate usage across every tenant so the Control Plane can collect it.
-- Read only: no insert, update or delete policy for that context, because the
-- platform reports usage and never writes it.

alter table public.ai_usage_events
  add column if not exists estimated_cost_micros bigint
    check (estimated_cost_micros is null or estimated_cost_micros >= 0);

drop policy if exists "ai_usage_events_select_provisioning" on public.ai_usage_events;
create policy "ai_usage_events_select_provisioning"
  on public.ai_usage_events for select
  using (public.is_provisioning());
