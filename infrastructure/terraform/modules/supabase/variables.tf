variable "project_slug" {
  type        = string
  description = "Base name for Supabase projects; env suffix is appended"
}

variable "organization_id" {
  type        = string
  description = "Supabase organisation ID"
}

variable "environments" {
  type = map(object({
    db_password = string
    region      = string
  }))
  description = "Map of env name → config. Passwords are sensitive and sourced from Doppler."

  validation {
    condition     = length(var.environments) > 0
    error_message = "At least one environment must be provided."
  }
}
