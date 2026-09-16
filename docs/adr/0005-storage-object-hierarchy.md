# ADR 0005 — Storage Object Hierarchy

**Status.** Accepted 2026-09-16. Extends ADR 0003 decision 4 with the rejected
alternatives and the reasoning for each.

**Context.** A proposal for this work described a physical object hierarchy:

```
environment / organization / product / tenant-or-workspace / category / year / month / day
```

That shape is common, and it is common because it reads well. Whether it is
right depends on what the keys are for. In this estate the key is not a lookup
path — the database is — and it is not an access control — the policy engine and
the signature are. It is an identifier that is signed, stored in
`files.storage_key`, and immutable in practice because rewriting it would unpick
every row that holds one.

Two keys were already in use by 2026-09-15 and diverging:
`tenants/<tenant>/<file>/<name>` for uploads, and
`tenants/<tenant>/exports/<id>/<file>` spelled by hand in the reporting router.

**Decision.**

1. *The canonical key is* `tenants/<tenant>/<category>/<file>/<safe name>`. The
   tenant is the security boundary; the category is what the object is for;
   everything else is a column.
2. *Environment is not in the key.* Each environment is a separate Supabase
   project with its own endpoint, bucket and credentials. The isolation is
   physical and stronger than a prefix, and a prefix would imply that one bucket
   holds several environments — which would be the thing to fix, not to encode.
3. *Organization is not in the key.* It is a mutable fact. A tenant that moves
   organization would need every object copied to keep the key honest, and a key
   that is not honest is worse than a key that says less. It is a column,
   denormalized at write time.
4. *Product is not in the key.* A deployment is one product and one bucket. A
   segment identical in every key carries no information and costs every key its
   length.
5. *Date is not in the key.* A date prefix exists to make a bucket listing by
   range cheap. Nothing lists by prefix here — the database answers every date
   question from an index, faster — and a date in the key freezes a second
   mutable fact: an object whose recorded date was wrong could not be corrected
   without moving it.
6. *Workspace is not in the key.* The starter has no workspace below a tenant.
   Modelled as a column and inert, so introducing one later is not a migration
   against every object.
7. *The category is a closed set.* `documents`, `exports`, `imports`,
   `attachments`, `generated`, `reports`, `archives`, `temp`. A path segment a
   caller can invent is a path segment a caller can aim somewhere else.
8. *Existing keys are not rewritten.* The category segment arrived on
   2026-09-15 and applies to objects created after it. `files.storage_key`
   stores what was signed.
9. *The key authorizes nothing.* It is minted by the API from verified tenant
   context, and access is a policy decision in Postgres plus a short-lived
   signature. Nothing is readable because of how its key is spelled.

**Consequences.** Keys are short and stable. A tenant that changes organization
needs no data movement. Every question the rejected segments would have answered
is answered by a column, which is where a mutable fact belongs. The export key
went through the one builder rather than being spelled twice, and the bytes did
not change — only the second copy of the layout went. The cost is that a bucket
browsed by hand is less self-describing: an operator looking at
`tenants/<uuid>/documents/<uuid>/invoice.pdf` learns the tenant and nothing
else, and must ask the database for the rest. That is accepted, because the
alternative was a key that lies as soon as a customer reorganizes.
