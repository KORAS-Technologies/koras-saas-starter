-- Migration: 00001_initial
-- Creates core tenant foundation with RLS

-- ── Extensions ──────────────────────────────────────────────────────────────
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- ── Tenants ─────────────────────────────────────────────────────────────────
create table public.tenants (
  id          uuid primary key default gen_random_uuid(),
  slug        text unique not null,
  name        text not null,
  plan        text not null default 'free',
  settings    jsonb not null default '{}',
  zitadel_org_id text unique,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table public.tenants enable row level security;

-- ── Tenant members ───────────────────────────────────────────────────────────
create table public.tenant_members (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants(id) on delete cascade,
  user_id     text not null,                -- ZITADEL subject (sub)
  role        text not null default 'member',
  created_at  timestamptz not null default now(),
  unique (tenant_id, user_id)
);

alter table public.tenant_members enable row level security;

-- ── Tenant settings ──────────────────────────────────────────────────────────
create table public.tenant_settings (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants(id) on delete cascade unique,
  branding    jsonb not null default '{}',
  domains     text[] not null default '{}',
  features    jsonb not null default '{}',
  updated_at  timestamptz not null default now()
);

alter table public.tenant_settings enable row level security;

-- ── RLS context helper ───────────────────────────────────────────────────────
-- app.tenant_id is set per-transaction by the API (koras-database.set_rls_context)
create or replace function public.current_tenant_id() returns uuid as $$
  select nullif(current_setting('app.tenant_id', true), '')::uuid;
$$ language sql stable;

create or replace function public.current_user_id() returns text as $$
  select nullif(current_setting('app.user_id', true), '');
$$ language sql stable;

-- ── Update trigger ───────────────────────────────────────────────────────────
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create trigger tenants_updated_at
  before update on public.tenants
  for each row execute function public.set_updated_at();

create trigger tenant_settings_updated_at
  before update on public.tenant_settings
  for each row execute function public.set_updated_at();
