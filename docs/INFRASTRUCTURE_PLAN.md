# KORAS SaaS Starter — Infrastructure Plan

## Overview

This document defines the Terraform module strategy, provisioning targets,
environment isolation approach, and infrastructure governance rules for all
KORAS projects — both `product` and `control-plane` profile.

---

## 1. Infrastructure Targets

Every KORAS project provisions resources across seven platforms:

| Platform      | Purpose                                     | Module                        |
|---------------|---------------------------------------------|-------------------------------|
| GitHub        | Source repository, branches, environments   | `modules/github`              |
| Doppler       | Secret management per environment           | `modules/doppler`             |
| Supabase      | Isolated PostgreSQL databases per env       | `modules/supabase`            |
| ZITADEL       | Identity provider project per ZITADEL inst. | `modules/zitadel`             |
| Vercel        | Frontend application hosting                | `modules/vercel`              |
| Fly.io        | Backend service hosting                     | `modules/fly`                 |
| Cloudflare    | DNS, CDN, WAF                               | `modules/cloudflare`          |

The `modules/project-bootstrap` orchestration module calls all seven modules
with the correct inputs derived from the generator context.

---

## 2. Module Design Principles

### Principle 1 — Profile awareness lives in `project-bootstrap` only

Individual modules (`github`, `doppler`, etc.) are profile-agnostic.
They receive explicit variables describing exactly what to create.
The `project-bootstrap` module translates profile capabilities into module inputs.

This means adding a new profile requires updating only `project-bootstrap`, not
every individual module.

### Principle 2 — No auto-apply

`terraform apply` is never invoked automatically. The generator shows the plan,
asks for explicit human approval, and then applies. This is enforced in the
generator's Terraform runner — not in Terraform itself.

### Principle 3 — Remote state is required

All projects use remote state. The backend configuration is rendered from
`infrastructure/terraform/templates/backend.tf.tpl` during generation.

Supported backends: Terraform Cloud / HCP Terraform, S3-compatible.

### Principle 4 — No secrets in Terraform state

Provider tokens and API keys flow into Terraform via environment variables or
Doppler-injected shell context. They are never written as Terraform variables
or stored in state.

### Principle 5 — Idempotent modules

All modules must be safe to `apply` repeatedly. Resources that already exist
must produce no-op on re-apply.

---

## 3. Module Specifications

### `modules/github`

**Creates:**
- Repository `<project_slug>` in `<github_org>`
- Branches: `develop`, `test`, `staging`, `main`
- Branch protection rules on all four branches
- GitHub Environments: `dev`, `test`, `stg`, `prod`
- Environment → branch mapping documented in README

**Variables:**
```hcl
variable "project_name"    { type = string }
variable "project_slug"    { type = string }
variable "github_org"      { type = string }
variable "default_branch"  { type = string; default = "develop" }
variable "visibility"      { type = string; default = "private" }
```

**Outputs:**
```hcl
output "repository_url"        { value = github_repository.this.html_url }
output "repository_full_name"  { value = github_repository.this.full_name }
```

---

### `modules/doppler`

**Creates:**
- Doppler project named `<project_slug>`
- Environments: `dev`, `test`, `stg`, `prod`
- Service tokens per environment (stored in Doppler itself)

**Variables:**
```hcl
variable "project_slug"    { type = string }
variable "environments"    {
  type    = list(string)
  default = ["dev", "test", "stg", "prod"]
}
```

**Outputs:**
```hcl
output "project_name"   { value = doppler_project.this.name }
output "environment_ids" { value = { for e in doppler_environment.envs: e.slug => e.id } }
```

---

### `modules/supabase`

**Creates:**
- One Supabase project per environment: `<project_slug>-dev`, `-test`, `-stg`, `-prod`
- Each project is in the KORAS Supabase organization
- Projects are physically isolated (separate PostgreSQL instances)

**Variables:**
```hcl
variable "project_slug"       { type = string }
variable "organization_id"    { type = string }
variable "db_password_secret" { type = string; sensitive = true }
variable "regions"            {
  type = map(string)
  default = {
    dev  = "us-east-1"
    test = "us-east-1"
    stg  = "us-east-1"
    prod = "us-east-1"
  }
}
```

