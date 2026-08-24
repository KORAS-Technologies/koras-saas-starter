variable "project_slug" {
  type        = string
  description = "Repository name and project slug"
}

variable "github_org" {
  type        = string
  description = "GitHub organisation name"
}

variable "description" {
  type        = string
  description = "Repository description"
  default     = ""
}

variable "visibility" {
  type        = string
  description = "Repository visibility: private or public"
  default     = "private"

  validation {
    condition     = contains(["private", "public"], var.visibility)
    error_message = "visibility must be 'private' or 'public'."
  }
}

variable "reviewer_team_ids" {
  type        = list(string)
  description = "GitHub team IDs required to approve stg/prod deployments"
  default     = []
}

variable "doppler_deploy_tokens" {
  type      = map(string)
  default   = {}
  sensitive = true

  description = <<-EOT
    Environment -> a read-only Doppler service token scoped to that config.

    Written as a GitHub environment secret, which is the one credential the
    deploy pipeline needs before it can read anything else. Everything the
    pipeline uses beyond this comes from Doppler with it.
  EOT
}

variable "estate_deploy_secrets" {
  type      = map(string)
  default   = {}
  sensitive = true

  description = <<-EOT
    Repository-level secrets the deploy pipeline needs, by name.

    Repository rather than environment because these are identical in all four:
    the Fly and Vercel credentials are estate-wide, so scoping them per
    environment would be theatre -- four copies of one secret, and four places
    to rotate it.

    That they are estate-wide is worth knowing rather than hiding. A leaked Fly
    token reaches every application in the estate, not just this product's, and
    a per-project deploy token would be the fix. Recorded in the risk register
    rather than left as a decision nobody made.
  EOT
}
variable "required_approvals" {
  type        = map(number)
  default     = {}
  description = <<-EOT
    Per-branch approving-review counts, overriding the defaults of test 1,
    staging 1, main 2. `develop` is always 0 and is not overridable.
  EOT
}
