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
  for_each = {
    develop = { required_approvals = 0, require_pr = false }
    test    = { required_approvals = 1, require_pr = true }
    staging = { required_approvals = 1, require_pr = true }
    main    = { required_approvals = 2, require_pr = true }
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

  required_status_checks {
    strict   = each.value.require_pr
    contexts = ["CI / Lint & Typecheck", "CI / Build"]
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
