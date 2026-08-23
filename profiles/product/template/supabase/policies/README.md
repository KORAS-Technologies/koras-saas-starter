# supabase/policies

**Empty by design.** Row-level security policies live in `supabase/migrations/`,
not here.

`local/scripts/migrate.sh` used to apply every migration and then every file in
this directory. A policy defined in both places was therefore applied twice,
with this directory winning:

```text
00001 .. 000NN   create the corrected policies
policies/*.sql   recreate the older ones on top
```

On an existing database that is invisible, because the directory had already
been applied before any corrective migration ran. Only a clean bootstrap
inverts the order -- which is the case least likely to be noticed and the one
that becomes production. The Control Plane hit exactly this and it restored a
cross-organization read (its R-05).

The second reason is versioning. A policy is part of the schema and part of its
security surface. Holding policies in a file that is re-applied in place gives
no ordering, no history, and no way to know which policies a given database
actually has.

**To change a policy, add a migration that drops and recreates it.**

## Where this product's policies are

`00002_rls_policies.sql`. RLS is enabled on each table by `00001`, and a table
with RLS enabled and no policy denies every role that cannot bypass it, so the
starting position is closed and each policy opens exactly one path.
