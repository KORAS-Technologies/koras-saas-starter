locals {
  # enabled_apps and enabled_services come from the generator, which resolves
  # them from the profile manifest and the user's component selections. Do not
  # re-derive them from the profile here — that would duplicate the manifest.
  vercel_apps  = var.enabled_apps
  fly_services = var.enabled_services
}

module "github" {
  source = "../github"

  project_slug       = var.project_slug
  github_org         = var.github_org
  description        = "${var.project_name} (${var.profile})"
  visibility         = var.repository_visibility
  required_approvals = var.required_approvals

  # The deploy pipeline declares five secrets `required: true`, and a
  # workflow_call with an unsatisfied one fails before any step runs. Nothing
  # set them, so every generated project had a pipeline that could not start.
  #
  # Split by what each value is rather than by habit. The Doppler token differs
  # per environment and is scoped to one config, so it is an environment
  # secret. The Fly and Vercel credentials are identical in all four, so
  # scoping them per environment would be four copies of one secret and four
  # places to rotate it.
  doppler_deploy_tokens = module.doppler.deploy_tokens
  estate_deploy_secrets = {
    FLY_API_TOKEN = var.fly_api_token
    VERCEL_TOKEN  = var.vercel_token
    # The team, not a credential. GitHub is simply where the pipeline reads it.
    VERCEL_ORG_ID = var.vercel_team_id
  }
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

locals {
  # Each environment's OIDC app accepts only its own callback URLs.
  #
  # `zitadel_redirect_uris` was one flat list handed to all four instances,
  # and it defaulted to empty and was never set -- so every OIDC app in every
  # generated estate had no redirect URI at all and ZITADEL refused every
  # sign-in with `The requested redirect_uri is missing in the client
  # configuration`. Sign-in could not work anywhere. Same shape as the
  # project roles that were never created: infrastructure that applies
  # cleanly and cannot do the one thing it exists for.
  #
  # Setting that list would have fixed the symptom and broken isolation: one
  # list means dev's ZITADEL accepts prod's callback, so a code issued by dev
  # can be redirected into the production application. Every other external
  # adapter here takes an explicit environment; this one would have been the
  # exception.
  #
  # Derived from the hostnames Vercel actually attaches, so the two cannot
  # disagree -- a domain added there is accepted here and nowhere else.
  auth_environments = keys(var.environment_branches)

  redirect_uris = {
    for environment in local.auth_environments : environment => concat(
      [
        for key, host in module.vercel.domains :
        "https://${host}/api/auth/callback"
        if endswith(key, "-${environment}")
      ],
      var.zitadel_redirect_uris,
    )
  }

  post_logout_redirect_uris = {
    for environment in local.auth_environments : environment => concat(
      [
        for key, host in module.vercel.domains :
        "https://${host}/"
        if endswith(key, "-${environment}")
      ],
      var.zitadel_post_logout_redirect_uris,
    )
  }
}

# One module instance per ZITADEL instance. Terraform cannot index providers,
# so each environment is wired explicitly to its aliased provider.

module "zitadel_dev" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.dev }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "dev"
  redirect_uris             = local.redirect_uris["dev"]
  post_logout_redirect_uris = local.post_logout_redirect_uris["dev"]
  role_grants               = lookup(var.zitadel_role_grants, "dev", {})
  # Absent unless this instance holds more than one organization. See the
  # zitadel module: it discovers the single active one and refuses to guess.
  org_id = lookup(var.zitadel_org_ids, "dev", null)

  # No depends_on. `local.redirect_uris` already reads `module.vercel.domains`,
  # so the dependency is expressed by the value and applies to exactly the
  # resources that consume it.
  #
  # An explicit module-level depends_on applies to every resource in the module
  # instead, including `zitadel_project_role`, which reads no redirect URI. This
  # module carried one and its three siblings did not, so when the Vercel module
  # was refusing an unrelated destroy, test, stg and prod could still be given
  # their roles and dev could not -- the one environment in daily use, failing
  # invisibly, because the plan simply omitted them. See R-029.
}

module "zitadel_test" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.test }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "test"
  redirect_uris             = local.redirect_uris["test"]
  post_logout_redirect_uris = local.post_logout_redirect_uris["test"]
  role_grants               = lookup(var.zitadel_role_grants, "test", {})
  # Absent unless this instance holds more than one organization. See the
  # zitadel module: it discovers the single active one and refuses to guess.
  org_id = lookup(var.zitadel_org_ids, "test", null)
}

module "zitadel_stg" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.stg }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "stg"
  redirect_uris             = local.redirect_uris["stg"]
  post_logout_redirect_uris = local.post_logout_redirect_uris["stg"]
  role_grants               = lookup(var.zitadel_role_grants, "stg", {})
  # Absent unless this instance holds more than one organization. See the
  # zitadel module: it discovers the single active one and refuses to guess.
  org_id = lookup(var.zitadel_org_ids, "stg", null)
}

module "zitadel_prod" {
  source    = "../zitadel"
  providers = { zitadel = zitadel.prod }

  project_slug              = var.project_slug
  profile                   = var.profile
  environment               = "prod"
  redirect_uris             = local.redirect_uris["prod"]
  post_logout_redirect_uris = local.post_logout_redirect_uris["prod"]
  role_grants               = lookup(var.zitadel_role_grants, "prod", {})
  # Absent unless this instance holds more than one organization. See the
  # zitadel module: it discovers the single active one and refuses to guess.
  org_id = lookup(var.zitadel_org_ids, "prod", null)
}

module "vercel" {
  source = "../vercel"

  primary_domain = var.primary_domain

  # Shared with the OIDC redirect URIs above, so a hostname Vercel attaches
  # is one ZITADEL accepts, in that environment and no other.
  environment_branches = var.environment_branches

  project_slug            = var.project_slug
  team_id                 = var.vercel_team_id
  applications            = local.vercel_apps
  application_source_dirs = var.application_source_dirs
  git_repository          = module.github.repository_full_name

  depends_on = [module.github]
}

# The deploy pipeline resolves each application's Vercel project from a secret
# named after the application -- apps/web looks for VERCEL_WEB_PROJECT_ID. There
# is one Vercel project per application per environment, so these are
# environment secrets rather than repository ones: a dev release reads the dev
# project's id and has no way to name the production project.
#
# Declared here rather than inside the github module because the Vercel projects
# are created from the repository, so github runs first and cannot see their ids
# without a dependency cycle.
resource "github_actions_environment_secret" "vercel_project_ids" {
  for_each = {
    for pair in setproduct(local.vercel_apps, keys(var.environment_branches)) :
    "${pair[0]}-${pair[1]}" => { app = pair[0], environment = pair[1] }
  }

  repository  = module.github.repository_name
  environment = each.value.environment
  # Named from the source directory, not the component key. The pipeline
  # derives this name by listing apps/ -- apps/admin looks for
  # VERCEL_ADMIN_PROJECT_ID -- while the component key for that same
  # application is `platform_admin`. Keying off the component wrote
  # VERCEL_PLATFORM_ADMIN_PROJECT_ID, a secret nothing reads, and left the
  # deploy depending on a hand-set one that Terraform did not know about.
  secret_name = "VERCEL_${upper(replace(basename(lookup(var.application_source_dirs, each.value.app, each.value.app)), "-", "_"))}_PROJECT_ID"
  value       = module.vercel.project_ids[each.key]

  # The environments are created inside the github module, and a project id is
  # only known once Vercel has made the project.
  depends_on = [module.github, module.vercel]
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
