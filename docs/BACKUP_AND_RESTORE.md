# Koras Backup and Restore

> **Both halves are built as of 2026-09-16.** A nightly copy runs, compares
> digests and catalogues the result, and an object can be brought back from
> that catalogue by two people. Nothing in Terraform creates a bucket for
> either — the destination is a name a person supplies, which is how
> `STORAGE_BUCKET` already works.
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

   **Bounded per object, and since 2026-10-02 per process as well.** One
   64 MiB object copied to another provider and read back was measured at 193
   MiB over an idle worker, in the product's own image, and beside the worst
   accepted import that was the whole of a 512 MiB machine. So a copy that
   can hold an object's bytes, and a restore, are each made inside the
   worker's heavy gate -- `services/worker/koras_worker/heavy.py` -- which an
   import and a scheduled report share: one such section to a process. The
   gate is taken an object at a time, and a restore takes it *before* it
   claims its request, so a restore that waits is still `approved` if the
   sweep is cancelled while it does. GR-352E;
   `docs/features/data-import/worker-resource-envelope.md` has the figures.

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
| verified | Two digests were compared and matched |
| failed | The copy was refused, or the digests disagreed |

### Where the two digests come from

The provider's own, where it gives one -- it costs nothing to ask. Where it does
not, both ends are read and hashed by the worker instead, bounded by
`STREAM_CEILING`.

That fallback is not a refinement. Until 2026-09-17 verification depended
entirely on the provider volunteering a SHA-256, and **Supabase volunteers
none**: its S3 accepts `ChecksumSHA256` on upload, stores nothing, and answers
`None` to `HeadObject` and `GetObject` alike. Confirmed by sending a digest and
asking for it back. Nothing computes one at upload either, so
`files.checksum_sha256` is null for every row in the estate. `verified` was
therefore unreachable in all four environments, on the only provider any of
them is configured with -- a feature described as backup with digest
verification that could never report one.

A digest computed here is the stronger claim in any case. The provider's is a
value it stored and may have computed over something else; this one is of the
bytes this process actually read.

What stays `copied` is what cannot be read within the bound. Past
`STREAM_CEILING` there is nothing to compare, and the row says so rather than
guessing.

### A provider that will not copy

`CopyObject` is refused outright by Supabase's S3 for any key containing a
space, with an empty error code, while `HeadObject` on the same key succeeds. On
the dev estate that was four of six objects -- somebody had uploaded "Homework
Packet Fill-In Updated 2025-04-18.pdf" -- each recorded `failed` night after
night under a run reporting `ok`.

A refused server-side copy now streams through the worker, which is the path
that already existed for cross-provider copies and works on exactly those keys.
An *integrity* refusal is never answered that way: that is the destination
saying the bytes do not match, and writing them by another route is how a
corrupt object becomes a backup.

`backup_status` and `backed_up_at` on the file index carry this per object.
They were added by `00018_files_governance.sql` and written since 2026-09-16.
`failed` leaves `backed_up_at` null: there is no moment at which that object was
backed up, and a date there would read as though there were.

An object the run could not compare stays `copied`, and the catalogue records
*why* in its `note` — which end had no digest. Three outcomes rather than two is
the whole point: "no digest" is the ordinary case, because a provider computes a
SHA-256 only when the upload asked it to.

A cross-provider copy produces the strongest statement of the three, and it is
worth understanding why. The bytes pass through the worker, which hashes what it
read; that digest is then **sent with the write**, so the destination compares
before it stores. A corrupt object is refused at the door rather than
catalogued and compared afterwards, and the destination keeps the digest, which
is what lets the comparison that follows succeed at all.

Two refusals, opposite in meaning, and the code must not confuse them:

| The destination says | What it means | What happens |
|----------------------|---------------|--------------|
| `BadDigest`, `InvalidDigest`, a checksum mismatch | It compared and disagreed | **`failed`.** Never retried without the digest — writing the bytes anyway would turn a caught corruption into a catalogued backup |
| `NotImplemented`, `InvalidRequest`, `BadRequest` | It does not understand the parameter | The write is repeated without the digest. The copy is then one nobody can verify, which `checksum()` reports by answering nothing |
| anything else | A missing bucket, a rejected credential | Raised unchanged. Swallowing it would make a broken destination look like a provider without checksum support |

The first version of the cross-provider path, on 2026-09-16, did not send the
digest with the write. The destination therefore stored no SHA-256, `checksum()`
answered nothing, and **every cross-provider copy would have read `copied` for
ever** — a backup nobody could confirm, produced by the job whose entire purpose
is confirming backups. It was found by asking what would happen on Cloudflare R2
before anything ran there.

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

## Restore

Restore is **destructive** and is designed around that fact rather than around
convenience.

```
requested -> authorized -> queued -> restoring -> verifying -> completed
                   |                                    |
                   +--> refused                         +--> failed
```

It borrows the **rule** from machinery that already exists, and not the
machinery itself. The design said it would reuse the AI foundation's action
state machine; that machine persists to `ai_actions`, which arrives with the
`ai` capability and is off by default, so restore would have been unavailable in
most products because they had not bought an assistant. `legal_holds` faced the
same choice and answered it the same way, so restore has its own table and its
own machine in `core/restore.py`.

The rule is worth restating because it is the good part: **an approver must be
someone who could have performed the action themselves.** An administrator
cannot rubber-stamp an operation they lack the permission for, and the person
who asked cannot be the person who approves.

Four decisions:

1. **Non-overwriting by default.** A restore to a new file id is not
   destructive. Overwriting an existing object is, and is a separately approved
   option rather than a checkbox on the same request.
2. **The plan is not consulted at all**, and no entitlement gates this.
   `files.manage` and the two people are the authority. The design said the
   opposite — that an unresolved plan should refuse, by analogy with export —
   and building it showed the analogy was wrong: the verification that matters
   here is the digest, which the worker checks itself and which a platform
   outage cannot affect. All the rule would have achieved is an unreachable
   Control Plane stopping somebody recovering a deleted file. Gating data
   recovery behind a plan tier is also a worse position to defend than not
   selling it.
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
