# ADR 0006 — Backup Strategy

**Status.** Proposed, 2026-09-16. **Not accepted, and nothing is built.** Three
questions in the Decision section are open and are named as open; this record
exists so that the settled parts are settled before code rather than during it.

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
  a destination and nothing provisions one.
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
6. *Restore is destructive and reuses the approval machinery that exists.* The
   AI foundation's action state machine, its destructive-operation class, and
   its rule that an approver must be someone who could have performed the action
   themselves. Non-overwriting by default; overwriting is separately approved.
7. *Restore refuses while the entitlement plan is unresolved.* Upload takes the
   opposite rule and continues. The asymmetry is deliberate: an outage must not
   lock a customer out of their own work, and must not let unverified data move.
8. *Disaster recovery is out of scope and needs its own record.* RPO, RTO,
   failover and cross-region replication are estate-level commitments to
   customers, not a product template's decisions.
9. *No RPO or RTO is stated here.* A daily copy implies a recovery point no
   better than 24 hours, and that is a consequence of the design rather than a
   target it was built to. Writing plausible numbers into a design document is
   how a number nobody agreed to becomes a number everyone cites.

**Open, and blocking.**

| # | Question | Leaning |
|---|----------|---------|
| 1 | Who creates the archive and backup buckets — a Terraform module, or a documented manual step | A manual step first, matching how `STORAGE_BUCKET` already works. Adding a Terraform output named for buckets also fails `tests/docs/identifiers.test.ts` until its exemption is removed in the same commit |
| 2 | Same-provider only, or cross-provider from the start | Same-provider first. Cross-provider when an estate asks and accepts the bill |
| 3 | Which entitlement gates restore | Propose `storage.restore`; adding it is Control Plane catalogue work, governed by the open F3/F2b authorization question |

**Consequences.** Nothing can be built until question 1 is answered, and
stories STORAGE-009 through STORAGE-013 are blocked on it rather than merely
unstarted. The integrity work that would otherwise look premature is the
prerequisite that makes this design possible at all. Accepting decision 1 means
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
