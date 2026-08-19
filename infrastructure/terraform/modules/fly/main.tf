locals {
  # Cartesian product: service × environment → fly app
  app_matrix = {
    for pair in setproduct(var.services, var.environments) :
    "${pair[0]}-${pair[1]}" => {
      service     = pair[0]
      environment = pair[1]
      region      = lookup(var.regions, pair[1], var.regions["prod"])
    }
  }
}

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
