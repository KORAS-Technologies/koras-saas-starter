# Creates one ZITADEL project inside a single ZITADEL instance.
#
# KORAS runs four isolated ZITADEL instances (dev/test/stg/prod). Terraform
# cannot select a provider dynamically, so this module is deliberately
# single-instance: the caller instantiates it once per instance and passes the
# matching aliased provider via a `providers` block.
#
# The project name is NOT suffixed with the environment — the instance itself
# represents the environment.

# The organization every resource in this module belongs to.
#
# `org_id` on `zitadel_project` is Optional and **not Computed**. Leaving it
# unset does not mean "the provider fills it in": it means the attribute plans
# as null, so `zitadel_project.this.org_id` is null for any project not already
# in state.
#
# That was survivable while nothing read it back. `zitadel_project_role`
# requires `org_id`, so reading it from the project made every *new* environment
# fail at plan with "The argument org_id is required, but no definition was
# found" -- while every existing one kept working, because its state already
# held the value the provider had written. A module that could only extend an
# estate it had already built.
#
# So the organization is discovered before anything is created. One active
# organization per instance is the estate's arrangement; `var.org_id` overrides
# it where that does not hold, and the precondition below names which case it is
# rather than failing on a null further down.
# Skipped entirely when `org_id` is given. Discovery is a fallback for an
# operator who has not said which organization to build in, and asking anyway is
# not free: these are live calls to an instance that may be asleep, restarting,
# or behind a gateway having a bad minute.
#
# It cost a plan. One environment's ZITADEL answered 503 with an HTML error page
# and `terraform plan` failed for the whole estate -- on a lookup whose only
# purpose was to put organization *names* into an error message that was not
# going to be shown, because the org was already known. Four instances meant
# four chances for an unrelated one to be down.
#
# So: name the org and nothing is queried. This is also why `zitadel_org_ids` is
# worth setting per environment even where discovery would succeed.
data "zitadel_orgs" "this" {
  count = var.org_id == null ? 1 : 0
  state = "ORG_STATE_ACTIVE"
}

# Names for what was discovered, so an ambiguous instance can be resolved from
# the error message rather than from a trip to the console. Two ids alone say
# nothing about which organization is which.
data "zitadel_org" "discovered" {
  for_each = toset(local.discovered_org_ids)
  id       = each.key
}

locals {
  discovered_org_ids = var.org_id == null ? data.zitadel_orgs.this[0].ids : []

  discovered_orgs = [
    for id in local.discovered_org_ids :
    "${id} (${data.zitadel_org.discovered[id].name})"
  ]

  org_id = var.org_id != null ? var.org_id : (
    length(local.discovered_org_ids) == 1 ? local.discovered_org_ids[0] : null
  )
}

resource "zitadel_project" "this" {
  name   = var.project_slug
  org_id = local.org_id

  project_role_assertion = true
  project_role_check     = true
  has_project_check      = true

  lifecycle {
    # Kept although org_id is now set explicitly. The provider writes the
    # resolved organization back into state, and a project cannot move between
    # organizations without being recreated -- so a diff here could only ever
    # propose destroying an environment that is serving traffic.
    ignore_changes = [org_id]

    precondition {
      condition     = local.org_id != null
      error_message = "Could not determine the ZITADEL organization: ${length(local.discovered_org_ids)} active organizations were found and this module needs exactly one. Set `org_id` on the module to name it. Found: ${join(", ", local.discovered_orgs)}"
    }
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
  # Customer roles. Every profile needs them: a product serves customers, and
  # so does the Control Plane -- its portal is a customer surface with its own
  # middleware and its own API.
  organization_roles = [
    "organization_owner",
    "organization_admin",
    "billing_admin",
    "security_admin",
    "member",
  ]

  # Staff roles, for the Control Plane only. No product has platform staff.
  platform_roles = [
    "platform_super_admin",
    "platform_admin",
    "platform_support",
    "platform_billing",
    "platform_readonly",
  ]

  # The Control Plane needs both, and defining only the staff half made its
  # portal unreachable at the identity layer: project_role_check below refuses
  # a token to anyone holding no role on the project, and no customer could
  # hold one. A customer signed in and ZITADEL answered ProjectRequired before
  # the application saw anything.
  project_roles = var.profile == "control-plane" ? concat(
    local.platform_roles,
    local.organization_roles,
  ) : local.organization_roles
}

resource "zitadel_project_role" "roles" {
  for_each = toset(local.project_roles)

  project_id = zitadel_project.this.id
  # Required here, unlike on the project and the application where the provider
  # resolves it from the service user. Taken from the project so both always
  # agree: a role created in a different organization than its project is
  # accepted by the API and never appears in anyone's token.
  org_id       = local.org_id
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

  # Put the roles and the profile into the ID token.
  #
  # `project_role_assertion` on the project above is not enough: it governs
  # the access token, and the applications read the ID token. Without these
  # two, a user with a platform role signs in successfully and arrives
  # carrying no role at all -- so the middleware answers `This application is
  # for KORAS staff`, which is the correct refusal for a token that genuinely
  # says nothing, and completely misleading about why.
  #
  # The userinfo assertion is here for the same reason: email and name are
  # read from the same token, and a session with no name renders a signed-in
  # user as anonymous.
  id_token_role_assertion     = true
  id_token_userinfo_assertion = true

  # Relaxed OIDC checks are acceptable in dev only.
  dev_mode = var.environment == "dev"

  # See the note above zitadel_project.
  lifecycle {
    ignore_changes = [org_id]
  }
}

# ── Who can actually sign in ────────────────────────────────────────────────
#
# Roles were defined above and granted to nobody, so a freshly provisioned
# estate had no one who could reach it: `project_role_check` refuses a token to
# any user holding no role on the project, and the refusal surfaces as
# ProjectRequired before the application is involved. The comment on
# `project_roles` records the same failure reaching the Control Plane's portal.

data "zitadel_human_users" "granted" {
  for_each = var.role_grants

  org_id       = local.org_id
  email        = each.key
  email_method = "TEXT_QUERY_METHOD_EQUALS_IGNORE_CASE"
}

resource "zitadel_user_grant" "roles" {
  for_each = var.role_grants

  org_id     = local.org_id
  project_id = zitadel_project.this.id
  user_id    = one(data.zitadel_human_users.granted[each.key].user_ids)
  role_keys  = each.value

  lifecycle {
    precondition {
      # `one()` returns null for an empty set, and a null user_id is accepted
      # by the API as a grant that matches nobody -- so the apply would succeed
      # and the person still could not sign in. Named here instead, while
      # someone is looking at the plan.
      condition = length(data.zitadel_human_users.granted[each.key].user_ids) == 1
      error_message = format(
        "%s matches %d users in this instance, not 1. A grant needs exactly one: create the user in %s first, or disambiguate the address.",
        each.key,
        length(data.zitadel_human_users.granted[each.key].user_ids),
        var.environment,
      )
    }

    precondition {
      # A role key the project does not define is accepted by ZITADEL and never
      # appears in anyone's token -- the same shape as the org_id note above.
      condition = length(setsubtract(each.value, local.project_roles)) == 0
      error_message = format(
        "%s would be granted roles this project does not define: %s. Defined: %s.",
        each.key,
        join(", ", setsubtract(each.value, local.project_roles)),
        join(", ", local.project_roles),
      )
    }
  }
}
