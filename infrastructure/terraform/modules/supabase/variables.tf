variable "project_slug" {
  type        = string
  description = "Base name for Supabase projects; env suffix is appended"
}

variable "organization_id" {
  type        = string
  description = "Supabase organisation ID"
}

variable "default_region" {
  type        = string
  description = "Region for environments that do not name one of their own."

  validation {
    condition     = length(var.default_region) > 0
    error_message = "default_region must be set; it is the fallback when an environment omits region."
  }
}

variable "environments" {
  type = map(object({
    db_password = string
    region      = optional(string)
  }))
  description = "Map of env name → config. Passwords are sensitive and sourced from Doppler. region is optional and falls back to default_region."

  validation {
    condition     = length(var.environments) > 0
    error_message = "At least one environment must be provided."
  }
}
