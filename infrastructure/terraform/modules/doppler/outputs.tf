output "project_name" {
  value = doppler_project.this.name
}

output "environment_slugs" {
  value = { for k, v in doppler_environment.envs : k => v.slug }
}

output "deploy_tokens" {
  description = "Map of environment -> a read-only service token for that config."
  sensitive   = true
  value       = { for k, v in doppler_service_token.deploy : k => v.key }
}
