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

-- ── Why these tables carry RLS and no policies ───────────────────────────────
--
-- Deliberate, and the opposite of the product profile's arrangement.
--
-- The Control Plane has no tenant model in the database. It is the platform
-- authority, and authorisation is by platform role, checked in the API through
-- `PlatformAuthDep`. There is no `current_tenant_id()` here because there is no
-- tenant to scope a row to.
--
-- RLS is enabled anyway as a deny-by-default backstop: a table with RLS on and
-- no policy denies every role RLS applies to, so anything that reaches this
-- database without being the service role reads nothing. The service role
-- bypasses RLS, which is how the API reads at all.
--
-- Consequently this schema must NOT use `force row level security`. `force`
-- binds the table owner to the policies, and there are none, so forcing it
-- denies the owner too and every query returns nothing. It was briefly added
-- here by a change that applied the product profile's fix to both profiles
-- without checking that both profiles meant the same thing by RLS. They do not.
--
-- The product profile's rule -- force RLS, connect as a role that cannot bypass
-- it -- is right for a schema whose policies do the scoping. Applying it to a
-- schema whose policies are deliberately absent is a lock-out.
