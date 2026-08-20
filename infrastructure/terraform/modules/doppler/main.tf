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

# The queue credential for each environment.
#
# Creating an environment creates a root config of the same name, which is what
# `doppler run --config <env>` resolves, so the config name is the slug.
#
# `for_each` cannot take a sensitive collection, and the URLs embed a password.
# Only the keys are unwrapped -- environment names are not secret, and this is
# the same idiom project-bootstrap already uses for supabase_environments.
resource "doppler_secret" "queue_url" {
  for_each = toset(nonsensitive(keys(var.queue_urls)))

  project = doppler_project.this.name
  config  = doppler_environment.envs[each.key].slug
  name    = "REDIS_URL"
  value   = var.queue_urls[each.key]
}
