# Creates one ZITADEL project inside a single ZITADEL instance.
#
# KORAS runs four isolated ZITADEL instances (dev/test/stg/prod). Terraform
# cannot select a provider dynamically, so this module is deliberately
# single-instance: the caller instantiates it once per instance and passes the
# matching aliased provider via a `providers` block.
#
# The project name is NOT suffixed with the environment — the instance itself
# represents the environment.

resource "zitadel_project" "this" {
  name = var.project_slug

  project_role_assertion = true
  project_role_check     = true
  has_project_check      = true
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
}
