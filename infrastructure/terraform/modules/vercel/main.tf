locals {
  # Component keys are Terraform/YAML identifiers and may contain underscores
  # (`platform_admin`). Vercel project names may not: they accept lowercase
  # alphanumerics and hyphens only, and reject the name outright at plan time.
  app_names = { for app in var.applications : app => replace(app, "_", "-") }
}

resource "vercel_project" "apps" {
  for_each = toset(var.applications)

  name      = "${var.project_slug}-${local.app_names[each.key]}"
  team_id   = var.team_id
  framework = var.framework

  git_repository = {
    type              = "github"
    repo              = var.git_repository
    production_branch = "main"
  }

  build_command    = var.build_command
  output_directory = ".next"
  install_command  = "pnpm install --frozen-lockfile"
  root_directory   = "apps/${each.key}"

  lifecycle {
    prevent_destroy = true
  }
}
