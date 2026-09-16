# ADR 0006 — Backup Strategy

**Status.** Accepted, 2026-09-16. All three questions are answered and both
halves are built: the copy and its verification in
`services/worker/koras_worker/tasks/storage_backup.py` with migration
`00025_file_backups.sql`, and restore in `routers/restore.py`,
`core/restore.py`, `tasks/storage_restore.py` and `00026_restore_requests.sql`.
Two decisions in this record were amended on building it; both amendments are
marked below.

**Context.** No object in this estate is backed up. Objects live in whichever
bucket a customer's storage policy names, and the only copy is the one the
customer uploaded. A provider incident, a mistaken deletion or a bad migration
would be unrecoverable.

Three things blocked designing it, and one has since cleared:

- **Integrity did not exist.** A backup that cannot be compared with its source
  is a copy with a reassuring name. Digests arrived on 2026-09-16, which is why
  they were built before anything that depends on them.
- **Terraform creates no buckets.** A repository-wide search of
  `infrastructure/` finds one match for the word and it is prose.
  `STORAGE_BUCKET` is declared `supplied` for exactly that reason. A backup needs
  a destination and nothing provisions one. Answered 2026-09-16: a documented
  manual step, matching how `STORAGE_BUCKET` already works.
- **Cross-provider backup costs money.** A second provider's bill and a second
  credential, and no estate has been asked.

**Decision.**

1. *A copy is not a backup until its integrity is verified.* A provider
   acknowledging a copy tells you the request was accepted, not that the bytes
   match. A run records `none`, `copied`, `verified` or `failed`, and only
   `verified` is a backup. This is the decision the rest of the design exists to
   serve.
2. *An object with no comparable provider digest is `copied`, never `failed`.* A
   multipart entity tag is a digest of digests. Calling that a mismatch would
   report every large object as corrupt and train operators to ignore the alert.
3. *A run walks the index, not the bucket.* The index knows which objects are
   supposed to exist. A backup driven by a listing would faithfully copy an
   orphan and miss a row whose object was already gone.
4. *Every run is recorded, whatever its outcome.* Success, failure and partial
   alike. The scheduled-report delivery already works this way and the reasoning
   transfers: one bad night must neither stop the job for good nor repeat it
   every hour.
5. *A partial run is never recorded as complete.* The same rule the
   reconciliation sweep follows, for the same reason: a count derived from an
   unfinished pass, presented as a total, is worse than no count.
6. *Restore is destructive and borrows the approval rule, not the machinery.*
   **Amended 2026-09-16 on building it.** This said restore would reuse the AI
   foundation's action state machine. It cannot: `ai_actions` arrives with the
   `ai` capability, which is off by default, so a storage safety operation would
   have been unavailable in most products because they had not bought an
   assistant. `legal_holds` faced the same choice in `00020` and answered it the
   same way — its own table, its own machine, the same rule. Restore does that,
   in `restore_requests`.

   The rule is unchanged and is the good part: an approver is somebody other
   than the requester. Non-overwriting by default, and overwriting is asked for
   *twice* — named on the request and confirmed again on the approval, because
   an approver who did not notice a checkbox has not approved a deletion.
7. *Restore does not consult the plan at all.* **Amended 2026-09-16.** This
   said restore refuses while the entitlement plan is unresolved, drawing an
   asymmetry with upload on the grounds that an outage must not let unverified
   data move. The verification that matters turned out to be the digest, which
   the restore checks itself and which a platform outage cannot affect — so the
   rule as written would only have meant an unreachable Control Plane stopping
   a customer from recovering a deleted file, which is the failure mode the
   reasoning was trying to avoid, pointed the other way.
8. *Disaster recovery is out of scope and needs its own record.* RPO, RTO,
   failover and cross-region replication are estate-level commitments to
   customers, not a product template's decisions.
9. *The catalogue outlives the object it describes.* Added 2026-09-16 on
   building it. `file_backups` holds `file_id` deliberately without a foreign
   key, because a catalogue row deleted alongside the object would be insurance
   that expires at the moment of the accident. A copy of a live object is kept
   as long as the object; a copy whose object is gone is dated, and goes
   `STORAGE_BACKUP_RETENTION_DAYS` later.
10. *The copy keeps the source key.* Objects here are immutable — a key carries
   the file's id and nothing overwrites one — so a mirror is a complete backup
   of current state and a restore does not need a catalogue lookup to find the
   bytes. Dated copies would guard against an overwrite this product cannot
   perform, at the cost of multiplying every object.
11. *No RPO or RTO is stated here.* A daily copy implies a recovery point no
   better than 24 hours, and that is a consequence of the design rather than a
   target it was built to. Writing plausible numbers into a design document is
   how a number nobody agreed to becomes a number everyone cites.

**Open, and blocking.**

| # | Question | Answer |
|---|----------|--------|
| 1 | Who creates the archive and backup buckets | **Answered 2026-09-16: a documented manual step**, matching how `STORAGE_BUCKET` already works. A person creates the bucket and sets `STORAGE_BACKUP_BUCKET`; nothing in Terraform is named for a bucket, so the identifiers test needs no exemption |
| 2 | Same-provider only, or cross-provider from the start | **Answered 2026-09-16: both, because the settings already promised both.** Same endpoint and the provider copies server-side; a different endpoint and no single provider reaches both ends, so the object passes through the worker, bounded at 64 MiB. A setting accepted and doing nothing is the defect this work exists to close |
| 3 | Which entitlement gates restore | **Answered 2026-09-16: none.** `files.manage` and the two-person rule, following the audit-export precedent. Gating data recovery behind a plan tier means a customer whose plan lapsed cannot get their data back, which is a worse position to defend than not selling it. `storage.restore` can be added later — adding a gate to something that works is easy in a way that removing one from something that refuses is not |

**Consequences.** STORAGE-009 and STORAGE-011 are built as of 2026-09-16;
STORAGE-012 and STORAGE-013 — restore, and its approval flow — are not, and are
blocked on question 3 rather than on a bucket. The integrity work that would
otherwise look premature is the prerequisite that made this possible at all: a
digest that could never match, which is what `checksum()` returned until a
review found it, would have made every object `copied` and none `verified`
while the console reported a working backup. Accepting decision 1 means
a console cannot show "backed up" for an object that was only copied, which will
make the first honest backup report look worse than a dishonest one would — and
that is the point of writing it down before anyone is disappointed by it.

**Why there is no separate ADR for the audit-storage and audit-retention
strategies.** Both were proposed alongside this one. ADR 0003 already records
them: decisions 2 and 3 place the audit table in the foundation and put storage
operations in it, decision 13 draws the line between an audit record and a log
line, and decisions 10 and 11 set retention precedence and the lifecycle tiers.
A second record of a decision already recorded is how two descriptions of one
problem come to disagree, which `FOLLOW_UPS.md` warns about in its own preamble.
The detail lives in `docs/AUDIT_ARCHITECTURE.md` and `docs/RETENTION_POLICY.md`.
