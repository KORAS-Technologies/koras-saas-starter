-- AI retention: the worker may delete old conversations, and nothing else may.
--
-- Messages hold what a customer said to the assistant and what it answered,
-- and until now nothing deleted them. The worker's retention sweep removes
-- conversations older than the product's retention period, across every
-- tenant, on the provisioning session -- the one context that reaches all
-- tenants, and the one no customer request runs under.
--
-- One policy, on conversations. Messages and actions reference a
-- conversation with `on delete cascade`, and a cascade is the system's own
-- write rather than the caller's, so it is not subject to the referencing
-- tables' policies. Usage rows are not touched: their conversation id is
-- set null by the same cascade and the metering stays, because a call that
-- happened is a fact whatever became of the conversation it was part of.
--
-- Two policies, both on conversations: delete, and the select a delete with
-- a WHERE clause needs -- Postgres applies the select policies to the rows a
-- qualified DELETE considers, so a delete policy alone finds nothing. No
-- insert and no update for this context, on any AI table, and no select on
-- messages or actions: the sweep never reads content.

drop policy if exists "ai_conversations_select_provisioning" on public.ai_conversations;
create policy "ai_conversations_select_provisioning"
  on public.ai_conversations for select
  using (public.is_provisioning());

drop policy if exists "ai_conversations_delete_provisioning" on public.ai_conversations;
create policy "ai_conversations_delete_provisioning"
  on public.ai_conversations for delete
  using (public.is_provisioning());
