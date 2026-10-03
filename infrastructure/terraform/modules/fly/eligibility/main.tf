# Which service runs in which environment, read from the services' own
# descriptors (services/<service>/service.yaml).
#
# This module is the Terraform half of a rule with two halves. The other is
# local/scripts/service-descriptor.sh, which the deploy workflow runs to decide
# what to deploy. They read the SAME file and are held to the same answers by a
# test that runs both over one corpus -- generators/create-koras-app/tests/
# service-descriptor-parity.test.ts. Change a rule in one and that test fails
# until it is changed in the other.
#
# It declares no provider on purpose: it can be applied on its own, with no
# credentials and no network, which is how the parity test exercises it.
#
# A service with no descriptor is the legacy case: every environment, public.
# A descriptor is never required.

terraform {
  required_version = ">= 1.5"
}

variable "services" {
  type        = list(string)
  description = "Service keys, as in the manifest (underscored). The directory is the key with hyphens."
}

variable "environments" {
  type    = list(string)
  default = ["dev", "test", "stg", "prod"]
}

variable "services_dir" {
  type        = string
  default     = null
  description = "Directory holding services/<dir>/service.yaml. Null means no descriptors are read: every service is legacy."
}

locals {
  # The environment mapping is immutable (ADR required to change it).
  valid_environments = ["dev", "test", "stg", "prod"]
  valid_policies     = ["inherit", "none", "allowlist"]
  valid_networks     = ["public", "private"]
  top_keys           = ["schema_version", "environments", "secrets", "network"]
  secret_keys        = ["policy", "allowlist"]

  dirs = { for s in var.services : s => replace(s, "_", "-") }

  paths = {
    for s, d in local.dirs :
    s => var.services_dir == null ? null : "${var.services_dir}/${d}/service.yaml"
  }

  present = { for s, p in local.paths : s => p != null && fileexists(p) }

  # yamldecode fails the plan on malformed YAML, which is the right answer.
  raw = { for s, p in local.paths : s => local.present[s] ? yamldecode(file(p)) : null }

  is_map = { for s, d in local.raw : s => d != null && can(keys(d)) }

  has_env = { for s, d in local.raw : s => try(contains(keys(d), "environments"), false) }
  has_sec = { for s, d in local.raw : s => try(contains(keys(d), "secrets"), false) }
  has_net = { for s, d in local.raw : s => try(contains(keys(d), "network"), false) }

  # Each rule, spelled the way service-descriptor.sh spells it. Every
  # expression is wrapped: a wrong type is a rule failing, not a crash.
  errors = {
    for s, d in local.raw : s => local.present[s] ? concat(
      local.is_map[s] ? [] : ["not a mapping"],
      !local.is_map[s] ? [] : (
        length(setsubtract(keys(d), local.top_keys)) == 0 ? [] : ["unknown key(s): ${join(", ", setsubtract(keys(d), local.top_keys))}"]
      ),
      !local.is_map[s] ? [] : (
        try(contains(keys(d), "schema_version") && jsonencode(d.schema_version) == "1", false) ? [] : ["schema_version must be the number 1"]
      ),
      !local.is_map[s] || !local.has_env[s] ? [] : (
        try(
          length(d.environments) > 0
          && alltrue([for e in d.environments : tostring(e) == e && contains(local.valid_environments, e)])
          && length(toset(d.environments)) == length(d.environments)
          && !can(keys(d.environments)),
          false
        ) ? [] : ["environments must be a non-empty list of unique names from: ${join(", ", local.valid_environments)}"]
      ),
      !local.is_map[s] || !local.has_sec[s] ? [] : (
        try(
          can(keys(d.secrets))
          && length(setsubtract(keys(d.secrets), local.secret_keys)) == 0
          && tostring(d.secrets.policy) == d.secrets.policy
          && contains(local.valid_policies, d.secrets.policy)
          && (
            d.secrets.policy == "allowlist"
            ? (
              length(d.secrets.allowlist) > 0
              && !can(keys(d.secrets.allowlist))
              && alltrue([for n in d.secrets.allowlist : tostring(n) == n && can(regex("^[A-Z][A-Z0-9_]*$", n)) && !startswith(n, "DOPPLER_")])
              && length(toset(d.secrets.allowlist)) == length(d.secrets.allowlist)
            )
            : !contains(keys(d.secrets), "allowlist")
          ),
          false
        ) ? [] : ["secrets must be {policy: inherit|none|allowlist} with a non-empty list of exact NAMES for allowlist and no allowlist otherwise"]
      ),
      !local.is_map[s] || !local.has_net[s] ? [] : (
        try(tostring(d.network) == d.network && contains(local.valid_networks, d.network), false) ? [] : ["network must be public or private"]
      ),
    ) : []
  }

  # Normalised only once valid; an invalid descriptor fails below before any
  # of this is used.
  ok = { for s in var.services : s => length(local.errors[s]) == 0 }

  env_list = {
    for s in var.services :
    s => (local.present[s] && local.ok[s] && local.has_env[s]) ? tolist(local.raw[s].environments) : null
  }

  policy = {
    for s in var.services :
    s => (local.present[s] && local.ok[s] && local.has_sec[s]) ? local.raw[s].secrets.policy : "inherit"
  }

  allowlist = {
    for s in var.services :
    s => (local.present[s] && local.ok[s] && local.has_sec[s] && local.policy[s] == "allowlist") ? tolist(local.raw[s].secrets.allowlist) : []
  }

  network = {
    for s in var.services :
    s => (local.present[s] && local.ok[s] && local.has_net[s]) ? local.raw[s].network : "public"
  }

  eligible_in = {
    for env in var.environments :
    # A conditional, not `== null || contains(...)`: HCL's `||` does not
    # short-circuit on older Terraform, so `contains(null, env)` was evaluated
    # for every service with no environment list and failed the plan. Newer
    # versions tolerate it, which is why it passed on the author's machine and
    # failed on the CI runner's.
    env => [for s in var.services : s if local.env_list[s] == null ? true : contains(local.env_list[s], env)]
  }
}

# Fails the plan, naming the service and the rule. Nothing is created from a
# descriptor that is not understood: a typo here is a service in the wrong
# place or holding the wrong secrets.
resource "terraform_data" "descriptor_check" {
  for_each = { for s in var.services : s => s if local.present[s] }

  lifecycle {
    precondition {
      condition     = length(local.errors[each.key]) == 0
      error_message = "${local.paths[each.key]} is not a valid service descriptor: ${join("; ", local.errors[each.key])}"
    }
  }
}

output "eligible" {
  description = "Map of environment to the service keys that run there."
  value       = local.eligible_in
}

output "matrix" {
  description = "Map of '<service>-<env>' to {service, environment}, for exactly the eligible pairs."
  value = {
    for pair in flatten([
      for env in var.environments : [
        for s in local.eligible_in[env] : { key = "${s}-${env}", service = s, environment = env }
      ]
    ]) : pair.key => { service = pair.service, environment = pair.environment }
  }
}

output "private_services" {
  description = "Service keys declared network: private. These get no public URL."
  value       = [for s in var.services : s if local.network[s] == "private"]
}

output "secret_policy" {
  description = "Map of service key to {policy, allowlist}."
  value       = { for s in var.services : s => { policy = local.policy[s], allowlist = local.allowlist[s] } }
}
