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
  }
}

# All provider tokens are injected via environment variables — never in code.
# GitHub:     GITHUB_TOKEN
# Doppler:    DOPPLER_TOKEN
# Supabase:   SUPABASE_ACCESS_TOKEN
# ZITADEL:    Configured per-instance in zitadel_instances variable
# Vercel:     VERCEL_API_TOKEN
# Fly:        FLY_API_TOKEN
# Cloudflare: CLOUDFLARE_API_TOKEN

provider "github" {
  owner = var.github_org
}

provider "vercel" {
  team = var.vercel_team_id
}

# KORAS runs four isolated ZITADEL instances. Terraform cannot select a
# provider dynamically, so each instance gets an explicit aliased
# configuration, wired into project-bootstrap by alias.
# Credentials come from the environment (ZITADEL_TOKEN / jwt profile file).

provider "zitadel" {
  alias    = "dev"
  domain   = var.zitadel_instances["dev"].domain
  port     = var.zitadel_instances["dev"].port
  insecure = var.zitadel_instances["dev"].insecure
}

provider "zitadel" {
  alias    = "test"
  domain   = var.zitadel_instances["test"].domain
  port     = var.zitadel_instances["test"].port
  insecure = var.zitadel_instances["test"].insecure
}

provider "zitadel" {
  alias    = "stg"
  domain   = var.zitadel_instances["stg"].domain
  port     = var.zitadel_instances["stg"].port
  insecure = var.zitadel_instances["stg"].insecure
}

provider "zitadel" {
  alias    = "prod"
  domain   = var.zitadel_instances["prod"].domain
  port     = var.zitadel_instances["prod"].port
  insecure = var.zitadel_instances["prod"].insecure
}
