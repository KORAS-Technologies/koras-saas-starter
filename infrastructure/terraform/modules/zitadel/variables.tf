variable "project_slug" {
  type        = string
  description = "ZITADEL project name (no env suffix — instance IS the environment)"
}

variable "environment" {
  type        = string
  description = "Environment this ZITADEL instance represents"

  validation {
    condition     = contains(["dev", "test", "stg", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, stg, prod."
  }
}

variable "profile" {
  type        = string
  description = "Generator profile: product or control-plane"

  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "profile must be 'product' or 'control-plane'."
  }
}

variable "redirect_uris" {
  type        = list(string)
  description = "Allowed OIDC redirect URIs"
  default     = []
}

variable "post_logout_redirect_uris" {
  type        = list(string)
  description = "Allowed post-logout redirect URIs"
  default     = []
}

variable "role_grants" {
  type    = map(list(string))
  default = {}

  description = <<-EOT
    Email address -> the roles that person holds on this project.

    `project_role_check` and `has_project_check` are both on, so a user holding
    no role on the project cannot obtain a token at all -- ZITADEL answers
    ProjectRequired before the application sees anything. Roles were defined
    here and granted nowhere, which meant a freshly provisioned estate had
    nobody who could sign in to it.

    Keyed by email rather than user id. An id is opaque and differs per
    instance, so the same person needs four of them and a reviewer cannot tell
    who is being granted what. The lookup resolves the id per environment.

    Declarative, and that cuts both ways: removing someone here revokes their
    access on the next apply, which is the point, and is worth knowing before
    editing it in a hurry.

    Bootstrap access, not an access-management system. Grant the few people who
    must be able to reach a new environment; everything after that belongs in
    the application's own administration.
  EOT
}

variable "org_id" {
  description = <<-DESC
    The ZITADEL organization to create everything in.

    Normally left null: the module finds the single active organization in the
    instance. Set it where an instance holds more than one -- a ZITADEL Cloud
    instance keeps its own default organization alongside any you create, and
    the module cannot tell which one is yours.
  DESC
  type        = string
  default     = null
}
