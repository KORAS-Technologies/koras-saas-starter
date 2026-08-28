# KORAS SaaS Starter — Environment Strategy

## Overview

Every KORAS project — regardless of profile — maintains four isolated environments
that map immutably to Git branches.

---

## 1. Environment and Branch Mapping

| Environment | Git Branch | Purpose                                          |
|-------------|------------|--------------------------------------------------|
| `dev`       | `develop`  | Active development; fast feedback; may be broken |
| `test`      | `test`     | Automated testing; integration suites            |
| `stg`       | `staging`  | Pre-production; stakeholder sign-off             |
| `prod`      | `main`     | Live production traffic                          |

This mapping is **immutable**. It may only be changed by an explicit Architecture
Decision Record (ADR). No tooling, CI pipeline, or Terraform module may deviate
from this mapping without a corresponding ADR.

---

## 2. Environment Isolation

Each environment is physically isolated:

### Supabase

Four separate Supabase projects:

```
<project>-dev
<project>-test
<project>-stg
<project>-prod
```

Each is an independent PostgreSQL instance with its own:
- Connection string
- `anon` key
- `service_role` key
- Storage bucket namespace

Data never flows between environments except via deliberate, audited migration
scripts.

### ZITADEL

Four separate ZITADEL instances maintained at the platform level:

```
ZITADEL DEV
ZITADEL TEST
ZITADEL STG
ZITADEL PROD
```

Each project creates one ZITADEL project (not suffixed) within the appropriate
instance:

```
ZITADEL DEV  →  <project>
ZITADEL TEST →  <project>
ZITADEL STG  →  <project>
ZITADEL PROD →  <project>
```

User identities, client IDs, and tokens are fully isolated. A dev ZITADEL
token cannot be used against a prod API.

### Doppler

Four Doppler environments per project:

```
<project>-dev
<project>-test
<project>-stg
<project>-prod
```

Doppler is the sole source of truth for all secrets. Secrets never leave
Doppler into source control, Docker images, or CI logs.

### Fly.io

Each service creates a Fly app per environment:

```
<project>-api-dev
<project>-api-test
<project>-api-stg
<project>-api-prod
```

Fly secrets are populated from Doppler via CI/CD.

### Vercel

**One project per application per environment.** Eight for a product with `web`
and `admin`, named the same way the Fly apps are:

```
<project>-web-dev      <project>-admin-dev
<project>-web-test     <project>-admin-test
<project>-web-stg      <project>-admin-stg
<project>-web-prod     <project>-admin-prod
```

Each has exactly one estate. Its `production_branch` is that environment's
branch — `develop` for dev, `test`, `staging` for stg, `main` for prod — so the
project's own *production* target holds that environment's settings, and its own
domain points at it:

| Environment | `web` | `admin` |
|-------------|-------|---------|
| dev  | `app-dev.<project>.<apex>`  | `admin-dev.<project>.<apex>` |
| test | `app-test.<project>.<apex>` | `admin-test.<project>.<apex>` |
| stg  | `app-stg.<project>.<apex>`  | `admin-stg.<project>.<apex>` |
| prod | `app.<project>.<apex>`      | `admin.<project>.<apex>` |

`web` is served at `app`, not `web` — `application_hostnames` maps it. Two
spellings of the same hostname is how a redirect URI stops matching the domain
it was issued for.

**Not one project with preview and production targets**, which is what this
section used to describe and what nothing has ever built. That arrangement needs
Vercel's preview environment to carry dev, test and staging settings at once,
which it cannot, so it ends with one working application environment and dev
credentials living in a target named production.

The cost is eight projects instead of two, and it matches how the rest of the
estate is already arranged: four Supabase projects, four ZITADEL instances,
eight Fly apps.

Environment variables are populated from Doppler.

---

## 3. GitHub Branch Configuration

### Branch protection rules

| Branch    | Require PR | Required approvals | Status checks required | Force-push | Deletion |
|-----------|------------|-------------------|------------------------|------------|----------|
| `develop` | No         | 0                 | CI pass                | Allowed    | Blocked  |
| `test`    | Yes        | 1                 | CI pass                | Blocked    | Blocked  |
| `staging` | Yes        | 1                 | CI pass + integration  | Blocked    | Blocked  |
| `main`    | Yes        | 2                 | CI pass + integration  | Blocked    | Blocked  |

### GitHub Environments

GitHub Environments are configured to enforce deployment gates:

