resource "github_repository" "this" {
  name        = var.project_slug
  description = var.description
  visibility  = var.visibility
  auto_init   = true

  has_issues   = true
  has_projects = false
  has_wiki     = false

  delete_branch_on_merge = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_branch" "branches" {
  for_each = toset(["develop", "test", "staging", "main"])

  repository    = github_repository.this.name
  branch        = each.key
  source_branch = "main"

  depends_on = [github_repository.this]
}

resource "github_branch_default" "default" {
  repository = github_repository.this.name
  branch     = "develop"
  depends_on = [github_branch.branches]
}

resource "github_branch_protection" "protections" {
  # The approval counts are overridable because how many reviewers exist is a
  # property of the organisation, not of this factory. GitHub does not let
  # anyone approve their own pull request, so on a single-maintainer estate
  # every one of these above zero is a rule that cannot be satisfied rather than
  # a rule that is strict -- the promotion simply stops, with the protection
  # reporting REVIEW_REQUIRED and no one able to give it.
  #
  # Whether a pull request is required at all is not overridable. That gate
  # costs a solo operator nothing -- they can open and merge their own -- while
  # still running the checks.
  for_each = {
    develop = { required_approvals = 0, require_pr = false }
    test    = { required_approvals = lookup(var.required_approvals, "test", 1), require_pr = true }
    staging = { required_approvals = lookup(var.required_approvals, "staging", 1), require_pr = true }
    main    = { required_approvals = lookup(var.required_approvals, "main", 2), require_pr = true }
  }

  repository_id = github_repository.this.node_id
  pattern       = each.key

  require_conversation_resolution = true
  enforce_admins                  = each.value.require_pr

  dynamic "required_pull_request_reviews" {
    for_each = each.value.require_pr ? [1] : []
    content {
      required_approving_review_count = each.value.required_approvals
      dismiss_stale_reviews           = true
    }
  }

  # Only on the branches that gate through a pull request.
  #
  # A required status check cannot be satisfied by a direct push: the checks run
  # against a commit that does not exist on the server until the push completes,
  # so GitHub reports them as `expected` and refuses. `develop` permits direct
  # pushes by design -- ENVIRONMENT_STRATEGY calls it fast feedback that may be
  # broken -- so requiring checks there made every push to it a bypass, recorded
  # as a rule violation and waved through because the pusher was an admin.
  #
  # A protection that is bypassed on every use is not a protection. It is a line
  # in an audit log that everyone learns to scroll past, and it was hiding the
  # fact that test, staging and main are gated properly.
  dynamic "required_status_checks" {
    for_each = each.value.require_pr ? [1] : []
    content {
      strict = true

      # Every job the generated CI defines, named the way GitHub actually
      # reports it: the job name alone.
      #
      # These read "CI / Secret scan" before, on the belief that a check is
      # reported as "<workflow> / <job>". That form is real but belongs to
      # called workflows -- deploy.yml is invoked by deploy-dev.yml and its jobs
      # do arrive as "deploy / Migrate (dev)". A workflow's own jobs do not
      # carry the prefix, so all five contexts sat in Expected forever and no
      # pull request to test, staging or main could merge, while every check on
      # it was green. A required check that cannot be reported is indistinguish-
      # able from one that has not finished, which is why this survived: the
      # branch looked strict rather than broken.
      #
      # Requiring only lint and build let a pull request with failing tests, or
      # a secret in its history, merge to main -- the two checks most worth
      # blocking on were the two not required.
      contexts = [
        "Secret scan",
        "Lint & Typecheck",
        "Test (Node)",
        "Test (Python)",
        "End-to-end (browser)",
        "Build",
      ]
    }
  }

  depends_on = [github_branch.branches]
}

resource "github_repository_environment" "environments" {
  for_each = {
    dev  = { branch = "develop" }
    test = { branch = "test" }
    stg  = { branch = "staging" }
    prod = { branch = "main" }
  }

  repository  = github_repository.this.name
  environment = each.key

  dynamic "reviewers" {
    for_each = contains(["stg", "prod"], each.key) ? [1] : []
    content {
      teams = var.reviewer_team_ids
    }
  }

  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }

  depends_on = [github_branch.branches]
}

# ── What the deploy pipeline is given ───────────────────────────────────────
#
# The workflow declares five secrets `required: true`, and a workflow_call with
# an unsatisfied required secret fails before any step runs. Nothing set them,
# so every generated project had a deploy pipeline that could not start -- on
# every push, permanently, with a log too empty to say why.
#
# The same shape as roles defined and granted to nobody: the resource was
# created and the thing that makes it usable was not.

resource "github_actions_environment_secret" "doppler" {
  # Iterating the map directly is refused: a for_each key becomes part of a
  # resource address, so Terraform will not take one from a sensitive value.
  # Declassifying the keys is safe and the values stay sensitive -- these keys
  # are environment names, which are already in every branch name and workflow
  # in the repository.
  for_each = toset(nonsensitive(keys(var.doppler_deploy_tokens)))

  repository  = github_repository.this.name
  environment = each.key
  secret_name = "DOPPLER_TOKEN"
  value       = var.doppler_deploy_tokens[each.key]

  depends_on = [github_repository_environment.environments]
}

resource "github_actions_secret" "estate" {
  # Same reason. Here the keys are the secret names themselves.
  for_each = toset(nonsensitive(keys(var.estate_deploy_secrets)))

  repository  = github_repository.this.name
  secret_name = each.key
  value       = var.estate_deploy_secrets[each.key]
}