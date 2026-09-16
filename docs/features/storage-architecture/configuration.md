# SAG-F1 — Configuration

Every setting storage reads, where it comes from, and what may override what.
State as of 2026-09-16.

## Inheritance

```
Platform floor        settings and code. Nothing may go below it
      |
Product policy        the product's own configuration
      |
Tenant policy         tenant settings, and tightening only
```

**Only the platform level exists.** Product and tenant levels are designed and
unbuilt for storage retention; the one genuinely per-tenant input today is the
Control Plane's storage policy, which selects a provider rather than relaxing a
control.

The rule that governs the layers when they are built: **a tenant may tighten and
may never loosen.** A security or compliance minimum is not tenant-configurable
at any level.

## Settings

All are declared in `local/config/secrets.manifest`. A setting not declared
there is never prompted for and never checked, which is how two incidents
started.

| Setting | Class | Default | What it does |
|---------|-------|---------|--------------|
| `STORAGE_ENDPOINT` | derived | Terraform output | The S3-compatible endpoint for this environment |
| `STORAGE_REGION` | derived | Terraform output | For SigV4 signing |
| `STORAGE_BUCKET` | supplied | — | The bucket name. Not a resource Terraform creates |
| `STORAGE_ACCESS_KEY` | supplied | — | Minted in the Supabase dashboard; MinIO's root pair locally |
| `STORAGE_SECRET_KEY` | supplied | — | As above |
| `STORAGE_R2_ACCESS_KEY` | optional | — | For a customer whose policy names Cloudflare R2 |
| `STORAGE_R2_SECRET_KEY` | optional | — | As above |
| `STORAGE_S3_ACCESS_KEY` | optional | — | For a customer whose policy names AWS S3 |
| `STORAGE_S3_SECRET_KEY` | optional | — | As above |
| `STORAGE_RECONCILE_ENABLED` | optional | off | Whether the nightly sweep runs at all |
| `STORAGE_PENDING_STALE_HOURS` | optional | 24 | When a pending upload is counted stale |

Reconciliation is **off by default** deliberately: it lists every active
tenant's prefix, which costs provider requests, and a product with a hundred
files does not need it.

## Per-customer, from the Control Plane

`GET /api/portal/v1/products/{code}/storage-policy`, read with the **customer's
own token**, cached 60 seconds. A product holds no machine credential toward the
platform, so the organization comes from the token and there is nowhere to name
another one.

| Policy says | Product does |
|-------------|--------------|
| nothing | the platform default bucket |
| `supabase`, `cloudflare-r2`, `aws-s3` | signs against it with that provider's pair |
| `azure-blob`, `customer-owned` | refuses with 503 and a reason |

The platform reports its own defaults back through
`GET /internal/platform/v1/storage-defaults`, so a policy recorded at
provisioning carries a real destination rather than blanks. The key pair is
never part of that answer.

## Entitlement

`storage.files`, read with the customer's token and cached the same way. Granted
from Starter upward with a per-plan ceiling in gigabytes, converted to bytes by
the API.

**An unreachable platform is no gate.** A customer whose plan cannot be read
keeps storing files, and the page says the plan could not be read. This is the
opposite of the rule export and restore follow, and the asymmetry is deliberate:
an outage must not lock a customer out of their own work, and must not let data
leave the product unverified either.

## Capability

Everything above is generated into **every** product. Storage is foundation, not
a capability, and `--without` does not remove it.

The two capabilities the plan named — one for storage governance, one for audit
— are **undeclared as of 2026-09-16**. When they are declared, both are off by
default, following the `ai` precedent: a capability whose later phases need an
external resource stays off until a product asks.

## Local development

The Compose stack runs MinIO as the `storage` service on ports 9000 and 9001.
MinIO is the local stand-in and never exists in a deployed environment, which is
why its credentials are declared `local` rather than `supplied`.

## Not configurable, and deliberately

| Thing | Why |
|-------|-----|
| The object key layout | A key is signed and stored; making it configurable makes every stored key ambiguous |
| Signed URL lifetimes | 15 minutes up, 5 down. A per-tenant knob here is a per-tenant weakening |
| Whether operations are audited | Auditing is not optional |
| Whether RLS is forced | The startup check refuses to serve without it |
| The 5 GiB object ceiling | One object, one signed PUT. Larger needs multipart, which is F22 |
