variable "project_slug" {
  type        = string
  description = "Base project slug; service and env are appended"
}

variable "org_slug" {
  type        = string
  description = "Fly.io organisation slug"
}

variable "services" {
  type        = list(string)
  description = "Services to create Fly apps for"
}

variable "environments" {
  type    = list(string)
  default = ["dev", "test", "stg", "prod"]
}

variable "regions" {
  type        = map(string)
  description = "Map of env → Fly region"
  default = {
    dev  = "iad"
    test = "iad"
    stg  = "iad"
    prod = "iad"
  }
}
