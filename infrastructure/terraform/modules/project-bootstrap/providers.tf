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
    # One aliased configuration per ZITADEL instance — the caller must supply
    # all four (see the generated infrastructure/terraform/providers.tf).
    zitadel = {
      source                = "zitadel/zitadel"
      version               = "~> 2.0"
      configuration_aliases = [zitadel.dev, zitadel.test, zitadel.stg, zitadel.prod]
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
