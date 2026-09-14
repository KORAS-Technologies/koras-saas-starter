-- Knowledge chunks: a tenant searches its own documents and never another's.
--
-- The nearest chunk in the whole table belongs to the other tenant on
-- purpose. A search that returned it would be the leak retrieval makes
-- possible and the policies exist to prevent.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-know-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-know-beta', 'Beta');

-- Two chunks, one per tenant. Beta's embedding is the query vector itself;
-- alpha's points the other way. pgvector wants a literal, and repeat() is
-- the clearest way to build a 1536-wide one.
insert into public.ai_knowledge_chunks
  (tenant_id, document_id, resource_type, resource_id, title, chunk_index, content, embedding)
values
  ('00000000-0000-0000-0000-000000000001', 'file-a', 'file', 'file-a', 'Alpha notes', 0, 'alpha content',
   ('[0,1' || repeat(',0', 1534) || ']')::vector),
  ('00000000-0000-0000-0000-000000000002', 'file-b', 'file', 'file-b', 'Beta secret', 0, 'beta content',
   ('[1' || repeat(',0', 1535) || ']')::vector);

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  nearest text;
  visible integer;
begin
  -- The query vector is beta's exactly. Alpha must still get alpha's chunk.
  select title into nearest
  from public.ai_knowledge_chunks
  order by embedding <=> ('[1' || repeat(',0', 1535) || ']')::vector
  limit 1;
  if nearest <> 'Alpha notes' then
    raise exception 'knowledge: tenant alpha''s nearest chunk was %', nearest;
  end if;

  select count(*) into visible from public.ai_knowledge_chunks;
  if visible <> 1 then
    raise exception 'knowledge: tenant alpha sees % chunks, expected 1', visible;
  end if;

  begin
    insert into public.ai_knowledge_chunks
      (tenant_id, document_id, resource_type, resource_id, title, chunk_index, content, embedding)
    values
      ('00000000-0000-0000-0000-000000000002', 'file-x', 'file', 'file-x', 'x', 0, 'x',
       ('[1' || repeat(',0', 1535) || ']')::vector);
    raise exception 'knowledge: a chunk was written into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  delete from public.ai_knowledge_chunks where document_id = 'file-b';
  if found then
    raise exception 'knowledge: another tenant''s chunk was deleted';
  end if;

  raise notice 'knowledge isolation: ok';
end
$$;

rollback;
