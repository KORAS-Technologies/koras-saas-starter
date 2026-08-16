resource "supabase_project" "envs" {
  for_each = var.environments

  organization_id   = var.organization_id
  name              = "${var.project_slug}-${each.key}"
  database_password = each.value.db_password
  region            = each.value.region

  lifecycle {
    # Prevent accidental destruction of production data
    prevent_destroy = true
    # DB password rotation happens outside Terraform
    ignore_changes = [database_password]
  }
}
