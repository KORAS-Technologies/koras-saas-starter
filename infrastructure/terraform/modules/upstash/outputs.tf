output "redis_urls" {
  description = <<-EOT
    Map of environment -> rediss:// connection URL.

    Sensitive: the URL embeds the password, so this is a credential rather than
    an address. It reaches Doppler through the bootstrap script, which is what
    makes Doppler the authority; Terraform state holds a copy because the
    provider returns one, and there is no way to ask it not to.
  EOT
  sensitive   = true
  value = {
    for name, database in upstash_redis_database.queues :
    name => "rediss://default:${database.password}@${database.endpoint}:${database.port}"
  }
}

output "redis_endpoints" {
  description = "Map of environment -> host, without the credential. Safe to log."
  value = {
    for name, database in upstash_redis_database.queues :
    name => database.endpoint
  }
}

output "redis_database_ids" {
  description = <<-EOT
    Map of environment -> Upstash database id.

    Not the endpoint. The endpoint is a hostname and the delete API takes an id,
    so a teardown holding only endpoints cannot remove anything -- which is
    exactly what happened: the inventory read an output that was never exported,
    found nothing, and reported a complete teardown while four databases stayed
    alive and billing.

    Not sensitive. An id addresses a database and does not open one; the URL
    above is the credential.
  EOT
  value = {
    for name, database in upstash_redis_database.queues :
    name => database.database_id
  }
}
