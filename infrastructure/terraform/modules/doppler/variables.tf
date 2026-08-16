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
