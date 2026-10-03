output "app_names" {
  description = "Map of 'service-env' → Fly app name"
  value       = { for k, v in fly_app.apps : k => v.name }
}

output "app_hostnames" {
  description = <<-EOT
    Map of 'service-env' to Fly app hostname, for public services only.

    A service declared `network: private` is reachable over Fly's private
    network and has no public URL, so it is not listed: an output naming
    <app>.fly.dev for it would be a URL that does not answer, and every consumer
    of this map builds URLs from it.
  EOT
  value = {
    for k, v in fly_app.apps : k => "${v.name}.fly.dev"
    if !contains(module.eligibility.private_services, local.app_matrix[k].service)
  }
}