**Outputs:**
```hcl
output "project_refs"    { value = { for k, v in supabase_project.envs: k => v.id } }
output "project_urls"    { value = { for k, v in supabase_project.envs: k => v.api_url } }
```

Sensitive outputs (db passwords, service_role keys) are stored in Doppler via
a post-apply provisioner, not in Terraform state.

---

### `modules/zitadel`

**Creates:**
- ZITADEL project named `<project_slug>` in each ZITADEL instance
  (DEV, TEST, STG, PROD instances are pre-existing platform resources)
- OIDC application configurations per profile

ZITADEL project names do NOT include an environment suffix.

**Variables:**
```hcl
variable "project_slug"    { type = string }
variable "profile"         { type = string }  # product | control-plane
variable "zitadel_instances" {
  type = map(object({
    domain      = string
    port        = number
    insecure    = bool
    token_path  = string  # path to service account JWT file
  }))
}
```

**Outputs:**
```hcl
output "project_ids"   { value = { for k, v in zitadel_project.instances: k => v.id } }
output "client_ids"    { value = { for k, v in zitadel_application_oidc.apps: k => v.client_id } }
```

---

### `modules/vercel`

**Creates:**
- One Vercel project per enabled application
- Environment variables linked to Doppler

**Variables:**
```hcl
variable "project_slug"   { type = string }
variable "team_id"        { type = string }
variable "applications"   { type = list(string) }  # e.g. ["web", "admin"]
variable "framework"      { type = string; default = "nextjs" }
variable "git_repository" { type = string }
```

**Application naming:**
```
<project_slug>-<app>   e.g. docoris-web, docoris-admin
```

**Outputs:**
```hcl
output "project_ids"   { value = { for a in vercel_project.apps: a.name => a.id } }
output "project_urls"  { value = { for a in vercel_project.apps: a.name => a.url } }
```

---

### `modules/fly`

**Creates:**
- One Fly application per enabled service per environment
- Named: `<project_slug>-<service>-<env>`

**Variables:**
```hcl
variable "project_slug"   { type = string }
variable "org_slug"       { type = string }
variable "services"       { type = list(string) }  # e.g. ["api", "worker"]
variable "environments"   { type = list(string); default = ["dev", "test", "stg", "prod"] }
variable "regions"        {
  type = map(string)
  default = {
    dev  = "iad"
    test = "iad"
    stg  = "iad"
    prod = "iad"
  }
}
```

**Outputs:**
```hcl
output "app_names"       { value = { for k, v in fly_app.apps: k => v.name } }
output "app_hostnames"   { value = { for k, v in fly_app.apps: k => v.hostname } }
```

---

### `modules/cloudflare`

**Creates:**
- DNS zone (or uses existing)
- A/CNAME records for all enabled applications and services
- WAF rules (OWASP ruleset, rate limiting)
- Page rules / cache configuration

**Variables:**
```hcl
variable "zone_id"        { type = string }
variable "primary_domain" { type = string }
variable "project_slug"   { type = string }
variable "dns_records"    {
  type = list(object({
    name  = string
    type  = string
    value = string
  }))
}
```

---

### `modules/project-bootstrap`

The orchestration module. Receives all generator context and calls each module.

**Variables:**
```hcl
variable "project_name"     { type = string }
variable "project_slug"     { type = string }
variable "profile"          {
  type = string
  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "Profile must be 'product' or 'control-plane'."
  }
}
variable "github_org"       { type = string }
variable "primary_domain"   { type = string }
variable "enabled_apps"     { type = list(string) }
variable "enabled_services" { type = list(string) }
variable "storage_provider" { type = string; default = "supabase" }
variable "ai_providers"     { type = list(string); default = [] }
variable "environment_configuration" {
  type = map(object({
    region      = string
    fly_region  = string
  }))
}
```

**Module calls (illustrative):**

