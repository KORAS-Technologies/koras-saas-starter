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

## Before writing the first one

RLS is enabled on every table by `00001`, and a table with RLS enabled and no
policy denies all access to any role that cannot bypass it. That is the correct
starting position here: the Control Plane holds every customer organization,
subscription and entitlement on the platform, so a policy that is too permissive
costs far more than one that is missing.

The policies this profile once shipped were written against Supabase Auth:

```sql
create policy "subscriptions_select_own_org"
  on public.subscriptions for select
  using (auth.role() = 'authenticated');
```

Two things were wrong with that. It applied no organization scoping at all, so
any authenticated user could read every subscription on the platform. And it
could never have worked as intended anyway: the Control Plane authenticates
through ZITADEL, so no Supabase JWT is ever presented and `auth.role()` is
always NULL. Some of those policies denied by accident and one leaked, with
nothing to distinguish the two. A companion policy naming `service_role` was
dead code besides -- that role carries BYPASSRLS, so a policy attached to it is
never evaluated.

Decide first what identifies a caller. Because identity comes from ZITADEL
rather than Supabase Auth, the API must declare it -- typically as
transaction-scoped settings read by helper functions, with requests running as a
role that cannot bypass RLS.

Write the isolation tests before the policies. A policy suite that has never
been observed to fail has not been tested.
