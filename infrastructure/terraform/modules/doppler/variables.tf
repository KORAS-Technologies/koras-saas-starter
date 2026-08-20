variable "project_slug" {
  type        = string
  description = "Doppler project name"
}

variable "description" {
  type    = string
  default = ""
}

variable "environments" {
  type        = list(string)
  description = "Doppler environments to create"
  default     = ["dev", "test", "stg", "prod"]
}

variable "queue_urls" {
  type        = map(string)
  sensitive   = true
  default     = {}
  description = <<-EOT
    Map of environment -> rediss:// queue URL, written as REDIS_URL into that
    environment's config.

    Doppler is the sole secret authority, so a credential Terraform created is
    only usable once it lands here: a deployed worker reads its configuration
    from Doppler and knows nothing about Terraform state or outputs.
  EOT
}
