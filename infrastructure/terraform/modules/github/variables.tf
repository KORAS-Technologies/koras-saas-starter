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
