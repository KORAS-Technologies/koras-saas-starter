# Creates one ZITADEL project per instance (dev/test/stg/prod).
# Each instance is a separate, pre-existing ZITADEL installation.
# Project names are NOT suffixed with env — the instance represents the environment.

resource "zitadel_project" "instances" {
  for_each = var.zitadel_instances

  name = var.project_slug

  # Provider alias selects the correct ZITADEL instance per environment
  provider = zitadel[each.key]

  project_role_assertion  = true
  project_role_check      = true
  has_project_check       = true
}

resource "zitadel_application_oidc" "apps" {
  for_each = var.zitadel_instances

  name       = "${var.project_slug}-web"
  project_id = zitadel_project.instances[each.key].id

  provider = zitadel[each.key]

  redirect_uris           = var.redirect_uris
  post_logout_redirect_uris = var.post_logout_redirect_uris
  response_types          = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types             = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                = "OIDC_APP_TYPE_WEB"
  auth_method_type        = "OIDC_AUTH_METHOD_TYPE_BASIC"
  version                 = "OIDC_VERSION_1_0"
  dev_mode                = each.key == "dev"
  access_token_type       = "OIDC_TOKEN_TYPE_JWT"
}
