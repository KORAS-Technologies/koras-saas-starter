-- AI knowledge: the customer's own documents, chunked and embedded, per tenant.
--
-- Retrieval lets the assistant answer from what an organization has uploaded
-- rather than from what the model remembers. The store is pgvector, in this
-- database: the same row-level security as every other table, the same
-- backup, and no second service holding a copy of customer content that
-- could be scoped differently.
--
-- One row per chunk of one document. `resource_type` and `resource_id` say
-- where the text came from -- a file, today -- so a deleted file's chunks
-- can be found and removed, and a citation can point back. The embedding is
-- 1536 wide, the dimension every embedding model in the platform's
-- catalogue answers with; a model of another width is a second column and a
-- migration, not a silent reinterpretation.
--
-- The tenant policies are the usual ones. There is no provisioning policy:
-- the platform never reads a customer's documents, and the retention sweep
-- does not touch knowledge, because a document is current until its file is
-- deleted, whenever that is.

create extension if not exists vector;

create table public.ai_knowledge_chunks (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references public.tenants(id) on delete cascade,
  document_id    text not null,
  resource_type  text not null,
  resource_id    text not null,
  title          text not null,
  chunk_index    integer not null check (chunk_index >= 0),
  content        text not null,
  embedding      vector(1536) not null,
  metadata       jsonb not null default '{}',
  created_at     timestamptz not null default now(),
  unique (tenant_id, document_id, chunk_index)
);

create index ai_knowledge_chunks_tenant_resource_idx
  on public.ai_knowledge_chunks (tenant_id, resource_type, resource_id);

-- HNSW over cosine distance, which is what the query uses. Built per tenant
-- by the planner's filter on tenant_id first; the index is one across
-- tenants because a partial index per tenant is not a thing Postgres does.
create index ai_knowledge_chunks_embedding_idx
  on public.ai_knowledge_chunks using hnsw (embedding vector_cosine_ops);

alter table public.ai_knowledge_chunks enable row level security;
alter table public.ai_knowledge_chunks force row level security;

drop policy if exists "ai_knowledge_chunks_select_own_tenant" on public.ai_knowledge_chunks;
create policy "ai_knowledge_chunks_select_own_tenant"
  on public.ai_knowledge_chunks for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "ai_knowledge_chunks_insert_own_tenant" on public.ai_knowledge_chunks;
create policy "ai_knowledge_chunks_insert_own_tenant"
  on public.ai_knowledge_chunks for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_knowledge_chunks_delete_own_tenant" on public.ai_knowledge_chunks;
create policy "ai_knowledge_chunks_delete_own_tenant"
  on public.ai_knowledge_chunks for delete
  using (tenant_id = public.current_tenant_id());
