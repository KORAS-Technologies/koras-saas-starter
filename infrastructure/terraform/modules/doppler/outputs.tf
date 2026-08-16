output "project_name" {
  value = doppler_project.this.name
}

output "environment_slugs" {
  value = { for k, v in doppler_environment.envs : k => v.slug }
}
