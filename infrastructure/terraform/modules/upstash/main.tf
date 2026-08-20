# Redis for the job queue, one database per environment.
#
# Upstash rather than a self-managed Redis: the queue is the only stateful
# component the platform runs itself, and running it properly means replication,
# failover and backups for something that holds at most a few hundred jobs.
#
# One database per environment, never one shared with a key prefix. A prefix is
# a convention, and invariant 6 -- a dev process may not touch a prod resource
# -- cannot rest on a convention. Separate databases mean separate credentials,
# so a dev worker holding a prod queue URL is a configuration error someone made
# rather than an accident waiting in a shared namespace.

resource "upstash_redis_database" "queues" {
  for_each = var.environments

  database_name = "${var.project_slug}-${each.key}"

  # `region = "global"` is the only shape Upstash still accepts: creating a
  # single-region database now fails with
  # `400 "regional db creation is deprecated"`. A global database with one
  # primary and no read replicas is the regional equivalent -- the provider
  # documents `primary_region` as working only when region is "global", so the
  # two must change together.
  region         = "global"
  primary_region = var.region
  read_regions   = []

  tls = true

  # See variables.tf: an evicted key is a lost job.
  eviction = var.eviction

  lifecycle {
    prevent_destroy = true
  }
}
