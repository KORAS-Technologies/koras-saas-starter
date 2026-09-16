# Koras Storage Architecture

> What a generated product does with a customer's files: where the bytes go,
> what the database knows about them, who may reach them, and what the platform
> can prove about them afterwards.
>
> The decision record is `docs/adr/0003-koras-storage-audit-governance.md`.
> The audit half is `docs/AUDIT_ARCHITECTURE.md`; retention and holds are
> `docs/RETENTION_POLICY.md`; backup and restore are `docs/BACKUP_AND_RESTORE.md`.

## Purpose

Every KORAS product stores something a customer would be upset to lose and
angry to have leaked. The starter therefore owns the whole path — the provider
seam, the key layout, the index, the authorization, the audit trail and the
sweeps — so that a product adds a page and never rebuilds any of it.

Two properties govern the design, and most of what follows is a consequence of
one of them:

1. **No byte passes through the product.** The API mints a signed URL and the
   browser talks to the bucket. The credential never leaves the API process.
2. **The key is never the authorization.** What an object key spells has no
   bearing on who may read it. Access is a policy decision in Postgres plus a
   short-lived signature.

## What existed before

The Files module shipped on 2026-09-08 with the provider seam, the index, the
quota and the signed-URL dance. What it did not have, until 2026-09-15, was
anything that could be called governance: no digest was recorded anywhere in
the repository, so no copy of an object could be compared with the original;
the file routes emitted no audit events at all, so the one module that stored
customer data was the one module whose operations left no trace; and two
comments in migration `00005_files.sql` promised a reconciliation sweep that
could not be written, because the provider protocol had no way to ask a bucket
what it holds.

## The provider seam

`python-packages/koras-storage` is the only place a bucket is spoken to. One
S3-compatible client serves four endpoints, because Supabase Storage,
Cloudflare R2, AWS S3 and the local MinIO all speak that protocol and one
client with four endpoints is a smaller surface than four clients.

`ObjectStore` is the protocol, and it is deliberately small:

| Operation | What it is for |
|-----------|----------------|
| `presign_upload` | A signed PUT the browser performs itself |
| `presign_download` | A signed GET, always with an attachment disposition |
| `head` | The object's size, or nothing — the confirmation check |
| `put` | Bytes the API already holds, such as a report export |
| `delete` | One object |
| `list` | What is actually under a prefix, paged |
| `copy` | One object, optionally into another destination |
| `checksum` | The provider's own digest, where it will give a comparable one |

The last three arrived on 2026-09-15, each with a default so that no existing
implementation broke. There is deliberately **no `move`**: copy and delete at
the call site is two events in the audit trail and one visible failure in
between, where a move is one event that either happened or silently half
happened.

Archiving and restoring are **not** provider operations. No provider this
estate uses offers storage tiers, so they are transitions this layer performs
as copies; see `docs/RETENTION_POLICY.md`.

### Which provider serves a customer

The Control Plane's storage policy decides, read by the API through the portal
route with the customer's own token and cached for a minute. No policy means
the platform default — the product's own Supabase bucket, which is exactly what
the platform answers for a customer nobody has decided anything for.

A policy naming Cloudflare R2 or AWS S3 is served through the same client with
that provider's key pair from Doppler. A policy naming `azure-blob` or
`customer-owned` is refused with 503 and a reason, never quietly written to the
default: the first needs a credential nothing in the estate holds, and the
second is not S3-compatible. That refusal is the correct behaviour and remains
so as of 2026-09-16.

## The object key

```
tenants/<tenant>/<category>/<file>/<name>
```

The tenant is the security boundary and the category is what the object is
for. **Nothing else is in the key**, and the omissions are the design:

| Not in the key | Why |
|----------------|-----|
| environment | Each environment is already a separate project with its own bucket. The isolation is physical and stronger than a prefix. |
| organization | A mutable fact. Freezing it into an immutable key means a tenant that changes organization needs every object copied. |
| product | A deployment is one product. A constant segment carries no information. |
| year/month/day | Date prefixes exist to make listing by range cheap, and nothing lists by prefix. The database answers every date question faster, from an index. |

