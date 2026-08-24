---
name: koras-supabase
description: Koras Supabase guidance for Koras applications.
---

# Koras Supabase

Use this skill for Supabase/Postgres schema changes, RLS, generated types, storage, and database access patterns.

## Database Change Checklist

For every new or changed table/column consider:

- migration
- nullability/defaults
- primary/foreign keys
- unique constraints
- indexes
- tenant ownership
- RLS/policies
- created/updated timestamps
- audit fields where required
- generated TypeScript types
- seed/test data impact

## RLS

Do not disable RLS merely to make a query work. Fix the policy, trusted server path, or authorization model.

Review SELECT, INSERT, UPDATE, and DELETE separately. A correct read policy does not imply safe writes.

## Service Role

Service-role credentials are privileged server-only secrets. Never expose them in browser bundles or `NEXT_PUBLIC_*` variables.

## Query Performance

Add indexes for actual access patterns, especially tenant-scoped filters and common foreign-key joins. Avoid speculative indexing without a query need.

## Migrations

- Make migrations deterministic and reviewable.
- Avoid destructive changes without an explicit migration/backfill strategy.
- Preserve production data unless the task explicitly allows destructive behavior.
- Include reversible/down guidance if the repository's migration system supports it.

## Storage

For tenant-scoped files, review:

- path strategy
- object-level authorization
- signed URL lifetime
- MIME/type validation
- file size limits
- malware/content scanning strategy if required
- deletion/retention behavior

Do not treat folder names as sufficient access control.
