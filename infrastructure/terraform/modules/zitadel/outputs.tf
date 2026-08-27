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

output "org_id" {
  description = <<-EOT
    The organization the project was created in.

    Exported for teardown, which needs it and cannot infer it. ZITADEL projects
    are org-scoped and the management API acts in the organization of whoever
    holds the token unless `x-zitadel-orgid` says otherwise. A delete aimed at
    the wrong org does not fail -- it returns 404, which teardown reads as
    "already gone", so a project would survive a run that reported success.

    That is not hypothetical here: this module discovers the org when `org_id`
    is unset, and an instance with more than one active organization is exactly
    when the discovered one and the token's own can differ.
  EOT
  value       = local.org_id
}
