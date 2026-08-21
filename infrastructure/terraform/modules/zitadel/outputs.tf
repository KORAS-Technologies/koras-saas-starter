output "project_id" {
  description = "ZITADEL project ID in this instance"
  value       = zitadel_project.this.id
}

output "client_id" {
  description = "OIDC client ID (non-secret)"
  value       = zitadel_application_oidc.web.client_id
  sensitive   = true
}

output "project_roles" {
  description = <<-EOT
    The role keys defined on this project.

    Exposed so a caller can assert the set is what the code expects. A role
    missing here is invisible until someone signs in and is refused.
  EOT
  value       = sort(keys(zitadel_project_role.roles))
}
