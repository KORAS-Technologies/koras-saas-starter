variable "project_slug" {
  type        = string
  description = "Base name for the Redis databases; the environment is appended."
}

variable "environments" {
  type        = set(string)
  description = "Environments needing a queue. One database each -- never one shared."

  validation {
    condition     = length(var.environments) > 0
    error_message = "At least one environment must be provided."
  }
}

variable "region" {
  type        = string
  description = <<-EOT
    Upstash region for every database.

    Co-located with the services that use it. A queue in a different region
    than its worker pays the round trip on every poll, and the worker polls
    continuously.
  EOT
  default     = "us-east-1"
}

variable "eviction" {
  type        = bool
  description = <<-EOT
    Whether Redis may evict keys under memory pressure.

    False, and it must stay false. This is a job queue: an evicted key is a
    provisioning job that vanishes silently, leaving a customer half-onboarded
    with nothing recording that anything was lost.
  EOT
  default     = false
}
