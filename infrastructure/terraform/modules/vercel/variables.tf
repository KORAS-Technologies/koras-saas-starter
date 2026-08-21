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
  type        = string
  description = <<-EOT
    Override the build command for every project.

    Null means "derive it per application from the workspace package name",
    which is almost always what is wanted. A single shared string cannot be
    right for more than one application, and the previous default was a literal
    placeholder that no deployment could ever satisfy.
  EOT
  default     = null
}


variable "primary_domain" {
  type        = string
  description = <<-EOT
    Apex domain the applications are served under.

    Empty disables domain attachment entirely, which keeps the module usable for
    an estate that has not chosen a domain yet -- the projects still exist and
    answer on their generated *.vercel.app names.
  EOT
  default     = ""
}

variable "environment_branches" {
  type        = map(string)
  description = "Environment -> git branch. Each becomes one domain bound to that branch."
  default = {
    dev  = "develop"
    test = "test"
    stg  = "staging"
    prod = "main"
  }
}

variable "application_hostnames" {
  type        = map(string)
  description = <<-EOT
    Application key -> hostname label, where the two differ.

    The customer portal is served at `account`, not `portal`: the name a
    customer sees should describe what it is to them, not what the component is
    called in this repository.
  EOT
  default = {
    portal         = "account"
    platform_admin = "admin"
    web            = "app"
  }
}


