variable "project_slug" {
  type        = string
  description = "ZITADEL project name (no env suffix — instance IS the environment)"
}

variable "zitadel_instances" {
  type = map(object({
    domain   = string
    port     = number
    insecure = bool
  }))
  description = "Map of env key → ZITADEL instance connection details"
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

variable "profile" {
  type        = string
  description = "Generator profile: product or control-plane"

  validation {
    condition     = contains(["product", "control-plane"], var.profile)
    error_message = "profile must be 'product' or 'control-plane'."
  }
}
