# Profile identity — set by create-koras-app in environments/<env>.tfvars.
# Terraform modules branch on this only where infrastructure genuinely differs.
variable "profile" {
  type = string
  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "profile must be one of: product, control-plane."
  }
}

variable "project_name" { type = string }
variable "project_slug" { type = string }

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "test", "stg", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, stg, prod."
  }
}

variable "github_org"      { type = string }
variable "primary_domain"  { type = string }
variable "enabled_apps"    { type = list(string); default = [] }
variable "enabled_services"{ type = list(string); default = [] }
variable "supabase_org_id" { type = string }
variable "supabase_region" { type = string; default = "eu-central-1" }
variable "supabase_environments" {
  type      = map(object({ db_password = string; region = string }))
  sensitive = true
}
variable "vercel_team_id"       { type = string }
variable "fly_org_slug"         { type = string }
variable "fly_regions"          { type = map(string) }
variable "cloudflare_zone_id"   { type = string }
variable "zitadel_instances" {
  type = map(object({ domain = string; port = number; insecure = bool }))
}
variable "zitadel_redirect_uris"             { type = list(string); default = [] }
variable "zitadel_post_logout_redirect_uris" { type = list(string); default = [] }
