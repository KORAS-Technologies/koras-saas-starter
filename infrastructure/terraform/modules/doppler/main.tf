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

# ── Deploy credentials ──────────────────────────────────────────────────────
#
# One read-only token per environment, for the deploy pipeline to read that
# environment's settings with.
#
# Scoped to this project and this config, so a token that leaks reads the
# environment it belongs to and nothing else. The estate-wide token the
# generator provisions with would have been simpler and is the reason to do
# this: one credential that reads every environment of every project is the
# blast radius nobody chooses on purpose.
#
# `read` access, not `read/write`. The pipeline consumes settings; the only
# thing that writes them is `make doppler-bootstrap`, run by a person.
resource "doppler_service_token" "deploy" {
  for_each = doppler_environment.envs

  project = doppler_project.this.name
  config  = each.value.slug
  name    = "github-actions-deploy"
  access  = "read"
}
