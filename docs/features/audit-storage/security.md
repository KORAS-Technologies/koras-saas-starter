# SAG-F2 — Security

> **No independent security review has been performed.** The `security_review`
> gate is `independent: true`, and this document was written by the work that
> built the controls. It is the input to that review, not its outcome.
> Status 2026-09-16.

## Assets

| Asset | Why it matters |
|-------|----------------|
| Audit rows | Evidence. Worthless if editable, dangerous if leaked |
| The actor subject | Personal data, kept for up to three years |
| Details maps | Small, and the place a secret would end up if the guard failed |
| The platform aggregate | Cross-tenant by design, and therefore the most sensitive route |

## Trust boundaries

1. Browser → API: nothing the browser asserts about tenancy or class is believed.
2. API → database: forced row-level security; the API's checks and the
   database's are independent.
3. Worker → database: provisioning context, transaction-local, from no request input.
4. Product → platform: the platform reads counts; the product pushes nothing.

## Controls

| Control | State |
|---------|-------|
| Forced RLS, insert and select scoped to the tenant | Built |
| **No update policy for anyone**, including provisioning | Built |
| **No tenant delete policy**; only the sweep deletes | Built |
| Cross-tenant emit refused by the sink | Built |
| Credential-shaped detail keys refused at construction | Built |
| Class written from the registry, never from a caller | Built |
| Undeclared action refused rather than defaulted | Built |
| Platform aggregate is counts only, machine identity only | Built |
| Retention floor of one day per class, checked before any delete | Built |
| Hold blocking purge | **Not built** |
| Permission gate for security-classified rows | **Not built** |
| Export authorization and artifact expiry | **Not built** |

## Abuse cases

None executed. This is the list a security test pass should work through.

| # | Attempt | Expected |
|---|---------|----------|
| B1 | Read another tenant's audit rows | none visible |
| B2 | Insert a row naming another tenant | `insufficient_privilege` |
| B3 | Update any row, as any principal | refused; no update policy exists |
| B4 | Delete own rows as a tenant | refused; no tenant delete policy |
| B5 | Record a detail named `storage_key` or `api_key` | `ValueError` at construction |
| B6 | Record an undeclared action | raises; no row written |
| B7 | Pass a class alongside an event | impossible; the field is not a parameter |
| B8 | Present a customer token to the private contract | refused |
| B9 | Infer another tenant's volume from the aggregate | the aggregate is per-tenant and machine-only |
| B10 | Set a retention of 0 to wipe the table | refused before any delete |
| B11 | Enumerate rows by id to find another tenant's | 404, not 403 — **unbuilt; AUDIT-005** |
| B12 | Export another tenant's history | **unbuilt; AUDIT-011** |

## The sharp edges

Three things that are correct and could easily be made wrong by a later change:

**An undeclared action raises, and that can fail a request.** This was chosen
deliberately over a silent default, because a default means a security event
swept on the activity schedule. The consequence is that adding an action without
registering it turns a working route into a 500 — caught by tests, but worth
knowing before someone "fixes" it by adding a fallback.

**The sink refuses rather than drops.** A cross-tenant event is a bug, and
dropping it would hide the bug while losing the record.

**Redaction has false positives on purpose.** `report_key` is refused because it
contains `key`. The cost is renaming a detail; the cost of the opposite error is
a credential in a table kept for three years.

## What integrity does and does not mean here

It means the database refuses the write: no update policy, no tenant delete.
That is strong against the application and against a compromised request path.

**It is not cryptographic.** There is no hash chain, no signature and no external
write-once store, so it is not strong against a principal with the database
owner role. No requirement has asked for more as of 2026-09-16, and claiming
tamper-proof rather than tamper-resistant would be the kind of overstatement a
compliance questionnaire punishes.

## Personal data

The actor's subject is the minimum the record cannot do without, and nothing
else about a person is copied. Names and addresses resolve at read time from the
identity provider, which is why `actor_display` was declined in
`audit-event-model.md`. IP addresses are **not** recorded by default.

A privacy and compliance review has not run, and this feature is squarely in its
scope: personal data, three-year retention, and an export path that would move
it out of the product.

## Open security items

| # | Item | Status |
|---|------|--------|
| B-S1 | Independent security review | **Not run** |
| B-S2 | Privacy and compliance review | **Not run** |
| B-S3 | Abuse cases B1–B12 executed | **Not run** |
| B-S4 | The reconciliation sweep's cross-context insert, proven under the restricted role | **No test** |
| B-S5 | A hold that nothing enforces would be false assurance | Unbuilt, and must ship with the sweep change |
| B-S6 | No alert if the retention sweep stops running | Open |