Those facts are columns instead. The category segment arrived on 2026-09-15;
keys written before it have no such segment and are **not rewritten**, because
`files.storage_key` stores what was signed and rewriting it would unpick every
row that holds one.

`safe_filename` strips path separators, control characters and anything outside
a small ASCII set, and caps the result at 180 characters. It is applied to both
the key and the `Content-Disposition` header. The original name stays in the row
for display.

## The index

`public.files`, created by `00005_files.sql` and extended by
`00011_files_index_state.sql` and `00018_files_governance.sql`. The bytes are
never here. A row and an object are created in that order and deleted in the
reverse, so a row without an object is a pending upload that never finished and
an object without a row is a leak the reconciliation sweep can find.

What 00018 added, and why each column exists:

| Column | The question it answers |
|--------|-------------------------|
| `organization_id` | Which organization the tenant belonged to when the object was stored |
| `category` | What the object is for; the key's own segment |
| `checksum_sha256` | What digest was claimed for these bytes |
| `checksum_verified_at` | Whether anyone but the client vouched for it |
| `classification` | How sensitive the object is |
| `retention_policy`, `retain_until` | Which rule applies, and until when |
| `legal_hold` | Whether anything forbids removing it |
| `scan_status`, `scan_note` | What a scanner concluded, and a sentence for a person |
| `archived_at` | When it was copied to the archive destination |
| `backup_status`, `backed_up_at` | Whether a verified copy exists |
| `entity_type`, `entity_id` | What the file is attached to, where a product attaches files to its own records |
| `workspace_id`, `version` | Reserved and inert as of 2026-09-16 |

Two decisions inside that table are worth stating plainly.

**There is no soft delete.** This schema has carried no deleted-at column since
it was written. Deletion is a lifecycle state plus a retention date, which
answers the same question with one idiom instead of two.

**Integrity is two columns, never one.** A digest a browser asserted is
evidence; a digest a provider corroborated is proof. Keeping them apart means
no reader ever has to guess which of the two they are holding. A single column
would make a claim look like a measurement.

## Upload

1. `POST /files/uploads` checks the entitlement and the quota, inserts a
   `pending` row, and mints a signed PUT. `ContentType` and `ContentLength` are
   part of the signature, so the browser cannot substitute a different type.
2. The browser hashes the file with `crypto.subtle`, then PUTs the bytes to the
   bucket itself.
3. `POST /files/{id}/complete` carries the digest. The API calls `head`, refuses
   a size that does not match, re-checks the quota, records the digest, marks
   the row ready, and hands the file to every registered hook.

The digest is optional and its absence is not an error. `crypto.subtle` needs a
secure context and reads the whole file into memory, so a failure to hash is not
a failure to upload — the digest is corroborating evidence, and refusing a file
because a hash could not be taken would trade a real capability for a
theoretical one.

**The quota is checked twice**, at ticket and at confirmation. It was checked
once until 2026-09-15, and two tickets taken out together were each inside the
limit and jointly over it.

## Download

A signed GET with an attachment disposition, five minutes long, refused before
it is signed when the file is withheld. A file a customer uploaded is not a page
this product vouches for, so it is downloaded and never rendered in the tab.

The product never sees the transfer: the browser fetches from the bucket. A
ticket issued is therefore the last thing this side can honestly claim to know,
and the audit record says exactly that.

## Scanning and quarantine

`services/api/koras_api/core/file_scan.py` is the seam. **No scanner is
integrated, and that is deliberate as of 2026-09-16**: which scanner a product
uses is a product's decision and often a customer's contractual one. What the
starter owes every product is somewhere to put the answer, a state the rest of
the system already respects, and a refusal that happens on the server.

A scanner registers as a file hook, reads the object through the signed URL it
is handed after an upload, and calls `record_scan`. An infected file moves to
`quarantined` in the same statement as its scan result, so there is no moment at
which a file is known to be infected and still listed as ready. The object is
not deleted: a customer may need it recovered, and destroying evidence of an
incident is rarely what an incident needs.

