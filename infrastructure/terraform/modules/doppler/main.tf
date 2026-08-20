resource "doppler_project" "this" {
  name        = var.project_slug
  description = var.description
}

resource "doppler_environment" "envs" {
  for_each = toset(var.environments)

  project = doppler_project.this.name
  slug    = each.key
  name    = each.key
}
