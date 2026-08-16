output "project_ids" {
  description = "Map of env → ZITADEL project ID"
  value       = { for k, v in zitadel_project.instances : k => v.id }
}

output "client_ids" {
  description = "Map of env → OIDC client ID (non-secret)"
  value       = { for k, v in zitadel_application_oidc.apps : k => v.client_id }
}
