-- AI usage beyond the allowance: pay as you go, stamped per call.
--
-- Three columns on `ai_usage_events`, none of which changes what a tenant
-- can see. `over_allowance` is set when the call was made after the month's
-- allowance was spent and the organization had turned pay as you go on.
-- `billable_micros` is what the customer is charged for it -- the call's
-- list-price cost times `overage_rate_percent`, the staff-set multiplier in
-- force at the time -- and both are copied onto the row so a later change to
-- the multiplier never rewrites a past month. Null inside the allowance.
--
-- The provisioning read policy from 00007 already admits the platform's
-- aggregate read, which now sums these too.

alter table public.ai_usage_events
  add column if not exists over_allowance boolean not null default false,
  add column if not exists billable_micros bigint
    check (billable_micros is null or billable_micros >= 0),
  add column if not exists overage_rate_percent integer
    check (overage_rate_percent is null or overage_rate_percent > 0);
