# SAG-F1 — Architecture

The prose description is `docs/STORAGE_ARCHITECTURE.md`. This document carries
the diagrams and the feature-scoped reasoning that does not belong in a
subsystem reference.

## Layering

```mermaid
flowchart TD
    Browser[Browser]
    Web[Next.js web tier]
    API[FastAPI product API]
    Store[koras-storage: ObjectStore]
    DB[(files index, forced RLS)]
    CP[Control Plane storage policy]

    Supabase[(Supabase Storage)]
    R2[(Cloudflare R2)]
    S3[(AWS S3)]
    Azure[Azure Blob - refused 503]
    Owned[customer-owned - refused 503]

    Browser -->|server action| Web
    Web -->|customer token| API
    API --> DB
    API -->|policy, cached 60s| CP
    API --> Store
    Store --> Supabase
    Store --> R2
    Store --> S3
    Store -.-> Azure
    Store -.-> Owned
    Browser ==>|signed PUT and GET, bytes| Supabase

    classDef refused stroke-dasharray: 4 4
    class Azure,Owned refused
```

The thick edge is the one that matters: **the bytes never traverse the product.**
Everything else is a control-plane decision about who may obtain a signature.

Only the three S3-compatible providers are implemented. The two dashed ones are
named by the Control Plane's enum and refused with a reason, because a policy
naming a provider the product cannot serve must not fall back to the default.

## Upload

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as API
    participant D as files
    participant S as Bucket

    B->>A: POST /files/uploads (name, size, type)
    A->>A: entitlement, then quota
    A->>D: insert row, status=pending
    A->>S: sign PUT (type and length in signature)
    A-->>B: ticket, 15 minutes
    B->>B: SHA-256 of the bytes
    B->>S: PUT object
    B->>A: POST /files/{id}/complete (digest)
    A->>S: head object
    alt size disagrees
        A->>D: delete row
        A-->>B: 409, object left for the sweep
    else quota now exceeded
        A->>D: delete row
        A-->>B: 402
    else
        A->>S: checksum (provider digest, may be absent)
        A->>D: ready, digest, verified only if corroborated
        A->>D: audit storage.object.uploaded
        A->>A: hand to each registered hook
        A-->>B: file row
    end
```

Three things in that sequence are the feature rather than the plumbing:

1. **The digest is taken before the PUT**, so it describes the bytes this
   browser holds rather than a file that changed on disk mid-upload.
2. **The quota is checked twice.** Between the two checks another ticket may
   have been issued and confirmed.
3. **A size mismatch deletes the row and not the object.** Deleting on a
   client's word is how a race loses a file.

## Download

```mermaid
flowchart LR
    R[GET /files/id/download] --> Ready{row ready?}
    Ready -->|no| NF[404]
    Ready -->|yes| Scan{scan_status infected?}
    Scan -->|yes| Q[403 + security audit event]
    Scan -->|no| Sign[sign GET, 5 min, attachment] --> Aud[audit downloaded] --> T[ticket]
```

The scan check is **before** the signature. A control the page consults and the
API does not is a suggestion.

## The object key

```
tenants/<tenant>/<category>/<file>/<safe name>
```

| Segment | In the key? | Reasoning |
|---------|-------------|-----------|
| tenant | yes | The security boundary, and stable for the object's life |
| category | yes | Closed set. Was emergent and diverging before 2026-09-15 |
| environment | no | Already a separate project and bucket |
| organization | no | Mutable. A tenant that moves would need every object copied |
| product | no | A deployment is one product; a constant segment says nothing |
| date | no | Exists to make prefix listing cheap, and nothing lists by prefix |

Everything omitted is a column. See ADR 0005.

## Lifecycle — designed, not built

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> ready: confirmed
    pending --> [*]: size mismatch or quota
    ready --> quarantined: scan infected
    ready --> archived: retention, copy to archive bucket
    archived --> purged: retention, and no hold
    ready --> deleted: a person deletes it
    quarantined --> ready: rescan clean
```

`ready → archived → purged` is the part nothing performs on 2026-09-16. HOT,
WARM and COLD are metadata; ARCHIVE is the only physical move, because no
provider in scope offers tiering.

## Reconciliation

```mermaid
flowchart TD
    Start[nightly, if enabled] --> Prov[provisioning context]
    Prov --> Each[for each active tenant]
    Each --> List[list the tenant prefix, paged]
    List --> Part{listing finished?}
    Part -->|no| Zero[report partial, zero orphans]
    Part -->|yes| Cmp[compare with rows]
    Cmp --> O[orphan objects]
    Cmp --> U[unverifiable rows]
    Cmp --> S[stale pending rows]
    O --> Rec[one audit row per tenant, counts only]
    Zero --> Next[next tenant]
    Rec --> Next
```

`Zero` is the whole safety property. A truncated listing looks exactly like a
prefix with fewer objects in it.

## Boundaries

| Boundary | Enforced by |
|----------|-------------|
| Tenant | `tenant_id` + forced row-level security, plus the key prefix the API mints |
| Product | One deployment, one product, one bucket. Not a runtime check |
| Environment | A separate Supabase project per environment; separate endpoint and credentials |
| Organization | A column, resolved from the verified token. Never from the key |

## Encryption

At rest by the provider; in transit by TLS on every signed URL. The product
holds no encryption key of its own and does not encrypt object bodies before
upload. Customer-managed keys are not supported as of 2026-09-16 and would need
their own decision — the `customer-owned` provider is refused for the adjacent
reason that nothing in the estate holds such a credential.
