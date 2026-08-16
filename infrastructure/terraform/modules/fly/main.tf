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

  name    = "${var.project_slug}-${each.value.service}-${each.value.environment}"
  org     = var.org_slug

  lifecycle {
    prevent_destroy = true
  }
}
