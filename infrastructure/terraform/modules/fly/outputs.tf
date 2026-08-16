output "app_names" {
  description = "Map of 'service-env' → Fly app name"
  value       = { for k, v in fly_app.apps : k => v.name }
}

output "app_hostnames" {
  description = "Map of 'service-env' → Fly app hostname"
  value       = { for k, v in fly_app.apps : k => "${v.name}.fly.dev" }
}
