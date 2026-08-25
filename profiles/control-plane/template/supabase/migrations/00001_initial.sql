-- Migration: 00001_initial
-- KORAS Control Plane platform schema
-- No customer tenant tables — this is the provisioning authority

-- ── Extensions ──────────────────────────────────────────────────────────────
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- ── Products ─────────────────────────────────────────────────────────────────
create table public.products (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  slug            text unique not null,
  status          text not null default 'active',
  github_repo     text,
  zitadel_project text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

alter table public.products enable row level security;

-- ── Organizations ────────────────────────────────────────────────────────────
create table public.organizations (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  slug            text unique not null,
  zitadel_org_id  text unique,
  status          text not null default 'active',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

alter table public.organizations enable row level security;

-- ── Subscriptions ────────────────────────────────────────────────────────────
create table public.subscriptions (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id),
  product_id      uuid not null references public.products(id),
  plan            text not null,
  status          text not null default 'active',
  trial_ends_at   timestamptz,
  current_period_start timestamptz not null default now(),
  current_period_end   timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, product_id)
);

alter table public.subscriptions enable row level security;

-- ── Entitlements ─────────────────────────────────────────────────────────────
create table public.entitlements (
  id              uuid primary key default gen_random_uuid(),
  subscription_id uuid not null references public.subscriptions(id) on delete cascade,
  feature         text not null,
  limit_value     int,
  enabled         boolean not null default true,
  created_at      timestamptz not null default now(),
  unique (subscription_id, feature)
);

alter table public.entitlements enable row level security;

-- ── Infrastructure registry ──────────────────────────────────────────────────
create table public.infrastructure_resources (
  id              uuid primary key default gen_random_uuid(),
  product_id      uuid not null references public.products(id),
  environment     text not null,
  provider        text not null,
  resource_type   text not null,
  resource_id     text not null,
  metadata        jsonb not null default '{}',
  created_at      timestamptz not null default now()
);

alter table public.infrastructure_resources enable row level security;

-- ── Update trigger ───────────────────────────────────────────────────────────
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create trigger products_updated_at
  before update on public.products for each row execute function public.set_updated_at();
create trigger organizations_updated_at
  before update on public.organizations for each row execute function public.set_updated_at();
create trigger subscriptions_updated_at
  before update on public.subscriptions for each row execute function public.set_updated_at();

-- ── Force RLS for the owner ──────────────────────────────────────────────────
--
-- `enable row level security` exempts the table's owner, and both the
-- migrations and the API arrive as the owner. Without `force`, every policy
-- below is skipped by the only connection that reads this data -- the policies
-- are present, correct, and never consulted.
--
-- The exemption exists so an owner can always recover a table it has locked
-- itself out of. That is a maintenance affordance, and it is the wrong default
-- for a connection serving tenant traffic. A migration that needs to bypass
-- policies can still `alter table ... no force` deliberately, in its own
-- migration, where it is visible.

alter table public.products force row level security;
alter table public.organizations force row level security;
alter table public.subscriptions force row level security;
alter table public.entitlements force row level security;
alter table public.infrastructure_resources force row level security;
