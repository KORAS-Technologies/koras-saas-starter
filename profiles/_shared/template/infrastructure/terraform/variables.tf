# Profile identity — set by create-koras-app in environments/<env>.tfvars.
# Terraform modules branch on this only where infrastructure genuinely differs.
variable "profile" {
  type = string
  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "profile must be one of: product, control-plane."
  }
}

variable "project_name" {
  type = string
}

variable "project_slug" {
  type = string
}

variable "github_org" {
  type = string
}

variable "primary_domain" {
  type = string
}

variable "enabled_apps" {
  type    = list(string)
  default = []
}

variable "application_source_dirs" {
  type        = map(string)
  description = "Component key to source directory, written by the generator."
  default     = {}
}

variable "enabled_services" {
  type    = list(string)
  default = []
}

variable "supabase_org_id" {
  type = string
}

variable "supabase_region" {
  type    = string
  default = "us-east-1"
}

variable "supabase_environments" {
  type      = map(object({ db_password = string, region = optional(string) }))
  sensitive = true
}

variable "vercel_team_id" {
  type = string
}

variable "fly_org_slug" {
  type = string
}

variable "fly_regions" {
  type = map(string)
}

variable "cloudflare_zone_id" {
  type = string
}

# Upstash account credentials. Both are required provider arguments, so the
# plan cannot even be produced without them. Supplied via TF_VAR_upstash_email
# and TF_VAR_upstash_api_key from Doppler — never in a .tfvars file.
variable "upstash_email" {
  type = string
}

variable "upstash_api_key" {
  type      = string
  sensitive = true
}

# Connection details and credentials for the four isolated ZITADEL instances.
# The provider has no environment-variable fallback and each instance has its
# own service user, so credentials are per-instance. Supply this whole map via
# TF_VAR_zitadel_instances (Doppler-injected) — never in a .tfvars file.
variable "zitadel_instances" {
  type = map(object({
    domain           = string
    port             = number
    insecure         = bool
    jwt_profile_json = string
    # Which organization to build in, where the instance holds more than one.
    #
    # Optional, and normally absent: the module finds the single active
    # organization by itself. A ZITADEL Cloud instance keeps its own default
    # organization alongside any you create, and an instance that has ever been
    # set up by hand may hold two -- at which point the module cannot tell which
    # is yours and says so, naming both.
    org_id = optional(string)
  }))
  sensitive = true
}

variable "zitadel_redirect_uris" {
  type    = list(string)
  default = []
}

variable "zitadel_post_logout_redirect_uris" {
  type    = list(string)
  default = []
}

# Cloudflare's OWASP Core Ruleset requires a Pro plan or above. Leave false on
# a Free zone or the apply fails.
variable "enable_waf" {
  type    = bool
  default = false
}

variable "zitadel_role_grants" {
  type    = map(map(list(string)))
  default = {}

  description = <<-EOT
    Environment -> email address -> the roles that person holds there.

    Bootstrap access. `project_role_check` refuses a token to a user holding no
    role on the project, so an environment named nowhere here has nobody who
    can sign in to it -- which is the right default until someone decides who
    should.

    Emails and role names, so this belongs in terraform.tfvars rather than in
    Doppler: neither is a secret, and a reviewer should be able to see who is
    being granted what without decrypting anything.
  EOT
}

variable "fly_api_token" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Fly.io token, written to the repository so the deploy pipeline can use it."
}

variable "vercel_token" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Vercel token, written to the repository so the deploy pipeline can use it."
}

variable "repository_visibility" {
  type        = string
  default     = "private"
  description = "Repository visibility: private or public. Public repositories get free Actions minutes."
}

variable "required_approvals" {
  type        = map(number)
  default     = {}
  description = "Per-branch approving-review counts, e.g. { test = 0 }. Defaults: test 1, staging 1, main 2."
}
