variable "project_slug" {
  type        = string
  description = "Base name; app name is appended"
}

variable "team_id" {
  type        = string
  description = "Vercel team ID"
}

variable "applications" {
  type        = list(string)
  description = "Application names to create Vercel projects for"
}

variable "git_repository" {
  type        = string
  description = "GitHub repository in org/repo format"
}

variable "framework" {
  type    = string
  default = "nextjs"
}

variable "build_command" {
  type    = string
  default = "pnpm turbo run build --filter=@PROJECT_SLUG/APP_NAME"
}
