variable "project_name" {
  type        = string
  description = "Human-readable project name"
}

variable "project_slug" {
  type        = string
  description = "URL/resource-safe project identifier"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,48}[a-z0-9]$", var.project_slug))
    error_message = "project_slug must be 2-50 lowercase letters, digits, or hyphens."
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

variable "github_org" {
  type        = string
  description = "GitHub organisation name"
}

variable "primary_domain" {
  type        = string
  description = "Primary domain for the project"
}

variable "enabled_apps" {
  type        = list(string)
  description = "Applications to provision (used by product profile)"
  default     = []
}

variable "enabled_services" {
  type        = list(string)
  description = "Services to provision Fly apps for"
  default     = []
}

# ── Provider account IDs ───────────────────────────────────────────────────────

variable "supabase_org_id" {
  type      = string
  sensitive = false
}

variable "vercel_team_id" {
  type = string
}

variable "fly_org_slug" {
  type = string
}

variable "cloudflare_zone_id" {
  type = string
}

# ── ZITADEL instances ─────────────────────────────────────────────────────────
#
# Instance connection details are NOT passed in as a variable — each instance is
# a separate aliased provider configured in the root module and wired here via
# the `providers` argument.

variable "zitadel_redirect_uris" {
  type    = list(string)
  default = []
}

variable "zitadel_post_logout_redirect_uris" {
  type    = list(string)
  default = []
}

# ── Supabase environments ─────────────────────────────────────────────────────

variable "supabase_environments" {
  type = map(object({
    db_password = string
    region      = string
  }))
  sensitive = true
}

# ── Region configuration ──────────────────────────────────────────────────────

variable "fly_regions" {
  type = map(string)
  default = {
    dev  = "ams"
    test = "ams"
    stg  = "ams"
    prod = "ams"
  }
}
