output "project_ids" {
  description = "Map of app name → Vercel project ID"
  value       = { for k, v in vercel_project.apps : k => v.id }
}

output "project_urls" {
  description = "Map of app name → Vercel project URL"
  value       = { for k, v in vercel_project.apps : k => "${v.name}.vercel.app" }
}

output "domains" {
  description = <<-EOT
    Map of '<app>-<environment>' -> hostname attached to that project.

    Both sets, so the DNS records follow whatever was actually attached. A
    hostname with no record is unreachable; a record with no hostname points at
    Vercel for a domain it will not serve.
  EOT
  value = merge(
    { for key, d in vercel_project_domain.production : key => d.domain },
    { for key, d in vercel_project_domain.branches : key => d.domain },
  )
}

