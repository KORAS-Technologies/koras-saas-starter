variable "project_slug" {
  type        = string
  description = "ZITADEL project name (no env suffix — instance IS the environment)"
}

variable "environment" {
  type        = string
  description = "Environment this ZITADEL instance represents"

  validation {
    condition     = contains(["dev", "test", "stg", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, stg, prod."
  }
}

variable "profile" {
  type        = string
  description = "Generator profile: product or control-plane"

  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "profile must be 'product' or 'control-plane'."
  }
}

variable "redirect_uris" {
  type        = list(string)
  description = "Allowed OIDC redirect URIs"
  default     = []
}

variable "post_logout_redirect_uris" {
  type        = list(string)
  description = "Allowed post-logout redirect URIs"
  default     = []
}
