# Koras Backup and Restore

> **The backup half is built as of 2026-09-16. Restore is not.** A nightly
> copy runs, compares digests and catalogues the result; nothing restores from
> it yet, and nothing in Terraform creates a bucket for either — the
> destination is a name a person supplies, which is how `STORAGE_BUCKET`
> already works.
>
> The decision record is `docs/adr/0006-backup-strategy.md`, accepted the same
> day. What else exists is in `docs/STORAGE_ARCHITECTURE.md`.

## What runs

`back_up_storage` in `services/worker/koras_worker/tasks/storage_backup.py`,
nightly at 04:39 and after the lifecycle sweep — an object removed tonight
should not be copied tonight. Off unless `STORAGE_BACKUP_ENABLED` asks for it,
because it bills a second destination.

Four things in one pass: copy what has no good copy, compare the digests, date
any copy whose object has gone, and remove any copy past its date.

## Three things blocked this until 2026-09-16, and what answered each

1. **No integrity existed.** A backup that cannot be compared with its source
   is a copy with a reassuring name. Digests arrived on 2026-09-16 — and the
   first version of them could never have matched anything, because
   `checksum()` returned a 32-character entity tag for a column holding 64 hex
   characters. A review found it. Had it shipped, every object would have read
   `copied` and none `verified` while a console reported a working backup.
2. **Terraform creates no buckets at all.** Answered: a documented manual step,
   matching `STORAGE_BUCKET`, which is declared `supplied` in the secrets
   manifest for the same reason. The person who creates the bucket sets
   `STORAGE_BACKUP_BUCKET`, and a destination equal to the source bucket is
   refused outright — a copy beside the original survives a deleted object and
   nothing else.
3. **Cross-provider backup costs money.** Answered by building both and letting
   the configuration decide. The same endpoint is a server-side copy and no
   byte reaches the worker; a different endpoint is a copy no single provider
   can make, so the bytes pass through, bounded at 64 MiB per object. The
   settings already promised both, and a setting accepted while doing nothing
   is the defect this work exists to close.

## The shape

```
Primary bucket
      |
      +--> Daily copy --> same provider, a separate bucket
      |
      +--> Daily copy --> a second provider, where configured
                |
                +--> Digest comparison --> verified | failed
```

A run walks the file index rather than the bucket: the index is the thing that
knows which objects are supposed to exist, and a backup driven by a listing
would faithfully copy an orphan and miss a row whose object was already gone.

## Copied is not verified

The rule this whole design exists to enforce:

> **A backup is not successful because a copy call returned success.**

A provider acknowledging a copy tells you the request was accepted. It does not
tell you the bytes at the destination are the bytes at the source. So a run
records two distinct states, and only one of them is a backup:

| State | Meaning |
|-------|---------|
| none | No copy has been attempted for this object |
| copied | The provider accepted the copy. Nothing has been compared |
| verified | The destination digest matched the recorded source digest |
| failed | The copy was refused, or the digests disagreed |

`backup_status` and `backed_up_at` on the file index carry this per object.
They were added by `00018_files_governance.sql` and written since 2026-09-16.
`failed` leaves `backed_up_at` null: there is no moment at which that object was
backed up, and a date there would read as though there were.

An object the run could not compare stays `copied`, and the catalogue records
*why* in its `note` — which end had no digest. Three outcomes rather than two is
the whole point: "no digest" is the ordinary case, because a provider computes a
SHA-256 only when the upload asked it to.

A cross-provider copy produces a stronger statement than either provider's. The
bytes pass through the worker, so the digest compared is of what this process
actually read from the source and actually wrote to the destination.

A digest that cannot be compared — a multipart object's entity tag is a digest
of digests — is **not** a mismatch. The provider seam already answers "no
comparable digest" rather than a wrong one, precisely so that a large object is
never reported as corrupt.

## What a run must record

`public.file_backups`, from migration `00025_file_backups.sql`: one row per
object per destination, holding both digests the comparison was made from, the
status, a note, and the dates. A run also records one `storage.backup.run`
audit event per tenant whose objects it touched, carrying counts and nothing
else — an object key is half a signed URL and is never a detail.

