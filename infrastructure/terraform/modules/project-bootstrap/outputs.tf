output "github_repository_url" {
  value = module.github.repository_url
}

output "github_repository_full_name" {
  value = module.github.repository_full_name
}

output "doppler_project_name" {
  value = module.doppler.project_name
}

output "supabase_project_refs" {
  description = "Non-secret Supabase project references per environment"
  value       = module.supabase.project_refs
}

output "supabase_project_api_urls" {
  value = module.supabase.project_api_urls
}

output "zitadel_project_ids" {
  value = module.zitadel.project_ids
}

output "zitadel_client_ids" {
  description = "OIDC client IDs (non-secret)"
  value       = module.zitadel.client_ids
}

output "vercel_project_ids" {
  value = module.vercel.project_ids
}

output "fly_app_names" {
  value = module.fly.app_names
}

output "fly_app_hostnames" {
  value = module.fly.app_hostnames
}
