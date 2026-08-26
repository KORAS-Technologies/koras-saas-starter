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

variable "application_source_dirs" {
  type        = map(string)
  description = "Component key to source directory for Vercel projects."
  default     = {}
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
    region      = optional(string)
  }))
  sensitive = true
}

# ── Region configuration ──────────────────────────────────────────────────────

variable "supabase_region" {
  type        = string
  description = "Default Supabase region; supabase_environments may override per environment."
}

variable "fly_regions" {
  type = map(string)
  default = {
    dev  = "iad"
    test = "iad"
    stg  = "iad"
    prod = "iad"
  }
}

# Cloudflare's OWASP Core Ruleset requires a Pro plan or above; a Free zone
# rejects it, so this defaults off and must be opted into.
variable "enable_waf" {
  type    = bool
  default = false
}

variable "upstash_region" {
  type        = string
  description = "Upstash region for the queue databases. Co-locate with fly_regions."
  default     = "us-east-1"
}

# Environment -> git branch. The key set is the list of environments, which
# is what the OIDC redirect URIs and the Vercel projects are both keyed by:
# one definition, so an environment cannot exist in one and not the other.
variable "environment_branches" {
  type = map(string)
  default = {
    dev  = "develop"
    test = "test"
    stg  = "staging"
    prod = "main"
  }
}

variable "zitadel_role_grants" {
  type    = map(map(list(string)))
  default = {}

  description = <<-EOT
    Environment -> email address -> the roles that person holds there.

    Per environment on purpose. Access to dev is not access to prod, and a
    single list applied everywhere is how someone ends up holding production
    authority because they needed to debug staging.

    An environment absent from this map grants nobody, which leaves it
    unreachable: project_role_check refuses a token to a user with no role.
    That is the correct default for an estate nobody has decided about yet.
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
  description = <<-EOT
    Repository visibility: private or public.

    Declared rather than assumed. A repository made public by hand -- to get
    free Actions minutes, most often -- was silently reverted to private by the
    next apply, which also stopped every workflow that change was meant to
    unblock.
  EOT

  validation {
    condition     = contains(["private", "public"], var.repository_visibility)
    error_message = "repository_visibility must be 'private' or 'public'."
  }
}

variable "required_approvals" {
  type        = map(number)
  default     = {}
  description = "Per-branch approving-review counts. See the github module."
}

variable "zitadel_org_ids" {
  description = <<-DESC
    Which ZITADEL organization to build in, per environment.

    Only the ids, not the instance config: the providers are configured at the
    root and passed in, so this module needs nothing else about an instance --
    and passing the whole object would hand it service-account JWTs it has no
    use for.

    Normally empty. The zitadel module finds the single active organization by
    itself and refuses to guess when an instance holds more than one, naming
    both. An entry here answers that question for that environment.
  DESC
  type        = map(string)
  default     = {}
}
