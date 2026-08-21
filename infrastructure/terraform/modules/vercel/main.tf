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

  build_command    = coalesce(var.build_command, "pnpm turbo run build --filter=${local.package_names[each.key]}")
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

# Production domains. These follow the production deployment and need no
# branch, so they attach to a project that has never deployed.
resource "vercel_project_domain" "production" {
  for_each = {
    for key, d in local.domain_matrix : key => d if d.environment == "prod"
  }

  project_id = vercel_project.apps[each.value.app].id
  team_id    = var.team_id
  domain     = each.value.domain
}

# Per-environment domains, each pinned to the branch that deploys it.
#
# Gated, because attaching one requires Vercel to already know the branch
# exists -- and Vercel learns a repository's branches from deployments, not from
# the Git provider. On a project that has never deployed, every one of these
# fails with `git_branch_not_found` even though the branch is present on GitHub
# and the Git integration is installed.
#
# That makes first-time provisioning a chicken and egg: the domains want a
# deployment, and a deployment is what the pipeline does after provisioning. So
# the order is provision, deploy once, then set attach_branch_domains and apply
# again. Defaulting this to true would mean every fresh estate fails its first
# apply on something that is not wrong.
resource "vercel_project_domain" "branches" {
  for_each = var.attach_branch_domains ? {
    for key, d in local.domain_matrix : key => d if d.environment != "prod"
  } : {}

  project_id = vercel_project.apps[each.value.app].id
  team_id    = var.team_id
  domain     = each.value.domain
  git_branch = each.value.branch
}
