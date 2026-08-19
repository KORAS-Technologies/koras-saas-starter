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
