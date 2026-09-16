# ADR 0003 — Koras Storage & Audit Governance

**Status.** Accepted 2026-09-15.

**Context.** The starter stores objects and records audit events, and does
both without governance. A file is uploaded through a signed URL, confirmed
by a size comparison, indexed in a tenant-scoped table and never checked
again: no digest is recorded anywhere in the repository, so no copy of it
can be verified against the original. Two source comments promise a
reconciliation sweep for objects without rows, and the provider protocol has
no listing operation to write one with. The file routes emit no audit events
at all, so the one module that stores customer data is the one module whose
operations leave no record. The general audit table is real, forced and
insert-only, and it is gated on the `reporting` capability, which means a
product generated without reporting has no audit table. Nothing in the
estate backs an object up, and no Terraform module creates a bucket. Four
capabilities each carry a retention integer of their own and none of them
can be held against deletion.

The pieces to build on are already here: an S3-compatible provider seam over
the three providers that speak the protocol, a tenant context that refuses to
open an undeclared transaction, an entitlement read on the customer's own
token, an audit envelope that refuses to carry a credential-shaped detail,
and an approval state machine for destructive actions that was written for
the assistant and is not specific to it.

**Decision.**

1. *Governance is two capabilities over one foundation.* `storage_governance`
   and `audit_governance` are separate, so audit search and export need not
   wait for a bucket that does not exist. Both are off by default, following
   the `ai` precedent rather than the `reporting` one: a capability whose
   later phases need an external resource stays off until a product asks for
   it.
2. *The audit table is foundation, not a capability.* The table, the sink,
   the envelope and the basic retention sweep move out of the `reporting`
   gate and are generated into every product. A general audit table that an
   unrelated capability can remove is not a place anything else can record.
   The six standard reports stay in `reporting`, which is what that
   capability was always for.
3. *Storage operations are audited in the foundation too.* Upload, download,
   deletion and their refusals record to the same sink, in every product,
   whether or not either governance capability is enabled. A refusal is
   audited as firmly as a success; an operation that leaves no record when
   it fails is the one worth recording.
4. *The object key carries the tenant, the category and nothing else.* The
   canonical shape is `tenants/<tenant>/<category>/<file>/<name>`. An
   environment is already a separate project with its own bucket, a
   deployment is already one product, and an organization is a mutable fact
   that a key would freeze — a tenant that moved organization would need
   every object copied. A date prefix exists to make listing by range cheap
   and nothing lists by prefix; the database answers every date question
   faster, from an index. What a key spells is never what authorizes reading
   it.
5. *The provider seam is extended, not replaced.* Listing, copying and
   reading a digest are added to the existing protocol with defaults, so no
   implementation breaks. Moving is not added: copy and delete at the call
   site keeps the failure visible and records two events instead of one.
   Archiving and restoring are not provider operations; they are transitions
   this layer implements as copies.
6. *Object metadata extends the index that exists.* Integrity,
   classification, retention, hold, scan and backup state become columns on
   the file index rather than a second table describing the same objects. A
   parallel object table would have to be kept in agreement with this one,
   and the agreement is what would fail.
7. *There is no soft delete.* Deletion is a lifecycle state and a retention
   date, matching a schema that has deliberately carried no deleted-at
   column since it was written. The outcome is the same and there is one
   idiom rather than two.
8. *Integrity is recorded and its provenance is recorded with it.* A digest
   supplied by a browser is evidence, and a digest corroborated by the
   provider is proof; the two are stored in separate columns so that no
   reader has to assume which one they hold. A backup is verified when a
   digest matches, and a copy call that returned success is copied rather
   than verified.
9. *A sweep reports before it deletes.* Reconciliation names objects without
   rows and rows without objects and removes neither. A listing that failed
   part-way is not evidence of an orphan, and a sweep that infers one from a
   partial answer deletes a customer's file.
10. *Retention has a floor the tenant cannot lower.* A legal hold outranks a
    regulatory minimum, which outranks the platform floor, which outranks a
    product policy, which outranks a tenant's own. A tenant may lengthen
    retention and may not shorten it. A hold blocks purging, and placing and
    lifting one are themselves audited.
11. *Lifecycle is a Koras model, not a provider feature.* No provider this
    estate uses offers tiering, so a cold state is metadata and an archived
    state is a copy into a separate bucket. Naming four tiers and
    implementing two honestly is better than implying a provider does
    something it does not.
12. *A restore reuses the approval machinery the assistant already has.* It
    is a destructive operation, it needs an owner or an administrator, its
    approver must be someone who could have performed it, every transition is
    recorded, and an unresolved plan refuses it. Restore takes the export
    rule rather than the upload rule: an unreachable platform closes this
    gate rather than opening it.
13. *An event enters the compliance store only when someone may later have to
    prove it happened.* Audit, activity, security and administrative events
    are rows; application and operational events are log lines. Without that
    sentence the audit table becomes the log.

**Consequences.** The audit table's migration moves between manifest entries
without being renumbered, and a product generated without reporting gains an
audit table it did not have. Storage gains a digest column whose value a
browser asserts, and the documentation says so rather than implying the
product measured it. The provider protocol grows three operations, and the
two providers this estate refuses — Azure Blob and customer-owned — go on
being refused with a reason. Versioning is a column and not a feature: the
dimension is reserved without being added to every listing and every quota
calculation. The archive and backup destinations are buckets nothing in
Terraform creates, and until that is decided the phases that need them are
not started; the phases that do not need them are independent of it. Two
architecture documents describe this in `docs/`, and they land with the code
that creates the identifiers they name, because the documentation tests read
every identifier a top-level document mentions and require it to exist.
