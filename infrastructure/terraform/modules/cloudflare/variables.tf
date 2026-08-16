variable "zone_id" {
  type        = string
  description = "Cloudflare zone ID"
}

variable "project_slug" {
  type        = string
  description = "Used for WAF rule set naming"
}

variable "dns_records" {
  type = list(object({
    name    = string
    type    = string
    value   = string
    proxied = optional(bool, true)
    ttl     = optional(number, 1)
  }))
  description = "DNS records to create"
  default     = []
}

variable "enable_waf" {
  type    = bool
  default = true
}
