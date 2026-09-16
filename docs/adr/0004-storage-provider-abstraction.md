# ADR 0004 — Storage Provider Abstraction

**Status.** Accepted 2026-09-16. Extends ADR 0003 decision 5, which stated the
choice in a paragraph; this record carries the operation-by-operation reasoning
and the refusals.

**Context.** A KORAS product must store customer files somewhere the customer
accepts, which for a data-residency requirement may not be the platform's own
bucket. The Control Plane's storage policy already names five providers. Four
possible shapes were available: one client per provider; a thin façade over
vendor SDKs; a generic abstraction covering every storage idea any provider has;
or one narrow protocol covering what this product actually asks of a bucket.

The five-operation protocol shipped on 2026-09-08 and was enough to upload,
download and delete. It was not enough to verify anything or to find anything:
reconciliation needs to ask a bucket what it holds, and a backup needs to
compare what it copied.

**Decision.**

1. *One protocol, and it is narrow.* `ObjectStore` names only what the product
   asks of a bucket. It is not a storage abstraction in general; it is this
   product's storage vocabulary, and a provider feature nothing uses is absent
   from it.
2. *One client for every S3-compatible provider.* Supabase Storage, Cloudflare
   R2, AWS S3 and the local MinIO all speak the protocol, and one client with
   four endpoints is a smaller surface than four clients with four bug
   surfaces. Path-style addressing and signature v4 throughout, because
   Supabase and MinIO require the first and R2 speaks nothing but the second.
3. *Only providers the estate can actually serve are implemented.* Azure Blob
   is not S3-compatible; `customer-owned` needs a credential nothing in the
   estate holds. Both are named by the Control Plane's enum and **refused with
   503 and a reason**, never quietly written to the platform default. Storing a
   customer's data somewhere they did not choose is worse than an outage.
4. *New operations are additive with defaults.* Listing, copying and digests
   were added on 2026-09-15 without breaking any implementation, and any future
   operation arrives the same way.
5. *There is no `move`.* Copy and delete at the call site is two events in the
   audit trail and one visible failure in between. A move is one event that
   either happened or silently half happened, and the half that fails is the
   delete.
6. *Archiving and restoring are not provider operations.* No provider in scope
   offers storage tiering, so they are transitions this layer performs as
   copies. Putting `archive()` on the protocol would imply a capability no
   implementation has.
7. *A digest that cannot be compared is reported as absent.* A multipart entity
   tag is a digest of digests. Returning it would make every large object read
   as corrupt, so `checksum` answers nothing rather than something wrong.
8. *Listing is paged, bounded, and never reachable from a tenant route.* A
   tenant's prefix is unbounded, and a caller that can choose a prefix can
   choose another tenant's. It is a sweep primitive.

**Consequences.** A customer may be served from R2 or S3 with that provider's
credential from Doppler, and the credential never leaves the API process. A
policy naming an unsupported provider is an outage for that customer rather than
a silent misplacement of their data, and that is the intended trade. The
reconciliation sweep became writable, eleven months after two comments in
`00005_files.sql` promised it. Verification of a backup became possible, which is
what made a backup worth designing. The protocol will grow when a product needs
something — tagging, object locking, server-side encryption parameters — and each
addition costs a default and a test rather than a migration.
