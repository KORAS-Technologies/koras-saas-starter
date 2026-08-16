output "project_ids" {
  description = "Map of app name → Vercel project ID"
  value       = { for k, v in vercel_project.apps : k => v.id }
}

output "project_urls" {
  description = "Map of app name → Vercel project URL"
  value       = { for k, v in vercel_project.apps : k => "${v.name}.vercel.app" }
}
