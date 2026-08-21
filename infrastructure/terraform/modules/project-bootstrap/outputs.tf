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
  description = "Map of env → ZITADEL project ID"
  value = {
    dev  = module.zitadel_dev.project_id
    test = module.zitadel_test.project_id
    stg  = module.zitadel_stg.project_id
    prod = module.zitadel_prod.project_id
  }
}

output "zitadel_client_ids" {
  description = "Map of env → OIDC client ID (non-secret)"
  sensitive   = true
  value = {
    dev  = module.zitadel_dev.client_id
    test = module.zitadel_test.client_id
    stg  = module.zitadel_stg.client_id
    prod = module.zitadel_prod.client_id
  }
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

output "redis_urls" {
  description = "Map of env -> rediss:// queue URL. Embeds the password."
  sensitive   = true
  value       = module.upstash.redis_urls
}

output "redis_endpoints" {
  description = "Map of env -> queue host, without the credential."
  value       = module.upstash.redis_endpoints
}

output "vercel_domains" {
  description = "Map of '<app>-<environment>' -> hostname, as attached to the Vercel project."
  value       = module.vercel.domains
}

