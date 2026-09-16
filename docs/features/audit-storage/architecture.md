# SAG-F2 — Architecture

The prose description is `docs/AUDIT_ARCHITECTURE.md`. This carries the
diagrams and the one architectural question worth arguing.

## The question: is a separate event pipeline justified?

The original design sketched publisher → ingestion → validation → store. **The
ingestion tier was declined**, and the reasoning is the substance of this
document rather than a footnote.

Events are written inside the request's own transaction, on the tenant's own
session. That gives three properties for free that a queue would make into
problems:

| Property | Synchronous write | With an ingestion queue |
|----------|-------------------|-------------------------|
| Tenancy | Enforced by row-level security on the same session | The consumer must re-establish it, from data the producer sent |
| Atomicity | The record and the work commit together | A refusal can be returned and not recorded |
| Ordering | The transaction's clock | A delivery-order guarantee to design and defend |

The cost of the synchronous choice is latency on hot routes and a failed write
becoming a failed request. Neither is showing as of 2026-09-16.

**What would change the answer:** flush latency appearing in traces on the file
download path, or a volume at which the table's write rate matters. Both are
observable, and neither is observed. Building the queue first would be adding a
delivery guarantee to reason about in exchange for a problem nobody has.

## As built

```mermaid
flowchart TD
    subgraph Product
        R[API route] -->|emit| S[SqlAuditSink buffer]
        S -->|flush after the answer| T[(audit_events)]
        Reg[Action registry] -->|classification| S
        W1[Reporting worker] -->|as tenant| T
        W2[Reconciliation sweep] -->|as tenant| T
        Sweep[Retention sweep] -->|provisioning, delete by class| T
    end
    T --> AR[Activity report]
    T --> PA[GET /internal/platform/v1/activity]
    PA -->|hourly, counts only| CP[Control Plane]
    AR --> Cust[Tenant administrator]

    L[Application and operational logs] --> Loki[(Loki / Tempo)]
    L -.->|never| T
```

The dashed edge is the design rule: **operational logs never enter the
compliance store.** Without that line the table becomes a log with a slower
query planner.

## Write path

```mermaid
sequenceDiagram
    participant R as Route
    participant S as SqlAuditSink
    participant Reg as Registry
    participant D as audit_events

    R->>S: emit(event)
    S->>S: tenant matches? else refuse
    Note over S: buffered, not written
    R->>R: decide the answer (success or refusal)
    R->>S: flush()
    S->>Reg: classification_of(action)
    alt action not registered
        Reg-->>S: raise
    else
        Reg-->>S: class
        S->>D: insert
        S->>D: commit
        S->>S: rebind tenant
    end
```

Two details that cause bugs elsewhere and are handled once here: the buffer
exists so a mid-request write cannot leave the session in an unknown state, and
the rebind exists because the commit drops `app.tenant_id`, which is
transaction-local.

## Retention

```mermaid
flowchart LR
    N[nightly 03:23] --> G{every class >= 1 day?}
    G -->|no| Stop[raise, delete nothing]
    G -->|yes| P[provisioning context]
    P --> A[delete activity older than 90d]
    A --> B[delete audit older than 365d]
    B --> C[delete administrative older than 365d]
    C --> E[delete security older than 1095d]
    E --> Commit[one commit]
```

The guard before the first delete is the safety property: a typo in one number
cannot delete the three that were right.

## Designed, not built

```mermaid
flowchart TD
    T[(audit_events)] -.-> Search[Search and filter API]
    Search -.-> Page[Tenant audit page]
    T -.-> Export[Export job, reusing report_exports]
    Export -.-> Art[Signed artifact, expiring]
    T -.-> Arch[(Archive)]
    Hold[Legal hold] -.->|blocks| Purge[Purge]
```

Everything dashed is design. `archival.md`, `legal-hold.md` and
`integration-contracts.md` carry the detail.

## Reuse, and what it buys

| Need | Existing mechanism reused |
|------|---------------------------|
| Export pipeline | `report_exports`: 202, background write, signed artifact, retirement |
| Approval for a destructive action | The AI foundation's action state machine and `may_decide` |
| Registry with import-time refusal | `koras_reporting`'s registries |
| Cross-tenant sweep | The provisioning declaration and the `_AS_TENANT` switch |
| Typed, declared filters | `koras_reporting.filters` — and its rule that there is no free-text filter |

Nothing in this feature needs a new framework. That is the point of the
architecture rather than an accident of it.
