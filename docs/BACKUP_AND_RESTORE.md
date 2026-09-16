# Koras Backup and Restore

> **Nothing in this document is built.** As of 2026-09-16 no backup runs, no
> restore exists, and no Terraform module creates a bucket for either. This is
> the design and the reasoning, written so that the decisions are settled before
> the code rather than discovered during it.
>
> The decision record is `docs/adr/0003-koras-storage-audit-governance.md`.
> What does exist is in `docs/STORAGE_ARCHITECTURE.md`.

## Why this was still a document on 2026-09-16, and not yet code

Three things were true on 2026-09-16 and each of them blocks building:

1. **No integrity existed until recently.** A backup that cannot be compared
   with its source is a copy, not a backup. Digests arrived on 2026-09-16; they
   are the prerequisite, and they are now in place.
2. **Terraform creates no buckets at all.** A repository-wide search of
   `infrastructure/` finds one match for the word, and it is prose. The
   product's own bucket is a name a project supplies, not a resource the estate
   provisions — `STORAGE_BUCKET` is declared `supplied` in the secrets manifest
   for exactly that reason. A backup destination therefore needs either a new
   Terraform module or a documented manual step, and that is an open decision.
3. **The estate has never been asked for the money.** Cross-provider backup
   means a second provider's storage bill and a second credential in Doppler.

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

`backup_status` and `backed_up_at` on the file index carry this per object; they
were added by `00018_files_governance.sql` and nothing writes them yet.

A digest that cannot be compared — a multipart object's entity tag is a digest
of digests — is **not** a mismatch. The provider seam already answers "no
comparable digest" rather than a wrong one, precisely so that a large object is
never reported as corrupt.

## What a run must record

A catalogue table, which does not exist on 2026-09-16, holding per run: when
it started and finished, its scope, how many objects were considered, copied,
verified and failed, how many bytes moved, and the first error where there was
one.

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
