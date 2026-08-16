output "repository_url" {
  description = "HTTPS clone URL"
  value       = github_repository.this.html_url
}

output "repository_full_name" {
  description = "org/repo format"
  value       = github_repository.this.full_name
}

output "repository_name" {
  value = github_repository.this.name
}

output "ssh_clone_url" {
  value = github_repository.this.ssh_clone_url
}
