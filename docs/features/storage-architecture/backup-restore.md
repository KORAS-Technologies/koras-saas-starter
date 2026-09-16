# SAG-F1 — Backup and restore

> **None of this is built.** The design, the reasoning and the open decisions
> are `docs/BACKUP_AND_RESTORE.md`, which is the authoritative document and is
> not duplicated here. This file carries only what is feature-scoped: which
> stories cover it, what blocks them, and the one property that must not be
> negotiated away. Status 2026-09-16.

## The shape

```
Primary storage
       |
       +---- Daily copy
                  |
            Verification
                  |
          +-------+-------+
          |               |
   Same provider    Second provider
```

## The rule

> **A copy is not a valid backup until integrity verification succeeds.**

A provider acknowledging a copy tells you the request was accepted. It does not
tell you the bytes at the destination are the bytes at the source. So the state
a run records is one of four, and only one of them is a backup:

| State | Meaning |
|-------|---------|
| `none` | Nothing attempted |
| `copied` | The provider accepted it. Nothing has been compared |
| `verified` | The destination digest matched the recorded source digest |
| `failed` | Refused, or the digests disagreed |

`backup_status` and `backed_up_at` exist on the file index from
`00018_files_governance.sql`, and nothing writes them.

An object with no comparable provider digest — a multipart entity tag is a
digest of digests — is recorded `copied`, never `verified` and never `failed`.
Reporting it as failed would call every large object corrupt.

## Stories

| Story | Title | Status | Blocked on |
|-------|-------|--------|-----------|
| STORAGE-009 | Daily backup | Blocked | who creates the bucket |
| STORAGE-010 | Cross-provider backup | Blocked | STORAGE-009, a second credential, a second bill |
| STORAGE-011 | Backup integrity verification | Blocked | STORAGE-009 |
| STORAGE-012 | Object restore | Blocked | STORAGE-011 |
| STORAGE-013 | Snapshot restore | Blocked | STORAGE-012 |

Acceptance criteria are in `acceptance-criteria.md`; they are constraints on
unwritten work rather than descriptions of behaviour.

## Why the prerequisite came first

Digests (STORAGE-017) were not in the original story list and were built before
any of the five above, because without them a backup can only be attempted and
never verified — and a backup that cannot be verified is a copy with a
reassuring name. That ordering was deliberate.

## RPO and RTO

**Not defined, and deliberately not invented here.** A recovery point objective
is a commitment to a customer about how much work they may lose, and a recovery
time objective is a commitment about how long they will wait. Neither is an
engineering choice, and writing plausible numbers into a design document is how
a number nobody agreed to becomes a number everyone cites.

A daily copy implies an RPO no better than 24 hours, which is a *consequence* of
the design rather than a target it was built to. Anyone setting real objectives
should read `docs/BACKUP_AND_RESTORE.md`'s disaster-recovery section first: DR
is out of scope for this feature and needs its own decision record.

## Restore, in one paragraph

Restore is destructive and reuses the AI foundation's approval machinery rather
than inventing a second one: the action state machine, the destructive-operation
class, and the rule that an approver must be someone who could have performed
the action themselves. Non-overwriting by default. An unresolved entitlement plan
refuses, unlike upload — an outage must not lock a customer out of their own
work and must not let unverified data move either. Every transition is audited,
including a refused authorization, because a denied approval is exactly the
record somebody asks for later.

## Open decisions

| # | Decision | Recommendation |
|---|----------|----------------|
| 1 | Who creates the archive and backup buckets | A documented manual step first, matching how `STORAGE_BUCKET` already works |
| 2 | Same-provider only, or cross-provider from the start | Same-provider first; cross-provider when an estate asks and accepts the bill |
| 3 | Which entitlement gates restore | Propose `storage.restore`; needs Control Plane catalogue work this task must not do |

Decision 1 carries a trap worth knowing before anyone reaches for Terraform:
`tests/docs/identifiers.test.ts` asserts that a buckets-named output is absent
from the codebase, so adding one fails the documentation suite until the
exemption is removed in the same commit.