| GitHub Env | Deployment gate                              |
|------------|----------------------------------------------|
| `dev`      | None — auto-deploy on push to `develop`      |
| `test`     | None — auto-deploy on push to `test`         |
| `stg`      | Required reviewer — at least one approval    |
| `prod`     | Required reviewer — at least two approvals   |

### Promotion flow

```
develop  →  test  →  staging  →  main
   dev   →  test  →    stg    →  prod
```

Promotion between branches is always forward. There is no mechanism to deploy
`main` to `dev`. Hotfixes to `prod` are cherry-picked to `develop` post-deploy.

---

## 4. Environment Variables per Environment

All environment variable names are identical across environments. Only values differ.

Variable injection chain:

```
Doppler (<project>-<env>)
    ↓
CI/CD job (GitHub Actions / Fly deploy / Vercel deploy)
    ↓
Running service
```

No `.env` files are committed. No secrets appear in CI logs.

The exception is `.env.local.example` files checked into `local/config/` which
contain only placeholder values (never real secrets) for developer onboarding.

---

## 5. Database Migration Strategy

Migrations are managed with:
- **Supabase CLI** for schema migrations
- **Alembic** for SQLAlchemy model migrations (Python services)

### Migration promotion

1. Migrations are authored against `dev`
2. Promoted to `test` via the CI pipeline on merge to `test`
3. Promoted to `stg` via the deployment pipeline on merge to `staging`
4. Promoted to `prod` via the deployment pipeline on merge to `main`, with a
   mandatory pre-apply dry-run and backup

Migrations are **never applied directly against `prod`** outside the pipeline.

### Rollback

All migrations include a corresponding down migration. Rollback is invoked
manually by an authorized operator after incident review — never automatically.

---

## 6. Secrets Rotation Policy

| Secret type        | Rotation frequency | Owner      |
|--------------------|-------------------|------------|
| Supabase keys      | Quarterly         | DevOps     |
| ZITADEL tokens     | Quarterly         | DevOps     |
| Fly deploy tokens  | Quarterly         | DevOps     |
| Vercel tokens      | Quarterly         | DevOps     |
| API keys (third-party) | Per vendor  | DevOps     |
| Database passwords | On breach or quarterly | DevOps |

Rotation is performed in Doppler and then redeployed. No code changes required.

---

## 7. Observability per Environment

All four environments have observability enabled:

| Stack           | Tool                      |
|-----------------|---------------------------|
| Metrics         | Prometheus / Grafana Cloud |
| Logs            | Loki / Grafana Cloud       |
| Traces          | Tempo / Grafana Cloud      |
| Error tracking  | Sentry                     |
| Uptime          | BetterStack / Grafana      |

Production alerting is more aggressive (lower thresholds, PagerDuty escalation).
Development observability is local Docker Compose only.

---

## 8. Environment-Specific Configuration Reference

There are no `environments/*.tfvars` files, and no `vercel_target`. Both were
planned and neither was built; the section below described them for long enough
that someone could have gone looking.

One configuration provisions all four environments in a single apply, because
the estate is four of everything rather than one thing deployed four times.
There are two files, and only one of them is per-project:

`infrastructure/terraform/terraform.tfvars`, generated once, holds what
identifies the project and what it is made of — `project_name`, `project_slug`,
`primary_domain`, `enabled_apps`, `enabled_services`, `supabase_region`,
`enable_waf`, and a `fly_regions` map keyed by the four environment names.

Everything credential-shaped arrives from Doppler as `TF_VAR_*` and is never
written to a file: `TF_VAR_supabase_environments` and `TF_VAR_zitadel_instances`
are assembled per environment by the CLI from the individual estate secrets.

The branch mapping is not configurable per project. It is the default of
`environment_branches` in the `project-bootstrap` module:

```hcl
default = {
  dev  = "develop"
  test = "test"
  stg  = "staging"
  prod = "main"
}
```

which is §1's table, in the one place that builds from it. Changing it needs an
ADR.

`prevent_destroy` is set in the modules on the resources that hold data or serve
traffic, for every environment rather than only production. See
INFRASTRUCTURE_PLAN.md.

---

## 9. ADR Requirement

Any change to the environment naming, branch naming, or branch-to-environment
mapping requires:

1. A new ADR filed in `docs/adr/`
2. Review and approval by the Architecture team
3. Updates to all tooling, pipelines, and this document before the change is
   considered complete
