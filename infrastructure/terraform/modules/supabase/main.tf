locals {
  # `for_each` rejects sensitive values, because instance keys appear in
  # resource addresses and plan output. Only the passwords inside this map are
  # secret — the keys are just environment names, so declassifying the key set
  # exposes nothing. Passwords are still read through the sensitive variable
  # below and never widened.
  environment_names = toset(nonsensitive(keys(var.environments)))
}

resource "supabase_project" "envs" {
  for_each = local.environment_names

  organization_id   = var.organization_id
  name              = "${var.project_slug}-${each.key}"
  database_password = var.environments[each.key].db_password
  region            = coalesce(var.environments[each.key].region, var.default_region)

  lifecycle {
    # Prevent accidental destruction of production data
    prevent_destroy = true
    # DB password rotation happens outside Terraform
    ignore_changes = [database_password]
  }
}
