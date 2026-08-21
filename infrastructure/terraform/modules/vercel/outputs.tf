output "project_ids" {
  description = <<-EOT
    Map of '<app>-<environment>' -> Vercel project id.

    Keyed by environment because there is one project per environment. The
    deploy pipeline reads the id for the environment it is releasing, which is
    what keeps a dev release from being pushed into the production project.
  EOT
  value       = { for key, p in vercel_project.apps : key => p.id }
}

output "project_urls" {
  description = "Map of '<app>-<environment>' -> the project's generated Vercel URL."
  value       = { for k, v in vercel_project.apps : k => "${v.name}.vercel.app" }
}

output "domains" {
  description = "Map of '<app>-<environment>' -> the hostname that project answers on."
  value       = { for key, d in vercel_project_domain.primary : key => d.domain }
}
