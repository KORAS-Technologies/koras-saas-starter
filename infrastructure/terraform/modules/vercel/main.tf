locals {
  # Component keys are Terraform/YAML identifiers and may contain underscores
  # (`platform_admin`). Vercel project names may not: they accept lowercase
  # alphanumerics and hyphens only, and reject the name outright at plan time.
  app_names = { for app in var.applications : app => replace(app, "_", "-") }

  # The workspace package each project builds.
  #
  # Derived from the source directory, not from the component key. The key is a
  # Terraform identifier (`platform_admin`); the package is named after the
  # directory (`apps/admin` -> `@slug/admin`), and the two differ for exactly
  # the components most likely to be enabled.
  #
  # This used to be a single `build_command` variable whose default carried
  # unsubstituted upper-case placeholders for the slug and the app name. Nothing
  # ever replaced them, so every Vercel project in every generated estate held a
  # build command naming a package that cannot exist -- and it failed only when
  # a deployment was finally attempted, with "No package found".
  #
  # The placeholder text is deliberately not repeated here: a check that forbids
  # a literal string is defeated by a comment quoting it.
  package_names = {
    for app in var.applications :
    app => "@${var.project_slug}/${basename(lookup(var.application_source_dirs, app, "apps/${app}"))}"
  }
}


locals {
  # One project per application per environment.
  #
  # Two projects and four environments does not work, and the reason is
  # structural rather than a configuration mistake. A Vercel project has three
  # environment-variable targets -- production, preview, development -- not one
  # per estate. Isolating four environments inside one project therefore needs
  # preview variables scoped per git branch, and Vercel only learns a
  # repository's branches from git-triggered deployments. These are deployed
  # from CI with the CLI, so it never learns them: every branch-scoped call
  # fails with `Branch "develop" not found in the connected Git repository`.
  #
  # Splitting by environment removes the dependency instead of working around
  # it. Each project has exactly one estate, so its own production target holds
  # that estate's settings, its own domain points at it, and nothing needs to
  # know what a branch is. It also matches how the rest of the estate is already
  # arranged -- four Supabase projects, four ZITADEL instances, twelve Fly apps.
  #
  # The cost is eight projects rather than two. The alternative was one working
  # application environment and dev credentials living in a target named
  # production.
  project_matrix = merge([
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

resource "vercel_project" "apps" {
  for_each = local.project_matrix

  name      = "${var.project_slug}-${local.app_names[each.value.app]}-${each.value.environment}"
  team_id   = var.team_id
  framework = var.framework

  git_repository = {
    type = "github"
    repo = var.git_repository
    # This environment's branch is this project's production branch. That is
    # what makes each project a single estate rather than a shared one.
    production_branch = each.value.branch
  }

  build_command    = coalesce(var.build_command, "pnpm turbo run build --filter=${local.package_names[each.value.app]}")
  output_directory = ".next"
  install_command  = "pnpm install --frozen-lockfile"
  root_directory   = lookup(var.application_source_dirs, each.value.app, "apps/${each.value.app}")

  lifecycle {
    prevent_destroy = true
  }
}

# The hostname this project answers on.
#
# One per project, on the production target, with no branch binding: the
# project *is* the environment, so its production deployment is the only thing
# the name should ever point at. The branch-bound variant this replaces could
# not be created at all until the project had already deployed once.
resource "vercel_project_domain" "primary" {
  for_each = var.primary_domain == "" ? {} : local.project_matrix

  project_id = vercel_project.apps[each.key].id
  team_id    = var.team_id
  domain     = each.value.domain
}