**The catalogue outlives the object it describes.** `file_id` is deliberately
not a foreign key: a catalogue row deleted alongside the object would be
insurance that expires the instant the accident happens. A copy of a live object is
kept as long as the object; a copy whose object is gone is dated, and goes
`STORAGE_BACKUP_RETENTION_DAYS` later — thirty days when unset.

**The copy keeps the source key.** Objects here are immutable, so a mirror is a
complete backup of current state and a restore will not need a catalogue lookup
to find the bytes. Dated copies would guard against an overwrite this product
cannot perform, at the cost of multiplying every object.

A tenant reads its own catalogue and writes none of it. Every row is a sweep's:
a tenant that could insert one could claim a backup exists that does not, which
is worse than having no catalogue at all.
`supabase/tests/240_file_backups_isolation.sql` proves both, and the mutation
that makes `file_id` a cascading foreign key kills it.

Two properties matter more than the columns:

- **Always record the run**, success or failure. The scheduled-report delivery
  already works this way and the reasoning transfers exactly: one bad night must
  not stop the job for good, and must not make it repeat every hour either.
- **A partial run is marked partial**, never completed. The reconciliation sweep
  makes the same distinction, for the same reason.

## Retries and failure

| Failure | Response |
|---------|----------|
| Destination provider unavailable | Retry with backoff; the run is failed, not partial, if it never succeeds |
| One object refused | Record it, continue with the rest; a single bad object is not a reason to abandon the night |
| Digest mismatch | Mark failed, alert, retry once. A second mismatch is an incident |
| Source object missing | Not a backup failure. That is reconciliation's finding, and it is reported there |
| Credentials rejected | Stop the run. Continuing would fill a log with noise and produce nothing |

## Restore — designed, not built

Restore is **destructive** and is designed around that fact rather than around
convenience.

```
requested -> authorized -> queued -> restoring -> verifying -> completed
                   |                                    |
                   +--> refused                         +--> failed
```

It reuses machinery that already exists rather than inventing a second approval
flow: the AI foundation's action state machine, its destructive-operation class,
and its approval rule. That rule is worth restating because it is the good part:
**an approver must be someone who could have performed the action themselves.**
An administrator cannot rubber-stamp an operation they lack the permission for.

Four decisions:

1. **Non-overwriting by default.** A restore to a new file id is not
   destructive. Overwriting an existing object is, and is a separately approved
   option rather than a checkbox on the same request.
2. **An unresolved plan refuses.** Storage takes the opposite rule — an
   unreachable platform is no gate, so a customer keeps working during an
   outage. Restore takes the export rule: a closed gate. The asymmetry is
   deliberate. An outage must not lock a customer out of their own work, and it
   must not let unverified data move either.
3. **Every transition is audited**, including a refused authorization. A denied
   approval is exactly the record somebody asks for later.
4. **Cross-tenant restore must be proven impossible**, by an isolation test
   running as the restricted role, not by reading the code.

### Scopes

One object, one version, a logical collection, a tenant, or a whole snapshot.
The wider the scope the more it looks like an incident response rather than a
user action, and tenant and snapshot scope are operator work with a runbook
rather than a button in the product.

## Disaster recovery

**Out of scope**, decided 2026-09-15. Backup and restore are a product
capability; disaster recovery is an estate-level decision about recovery point
and recovery time objectives, failover and cross-region replication, and it does
not belong inside a product template. It needs its own ADR.

## Open decisions

| # | Decision | Blocks |
|---|----------|--------|
| 1 | Who creates the archive and backup buckets — Terraform module or documented manual step | Everything here |
| 2 | Same-provider only, or cross-provider from the start | The credential and the bill |
| 3 | Which entitlement gates restore, and its code in the platform catalogue | The gate |

Decision 1 has a recommendation: a documented manual step for the first pass,
matching how `STORAGE_BUCKET` already works. Adding a Terraform output named for
buckets also has a cost worth knowing — `tests/docs/identifiers.test.ts` asserts
that identifier is absent, so the exemption must be removed in the same commit
or the documentation suite fails.
