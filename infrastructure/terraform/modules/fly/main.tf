# Which service-environment pairs exist is decided by the services' own
# descriptors (services/<service>/service.yaml), through the same rules the
# deploy workflow applies to decide what to deploy. A service with no
# descriptor gets every environment, exactly as before descriptors existed.
module "eligibility" {
  source = "./eligibility"

  services     = var.services
  environments = var.environments
  services_dir = var.services_dir
}

locals {
  app_matrix = {
    for key, pair in module.eligibility.matrix :
    key => {
      service     = pair.service
      environment = pair.environment
      region      = lookup(var.regions, pair.environment, var.regions["prod"])
    }
  }
}

# There is deliberately no fly_ip resource, here or anywhere in this module. An
# app gets a public address only when something allocates one -- flyctl does
# it on deploy when fly.toml has an [http_service] or [[services]] -- so a
# service declared `network: private` stays private by having neither.
resource "fly_app" "apps" {
  for_each = local.app_matrix

  # Same constraint as Vercel: `ai_gateway` is a valid component key but not a
  # valid Fly app name. Latent until that optional service is enabled.
  name = "${var.project_slug}-${replace(each.value.service, "_", "-")}-${each.value.environment}"
  org  = var.org_slug

  lifecycle {
    prevent_destroy = true
  }
}
