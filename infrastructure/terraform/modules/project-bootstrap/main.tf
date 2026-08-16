locals {
  # Profile-specific Vercel applications
  vercel_apps = var.profile == "control-plane" ? ["admin", "portal"] : var.enabled_apps

  # Profile-specific Fly services
  fly_services = var.profile == "control-plane" ? ["api", "worker", "scheduler"] : var.enabled_services
}

module "github" {
  source = "../github"

  project_slug = var.project_slug
  github_org   = var.github_org
  description  = "${var.project_name} (${var.profile})"
}

module "doppler" {
  source = "../doppler"

  project_slug = var.project_slug
  description  = var.project_name
}

module "supabase" {
  source = "../supabase"

  project_slug    = var.project_slug
  organization_id = var.supabase_org_id
  environments    = var.supabase_environments
}

module "zitadel" {
  source = "../zitadel"

  project_slug              = var.project_slug
  profile                   = var.profile
  zitadel_instances         = var.zitadel_instances
  redirect_uris             = var.zitadel_redirect_uris
  post_logout_redirect_uris = var.zitadel_post_logout_redirect_uris
}

module "vercel" {
  source = "../vercel"

  project_slug   = var.project_slug
  team_id        = var.vercel_team_id
  applications   = local.vercel_apps
  git_repository = module.github.repository_full_name

  depends_on = [module.github]
}

module "fly" {
  source = "../fly"

  project_slug = var.project_slug
  org_slug     = var.fly_org_slug
  services     = local.fly_services
  regions      = var.fly_regions
}

module "cloudflare" {
  source = "../cloudflare"

  zone_id      = var.cloudflare_zone_id
  project_slug = var.project_slug

  # DNS records are assembled from Vercel and Fly outputs post-apply
  dns_records = []
}
