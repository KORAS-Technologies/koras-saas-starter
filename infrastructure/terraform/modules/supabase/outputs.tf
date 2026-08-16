output "project_refs" {
  description = "Map of env → Supabase project ref (non-secret)"
  value       = { for k, v in supabase_project.envs : k => v.id }
}

output "project_api_urls" {
  description = "Map of env → Supabase API URL (non-secret)"
  value       = { for k, v in supabase_project.envs : k => "https://${v.id}.supabase.co" }
}
