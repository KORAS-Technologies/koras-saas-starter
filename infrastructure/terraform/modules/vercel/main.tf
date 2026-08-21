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
  root_directory   = lookup(var.application_source_dirs, each.key, "apps/${each.key}")

  lifecycle {
    prevent_destroy = true
  }
}

# The hostnames each application actually answers on.
#
# Creating the project was never enough: a Vercel project with no domain is
# reachable only at its generated *.vercel.app URL, so the redirect URI ZITADEL
# sends a browser to after login pointed at a name that resolved to nothing.
# Sign-in completed and then landed on NXDOMAIN.
#
# One domain per environment, bound to that environment's branch. Vercel deploys
# every branch as a preview and this is what gives a preview a stable name --
# without the binding, `admin-dev` would follow whichever deployment was most
# recent, including one from an unrelated branch.
#
# `prod` is deliberately absent from the branch binding: the production domain
# follows the production deployment, which is what `--prod` on the `main` branch
# produces.
locals {
  domain_matrix = merge([
    for app in var.applications : {
      for environment, branch in var.environment_branches :
      "${app}-${environment}" => {
        app         = app
        environment = environment
        branch      = branch
        domain = environment == "prod" ? (
          "${lookup(var.application_hostnames, app, local.app_names[app])}.${var.primary_domain}"
          ) : (
          "${lookup(var.application_hostnames, app, local.app_names[app])}-${environment}.${var.primary_domain}"
        )
      }
    }
  ]...)
}

resource "vercel_project_domain" "domains" {
  for_each = var.primary_domain == "" ? {} : local.domain_matrix

  project_id = vercel_project.apps[each.value.app].id
  team_id    = var.team_id
  domain     = each.value.domain

  # Null for production: a git_branch on the production domain would pin it to
  # a branch and stop `--prod` from moving it.
  git_branch = each.value.environment == "prod" ? null : each.value.branch
}

