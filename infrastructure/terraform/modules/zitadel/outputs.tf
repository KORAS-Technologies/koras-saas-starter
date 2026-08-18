output "project_id" {
  description = "ZITADEL project ID in this instance"
  value       = zitadel_project.this.id
}

output "client_id" {
  description = "OIDC client ID (non-secret)"
  value       = zitadel_application_oidc.web.client_id
  sensitive   = true
}
