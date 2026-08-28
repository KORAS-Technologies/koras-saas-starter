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

output "zitadel_resolved_org_ids" {
  description = <<-EOT
    Map of env → the organization each ZITADEL project was created in.

    Not `zitadel_org_ids`, which is the *variable* above and means something
    narrower: the orgs an operator named. This is what each module resolved --
    the named one where there was one, the discovered one everywhere else. One
    name for both would make the difference invisible at exactly the point it
    matters.

    Paired with zitadel_project_ids, and useless apart from it: a project id
    identifies nothing without the org it lives in. Teardown sends both, because
    a management-API delete aimed at the wrong organization answers 404 rather
    than failing, and 404 is how teardown recognises a resource that is already
    gone.
  EOT
  value = {
    dev  = module.zitadel_dev.org_id
    test = module.zitadel_test.org_id
    stg  = module.zitadel_stg.org_id
    prod = module.zitadel_prod.org_id
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

output "redis_database_ids" {
  description = "Map of env -> Upstash database id. What teardown deletes by."
  value       = module.upstash.redis_database_ids
}

output "vercel_domains" {
  description = "Map of '<app>-<environment>' -> hostname, as attached to the Vercel project."
  value       = module.vercel.domains
}

output "cloudflare_record_ids" {
  description = <<-EOT
    Map of hostname → Cloudflare DNS record id.

    The module has exported record_ids since it was written; nothing above it
    ever asked, so eight records survived a teardown that reported none
    retained. An inventory can only miss what it is not told about, and the
    count it prints is the least likely thing to reveal the omission.
  EOT
  value       = module.cloudflare.record_ids
}

output "cloudflare_zone_id" {
  description = "The zone the records live in. A record id cannot be deleted without it."
  value       = var.cloudflare_zone_id
}
