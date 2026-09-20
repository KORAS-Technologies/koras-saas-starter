-- The one organisation the round-trip suite signs in as.
--
-- Applied after the migrations, before the suite. Idempotent, because a run
-- that cannot be repeated is a run somebody deletes the database to retry.
--
-- ## Why these exact values
--
-- `zitadel_org_id` is what `resolve_tenant` looks a tenant up by, and it must
-- equal the `organizationId` in `e2e/support/session.ts`. `user_id` is what the
-- token's subject carries, and it is what every row-level policy keyed to a
-- person resolves through. Change either and the suite signs in successfully
-- and then sees nothing, which reads as a broken feature rather than a broken
-- fixture -- so both are asserted by `roundtrip/identity.spec.ts` before
-- anything else runs.
--
-- ## What is deliberately not here
--
-- No files, no notifications, no import runs, no settings values. Every
-- round-trip test writes what it needs and asserts what it wrote; a fixture
-- that pre-seeded them would let a test pass against data it did not create,
-- which is how a suite starts proving that the seed script works.

-- ── A role row-level security applies to ─────────────────────────────────────
--
-- **The API refuses to start without one**, and finding that out was the first
-- thing this harness did. `verify_rls_enforcement` runs in the lifespan and
-- raises `RlsNotEnforced` when the connection's role is granted BYPASSRLS:
-- "every tenant policy is inert and queries can return other tenants' rows".
--
-- Connecting as `postgres` would therefore have produced a suite in which every
-- isolation assertion passed vacuously -- the worst possible outcome for a
-- harness whose whole purpose is to check that a customer sees their own rows
-- and nobody else's. The guard caught it on the first run, which is the
-- argument for having a guard rather than a comment.
--
-- The same arrangement `generator-integration.yml` already makes for the
-- row-level security suite, for the same reason.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'koras_e2e_app') then
    create role koras_e2e_app login password 'koras_e2e_app' nobypassrls;
  end if;
end
$$;

grant usage on schema public to koras_e2e_app;
grant select, insert, update, delete on all tables in schema public to koras_e2e_app;
grant usage, select on all sequences in schema public to koras_e2e_app;
-- Tables a later migration adds, so a seed run before one does not leave the
-- API unable to read it.
alter default privileges in schema public
  grant select, insert, update, delete on tables to koras_e2e_app;
alter default privileges in schema public grant usage, select on sequences to koras_e2e_app;

insert into public.tenants (id, slug, name, zitadel_org_id, status, owner_email)
values (
  '00000000-0000-4e2e-8000-000000000001',
  'e2e',
  'End-to-end organisation',
  'e2e-organization',
  'active',
  'owner@example.com'
)
on conflict (zitadel_org_id) do update set
  status = 'active',
  name = excluded.name;

-- Two members, not one. A person's own preference is stored against their
-- subject and read back the same way, and the only way to check from a browser
-- that one member's value is not another's is to have a second member. A suite
-- with one would pass against a settings store that ignored the subject
-- entirely.
insert into public.tenant_members (tenant_id, user_id, role)
values
  ('00000000-0000-4e2e-8000-000000000001', 'e2e-subject', 'organization_admin'),
  ('00000000-0000-4e2e-8000-000000000001', 'e2e-colleague', 'organization_admin')
on conflict (tenant_id, user_id) do update set role = excluded.role;
