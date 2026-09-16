# SAG-F1 — Security

> **No independent security review has been performed.** This document is the
> threat model and the control inventory written by the same work that built the
> controls, which is precisely the arrangement
> `profiles/product/template/.claude/orchestration/quality-gates.yaml` marks as
> insufficient: the `security_review` gate is `independent: true`. Treat what
> follows as the input to that review, not its outcome. Status 2026-09-16.

## Assets

| Asset | Why it matters |
|-------|----------------|
| Customer file contents | The thing a customer would be most upset to have leaked |
| Object keys | Half a signed URL. Not secret, but not to be scattered |
| Provider credentials | Reach every object in the bucket |
| Signed URLs | Bearer credentials with a short life |
| The file index | Names, sizes and who uploaded what — metadata is disclosure too |
| Audit rows | Evidence, and useless if editable |

## Actors

| Actor | Trust |
|-------|-------|
| Tenant member | Authenticated, scoped to one tenant, untrusted as to tenant claims |
| Tenant owner / administrator | The same, plus destructive authority within the tenant |
| Platform machine identity | Cross-tenant read on the private contract, counts only |
| The worker | Cross-tenant, on the provisioning context, no request input |
| A registered hook | Runs with a signed URL; product code, not customer code |
| The browser | Fully untrusted, including everything it asserts about an upload |

## Trust boundaries

1. Browser → web tier: nothing the browser says about tenancy is believed.
2. Web tier → API: the customer's own token; the API re-decides everything.
3. API → database: forced row-level security, independent of the API's checks.
4. API → provider: the credential stops here and never travels outward.
5. Worker → database: provisioning context, transaction-local, no request input.

## Controls

| Control | Where | State |
|---------|-------|-------|
| Trusted tenant from a verified token | `core/tenant.py` | Built |
| Forced RLS on the index | `00005`, `00018` | Built |
| A transaction that refuses to open undeclared | `koras-database` | Built |
| API-minted keys; browser never chooses one | `koras_storage.object_key` | Built |
| Filename sanitisation on key and header | `safe_filename` | Built |
| Content type and length in the upload signature | `presign_upload` | Built |
| Attachment disposition on every download | `presign_download` | Built |
| Short URL lifetimes: 15 min up, 5 min down | `routers/files.py` | Built |
| Role check for deletion | `routers/files.py` | Built |
| Entitlement gate and quota, both ends | `core/storage.py`, `routers/files.py` | Built |
| Unsupported provider refused, never defaulted | `resolve_destination` | Built |
| Withheld file refused before signing | `core/file_scan.py` | Built |
| Every operation and refusal audited | `core/audit.py` | Built |
| Credential-shaped audit details refused | `koras_audit` | Built |
| Legal hold blocking removal | — | **Not built** |
| Restore approval and cross-tenant refusal | — | **Not built** |

## Abuse cases

None of these has been executed. They are the list a security test pass should
work through.

| # | Attempt | Expected |
|---|---------|----------|
| A1 | Fetch another tenant's file by id | 404, and nothing disclosed |
| A2 | Insert a row naming another tenant | `insufficient_privilege` |
| A3 | Move a row to another tenant by update | `insufficient_privilege` |
| A4 | Lift another tenant's legal hold | touches nothing |
| A5 | Edit a signed URL's key to another object | provider refuses; signature covers the key |
| A6 | Replay a signed URL after expiry | provider refuses |
| A7 | Upload a different content type than the ticket | provider refuses |
| A8 | Filename with `../` or control characters | sanitised; cannot escape the prefix |
| A9 | Two concurrent tickets to exceed the quota | second confirmation refused |
| A10 | Download a quarantined file | 403 before signing |
| A11 | Record `storage_key` as an audit detail | `ValueError` from the envelope |
| A12 | Delete a file as a plain member | 403, audited as a security event |
| A13 | Reach `list` from a tenant route | no such route exists |
| A14 | Point a storage policy at an internal address | see the open item below |

## OWASP API Top 10

Against `docs/OWASP_CHECKLIST.md`:

| Row | Position |
|-----|----------|
| API1 Object level authorization | Two layers: `require_tenant` and forced RLS |
| API2 Authentication | ZITADEL bearer, signature, audience and issuer verified |
| API3 Property exposure | `tests/security/test_api_surface.py` fails on credential-shaped response fields |
| API4 Resource consumption | Paged listings; 5 GiB ceiling; rate limits on the tier |
| API5 Function level authorization | Role checked server-side for deletion |
| API6 Sensitive business flows | **Restore will need its own flow-keyed limit when built** |
| API7 SSRF | No route fetches a caller-supplied URL. **A restore-from-URL feature would break this row and must not be built** |
| API8 Misconfiguration | Doppler only; no credential in any bundle |
| API9 Inventory | The provider enum mirrors the Control Plane's |
| API10 Unsafe third-party APIs | Only S3-compatible providers, and unsupported ones refused |

## Secrets

Doppler is the sole authority. `STORAGE_ACCESS_KEY` and `STORAGE_SECRET_KEY` are
`supplied`; the R2 and S3 pairs are `optional`. Every new setting is declared in
`local/config/secrets.manifest` or it is never prompted for and never checked —
a rule that exists because omitting it has caused two incidents.

A signed URL is a bearer credential. Nothing logs one, nothing audits one, and
the audit envelope's forbidden-detail rule makes recording the key a `ValueError`
rather than a judgement call.

## Open security items

| # | Item | Status |
|---|------|--------|
| S1 | Independent security review | **Not run** |
| S2 | Privacy and compliance review | **Not run** |
| S3 | Abuse cases A1–A14 executed | **Not run** |
| S4 | The reconciliation sweep's own audit write, proven under the restricted role | **No test** |
| S5 | A storage policy naming a host that resolves to a private address | Open; the same shape as `FOLLOW_UPS.md` F19's DNS half |
| S6 | No scanner is installed anywhere | By design; the seam exists |
| S7 | Rate limiting for restore and export | Not built, because neither is |
