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

  # The primary_region list is narrower than the old region list and spells
  # eu-central-1 with the dash that the deprecated region form omitted. A typo
  # here would otherwise surface as a 400 from Upstash partway through apply.
  validation {
    condition = contains([
      "us-east-1", "us-west-1", "us-west-2",
      "eu-central-1", "eu-west-1", "sa-east-1",
      "ap-southeast-1", "ap-southeast-2",
    ], var.region)
    error_message = "Must be an Upstash primary region: us-east-1, us-west-1, us-west-2, eu-central-1, eu-west-1, sa-east-1, ap-southeast-1, ap-southeast-2."
  }
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
