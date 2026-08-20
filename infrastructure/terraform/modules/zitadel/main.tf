# Creates one ZITADEL project inside a single ZITADEL instance.
#
# KORAS runs four isolated ZITADEL instances (dev/test/stg/prod). Terraform
# cannot select a provider dynamically, so this module is deliberately
# single-instance: the caller instantiates it once per instance and passes the
# matching aliased provider via a `providers` block.
#
# The project name is NOT suffixed with the environment — the instance itself
# represents the environment.

# `org_id` is deliberately not set, and deliberately ignored.
#
# The provider resolves the organization from the authenticated service user
# and writes the result into state, but the attribute is Optional and ForceNew
# rather than Computed. Terraform therefore reads the next plan as
# `org_id = "386573..." -> null # forces replacement` and proposes to destroy
# and recreate every project and OIDC application — rotating client_id and
# client_secret for an environment that is already serving traffic.
#
# Ignoring it is safe: each ZITADEL instance holds exactly one KORAS
# organization, and the service user's credential is what selects it. A project
# cannot move between organizations without being recreated anyway, so there is
# no real drift for this to hide.
resource "zitadel_project" "this" {
  name = var.project_slug

  project_role_assertion = true
  project_role_check     = true
  has_project_check      = true

  lifecycle {
    ignore_changes = [org_id]
  }
}

resource "zitadel_application_oidc" "web" {
  name       = "${var.project_slug}-web"
  project_id = zitadel_project.this.id

  redirect_uris             = var.redirect_uris
  post_logout_redirect_uris = var.post_logout_redirect_uris
  response_types            = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types               = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                  = "OIDC_APP_TYPE_WEB"
  auth_method_type          = "OIDC_AUTH_METHOD_TYPE_BASIC"
  version                   = "OIDC_VERSION_1_0"
  access_token_type         = "OIDC_TOKEN_TYPE_JWT"

  # Relaxed OIDC checks are acceptable in dev only.
  dev_mode = var.environment == "dev"

  # See the note above zitadel_project.
  lifecycle {
    ignore_changes = [org_id]
  }
}