```hcl
module "github" {
  source       = "../github"
  project_slug = var.project_slug
  github_org   = var.github_org
}

module "doppler" {
  source       = "../doppler"
  project_slug = var.project_slug
}

module "supabase" {
  source       = "../supabase"
  project_slug = var.project_slug
  organization_id = var.supabase_org_id
}

module "zitadel" {
  source       = "../zitadel"
  project_slug = var.project_slug
  profile      = var.profile
  zitadel_instances = local.zitadel_instances
}

module "vercel" {
  source       = "../vercel"
  project_slug = var.project_slug
  team_id      = var.vercel_team_id
  applications = local.vercel_applications[var.profile]
  git_repository = module.github.repository_full_name
}

module "fly" {
  source       = "../fly"
  project_slug = var.project_slug
  org_slug     = var.fly_org_slug
  services     = local.fly_services[var.profile]
}

module "cloudflare" {
  source         = "../cloudflare"
  zone_id        = var.cloudflare_zone_id
  primary_domain = var.primary_domain
  project_slug   = var.project_slug
  dns_records    = local.dns_records
}
```

Profile-specific local values:

```hcl
locals {
  vercel_applications = {
    product       = var.enabled_apps
    control-plane = ["admin", "portal"]
  }

  fly_services = {
    product       = var.enabled_services
    control-plane = ["api", "worker", "scheduler"]
  }
}
```

---

## 4. Environment Directory Structure

```
infrastructure/terraform/
├── modules/
│   ├── github/
│   ├── doppler/
│   ├── supabase/
│   ├── zitadel/
│   ├── vercel/
│   ├── fly/
│   ├── cloudflare/
│   └── project-bootstrap/
│
├── environments/
│   ├── dev.tfvars
│   ├── test.tfvars
│   ├── stg.tfvars
│   └── prod.tfvars
│
└── templates/
    ├── backend.tf.tpl          Remote state configuration
    ├── providers.tf.tpl        Provider versions
    └── main.tf.tpl             Root module entry point
```

Generated projects include a rendered version of these templates under
`infrastructure/terraform/`.

---

## 5. Terraform Variable Inputs from Generator

The generator assembles variables from the `GenerationContext` and passes them
to Terraform as a generated `terraform.tfvars.json` file (never committed):

```json
{
  "project_name": "Docoris",
  "project_slug": "docoris",
  "profile": "product",
  "github_org": "koras-technologies",
  "primary_domain": "docoris.app",
  "enabled_apps": ["web", "admin"],
  "enabled_services": ["api", "worker", "ai_gateway"],
  "storage_provider": "supabase",
  "ai_providers": ["openai", "anthropic"],
  "environment_configuration": {
    "dev":  { "region": "us-east-1", "fly_region": "iad" },
    "test": { "region": "us-east-1", "fly_region": "iad" },
    "stg":  { "region": "us-east-1", "fly_region": "iad" },
    "prod": { "region": "us-east-1", "fly_region": "iad" }
  }
}
```

This file is written to a temporary directory, used for the plan/apply, and
then deleted. It is never committed.

---

## 6. Governance

### State management

- Remote state backend is required for all projects
- State files are encrypted at rest
- State access is restricted to Terraform service accounts and authorized operators

### Drift detection

- Scheduled GitHub Actions workflow runs `terraform plan` weekly
- Any drift (plan is non-empty) creates a GitHub issue

### Module versioning

- All modules in this repository are versioned together with the starter
- Modules are referenced by relative path within a generated project
- If modules diverge (e.g., a product needs a hotfix), the change is applied
  in the starter and propagated via a documented upgrade guide

### Destruction protection

- All Supabase and ZITADEL resources have `lifecycle { prevent_destroy = true }`
  in production
- Fly production apps have `lifecycle { prevent_destroy = true }`
- GitHub repository has `lifecycle { prevent_destroy = true }` in production

---

## 7. Provider Versions (initial)

```hcl
terraform {
  required_version = ">= 1.6"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
    doppler = {
      source  = "DopplerHQ/doppler"
      version = "~> 1.0"
    }
    supabase = {
      source  = "supabase/supabase"
      version = "~> 1.0"
    }
    zitadel = {
      source  = "zitadel/zitadel"
      version = "~> 2.0"
    }
    vercel = {
      source  = "vercel/vercel"
      version = "~> 2.0"
    }
    fly = {
      source  = "fly-apps/fly"
      version = "~> 0.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}
```

Provider versions are reviewed and updated quarterly.
