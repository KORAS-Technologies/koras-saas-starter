resource "vercel_project" "apps" {
  for_each = toset(var.applications)

  name      = "${var.project_slug}-${each.key}"
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
