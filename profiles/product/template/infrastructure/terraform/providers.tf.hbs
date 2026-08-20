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
      version = "~> 0.0.9"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    upstash = {
      source  = "upstash/upstash"
      version = "~> 1.5"
    }
  }
}

# All provider tokens are injected via environment variables — never in code.
# GitHub:     GITHUB_TOKEN
# Doppler:    DOPPLER_TOKEN
# Supabase:   SUPABASE_ACCESS_TOKEN
# ZITADEL:    Per-instance credentials in TF_VAR_zitadel_instances
# Vercel:     VERCEL_API_TOKEN
# Fly:        FLY_API_TOKEN
# Cloudflare: CLOUDFLARE_API_TOKEN
# Upstash:    TF_VAR_upstash_email and TF_VAR_upstash_api_key

# Upstash has no environment-variable fallback: `email` and `api_key` are
# required provider arguments, so omitting this block fails the plan with
# "requires explicit configuration" before any resource is evaluated.
provider "upstash" {
  email   = var.upstash_email
  api_key = var.upstash_api_key
}

provider "github" {
  owner = var.github_org
}

provider "vercel" {
  team = var.vercel_team_id
}

# KORAS runs four isolated ZITADEL instances. Terraform cannot select a
# provider dynamically, so each instance gets an explicit aliased
# configuration, wired into project-bootstrap by alias.
# The ZITADEL provider has no environment-variable fallback, so each alias
# carries its own service-user credential from var.zitadel_instances.

provider "zitadel" {
  alias            = "dev"
  domain           = var.zitadel_instances["dev"].domain
  port             = var.zitadel_instances["dev"].port
  insecure         = var.zitadel_instances["dev"].insecure
  jwt_profile_json = var.zitadel_instances["dev"].jwt_profile_json
}

provider "zitadel" {
  alias            = "test"
  domain           = var.zitadel_instances["test"].domain
  port             = var.zitadel_instances["test"].port
  insecure         = var.zitadel_instances["test"].insecure
  jwt_profile_json = var.zitadel_instances["test"].jwt_profile_json
}

provider "zitadel" {
  alias            = "stg"
  domain           = var.zitadel_instances["stg"].domain
  port             = var.zitadel_instances["stg"].port
  insecure         = var.zitadel_instances["stg"].insecure
  jwt_profile_json = var.zitadel_instances["stg"].jwt_profile_json
}

provider "zitadel" {
  alias            = "prod"
  domain           = var.zitadel_instances["prod"].domain
  port             = var.zitadel_instances["prod"].port
  insecure         = var.zitadel_instances["prod"].insecure
  jwt_profile_json = var.zitadel_instances["prod"].jwt_profile_json
}