Only `infected` is withheld. Refusing `pending` would break every product that
has no scanner, and a control that breaks the feature it protects is a control
that gets switched off.

## The hook registry

`core/file_hooks.py` was one mutable record with three fields until
2026-09-15, which admitted exactly one consumer: the assistant's indexer took
the slot at startup, and a scanner arriving second would have replaced it rather
than joined it, silently and at import order.

It is a registry now, in the shape `koras-reporting` uses. A duplicate name is
refused where that is a traceback; iteration is ordered by name so two runs of
one build do the same thing in the same order; and a hook that throws after an
upload is logged and isolated, because the response has already been sent and
one hook failing must not stop the next.

## Reconciliation

`services/worker/koras_worker/tasks/storage_reconcile.py`, nightly, and **off
unless `STORAGE_RECONCILE_ENABLED` asks for it**.

It reports and deletes nothing. An object it cannot match to a row is not proof
of a leak: a listing that failed part way looks exactly like a prefix with fewer
objects in it, and acting on that difference deletes a customer's file. A
partial listing therefore reports no orphans at all.

What it can and cannot see is a real boundary rather than an oversight. The
worker holds the platform's own credentials and nothing else — a customer's
storage policy is read by the API with that customer's token, and the worker has
no token and no machine identity toward the platform. So it reconciles the
platform's default bucket, and a ready row whose object it cannot see is counted
**unverifiable** rather than reported as missing. That is the difference between
an alert and a false alarm.

## Authorization

Four checks, and all four are expected:

| Where | What it decides |
|-------|-----------------|
| Navigation registry | Whether the module appears, and locked or hidden |
| Middleware | Whether the URL may be reached at all |
| Page render | Whether the surface is drawn |
| **API route** | The actual boundary |

Permissions are `files.read`, `files.upload` and `files.manage`, the last being
deletion and owner-or-administrator only. Row-level security is forced on
`files`, so the API's own checks and the database's are two independent layers
rather than one written twice.

## Entitlements and quota

`storage.files` is the entitlement, granted from Starter upward with a per-plan
ceiling in gigabytes. The API refuses an upload over the ceiling with 402 and
names the plan; the sidebar locks and the page says so.

**An unreachable platform is no gate rather than a closed one** — the same
decision the Analytics page makes, and the opposite of the rule export and
restore follow. A customer whose plan cannot be read keeps storing files; a
customer whose plan cannot be read does not get to export or restore. The
asymmetry is deliberate: an outage should not lock a customer out of their own
work, and it should not let data leave the product unverified either.

## Observability

Every storage operation records an audit event; see `docs/AUDIT_ARCHITECTURE.md`
for the classes and what is kept how long. Beyond that, storage uses the
starter's tracing: spans through the API, structured logs on the worker sweeps.

There is **no metric API in this repository as of 2026-09-16** — observability
is tracing-only, and a counter convention would be new framework rather than new
usage. Byte counts and object counts are therefore answered by queries against
the index rather than by gauges.

## Testing

| Layer | Where |
|-------|-------|
| Provider seam, key layout, digests | `python-packages/koras-storage/tests/test_storage.py` |
| Hook registry | `tests/unit/test_file_hooks.py` |
| Audit of storage operations | `tests/unit/test_storage_audit.py` |
| Reconciliation | `tests/unit/test_storage_reconcile.py` |
| Tenant isolation of the index | `supabase/tests/050_files_isolation.sql` |
| Tenant isolation of the governance columns | `supabase/tests/170_files_governance_isolation.sql` |
| Browser path | `e2e/files.spec.ts` |

The isolation tests run as a restricted role with no bypass, against a real
Postgres, in every Generator Integration row. Seeding as the owner proves
nothing, which is the lesson R-032 left behind.

**What is not covered, as of 2026-09-16:** no real upload happens in CI —
Generator Integration has Postgres and no bucket — so the upload itself is proven
against MinIO locally and against dev by hand. `FOLLOW_UPS.md` F22 records this
and the rest of what the Files module deliberately leaves out.
