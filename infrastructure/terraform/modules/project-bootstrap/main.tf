locals {
  # enabled_apps and enabled_services come from the generator, which resolves
  # them from the profile manifest and the user's component selections. Do not
  # re-derive them from the profile here — that would duplicate the manifest.
  vercel_apps  = var.enabled_apps
  fly_services = var.enabled_services
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

# One module instance per ZITADEL instance. Terraform cannot index providers,
# so each environment is wired explicitly to its aliased provider.

module "zitadel_dev" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.dev }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "dev"
  redirect_uris             = var.zitadel_redirect_uris
  post_logout_redirect_uris = var.zitadel_post_logout_redirect_uris
}

module "zitadel_test" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.test }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "test"
  redirect_uris             = var.zitadel_redirect_uris
  post_logout_redirect_uris = var.zitadel_post_logout_redirect_uris
}

module "zitadel_stg" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.stg }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "stg"
  redirect_uris             = var.zitadel_redirect_uris
  post_logout_redirect_uris = var.zitadel_post_logout_redirect_uris
}

module "zitadel_prod" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.prod }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "prod"
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
