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

  # No secret values are passed in, deliberately. `doppler_secret` resources
  # would put every credential into Terraform state permanently, making state
  # the authority and Doppler a replica -- backwards, and the shape that let a
  # generated project publish its estate in a committed plan file.
  #
  # Terraform creates the project and its environments and stops there. Values
  # arrive through local/scripts/doppler-bootstrap.sh, which reads the outputs
  # below (redis_urls among them) and prompts for what cannot be derived.
}

module "supabase" {
  source = "../supabase"

  project_slug    = var.project_slug
  organization_id = var.supabase_org_id
  environments    = var.supabase_environments
  default_region  = var.supabase_region
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

  primary_domain = var.primary_domain

  project_slug            = var.project_slug
  team_id                 = var.vercel_team_id
  applications            = local.vercel_apps
  application_source_dirs = var.application_source_dirs
  git_repository          = module.github.repository_full_name

  depends_on = [module.github]
}

module "upstash" {
  source = "../upstash"

  project_slug = var.project_slug
  environments = toset(nonsensitive(keys(var.supabase_environments)))
  region       = var.upstash_region
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
  enable_waf   = var.enable_waf

  # Assembled from the Vercel domains rather than left empty. "Post-apply" was
  # the plan and nothing ever did it, so every hostname the applications were
  # configured to answer on resolved to nothing -- including the OAuth redirect
  # URI, which meant sign-in completed and then landed on NXDOMAIN.
  #
  # CNAME to Vercel, not an A record: Vercel's edge addresses change, and a
  # pinned address is an outage nobody causes and nobody expects.
  #
  # The API is deliberately absent. It answers on its Fly hostname, which is
  # what the settings point at, so a DNS record here would be a second name for
  # something already reachable and a second thing to keep correct.
  dns_records = [
    for key, domain in module.vercel.domains : {
      name  = domain
      type  = "CNAME"
      value = "cname.vercel-dns.com"
      # Unproxied. Vercel terminates TLS for the domain itself, and proxying
      # through Cloudflare puts a second certificate in front of one that is
      # already valid -- which fails until Vercel has issued, and then serves
      # the wrong chain.
      proxied = false
    }
  ]
}
