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

# The roles a token can carry.
#
# Without these, nothing else works. `project_role_assertion` above puts the
# caller's roles into the `urn:zitadel:iam:org:project:roles` claim, and the
# applications read their entire authorisation model from it -- but a project
# with no roles defined can grant none, so every token arrives with an empty
# claim. The result is not an error anyone can diagnose: sign-in succeeds, the
# session is valid, and the middleware refuses every page because the caller
# has no role. A perfectly deployed platform that nobody can log into.
#
# The names are not free text. They are matched exactly against the enums the
# code parses (`PlatformRole`, `OrganizationRole`), and an unrecognised name
# grants nothing rather than failing loudly -- which is the right behaviour for
# a typo in a claim, and the reason a typo here would be so quiet.
locals {
  # Staff roles for the Control Plane; customer roles for a product. A product
  # has no platform roles at all: staff authority lives in one place, and
  # issuing `platform_admin` from a product project would create a second.
  project_roles = var.profile == "control-plane" ? [
    "platform_super_admin",
    "platform_admin",
    "platform_support",
    "platform_billing",
    "platform_readonly",
    ] : [
    "organization_owner",
    "organization_admin",
    "billing_admin",
    "security_admin",
    "member",
  ]
}

resource "zitadel_project_role" "roles" {
  for_each = toset(local.project_roles)

  project_id = zitadel_project.this.id
  # Required here, unlike on the project and the application where the provider
  # resolves it from the service user. Taken from the project so both always
  # agree: a role created in a different organization than its project is
  # accepted by the API and never appears in anyone's token.
  org_id       = zitadel_project.this.org_id
  role_key     = each.key
  display_name = each.key

  # No group. ZITADEL groups are a display concern, and setting one changes the
  # role key format in some provider versions -- which would silently stop the
  # claim matching the enum.
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
