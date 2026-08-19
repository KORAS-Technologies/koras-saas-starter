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

variable "application_source_dirs" {
  type        = map(string)
  description = <<-EOT
    Component key to source directory, e.g. { platform_admin = "apps/admin" }.
    Component keys are identifiers and need not match their directory, so the
    directory cannot be derived from the key. Inferring it produced Vercel
    projects rooted at a path that had never existed, which surfaces only as a
    failed build.
  EOT
  default     = {}
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
