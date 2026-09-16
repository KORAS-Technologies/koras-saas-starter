# Audit Storage, Retention & Archival — SAG-F2

Part built as of 2026-09-16. See `feature.md` for what that means precisely.

| Document | What it holds |
|----------|---------------|
| `feature.md` | Purpose, scope, event categories, requirements, Definition of Done |
| `architecture.md` | Diagrams, and the argument for not building an ingestion tier |
| `audit-event-model.md` | The envelope, field by field, and where the proposed fields went |
| `user-stories.md` | 21 stories, each classified `EXISTING` / `EXTEND` / `NEW` / `NOT REQUIRED` |
| `acceptance-criteria.md` | Criteria per story, each naming its test or admitting there is none |
| `retention-policy.md` | Feature-scoped notes; the policy is `docs/RETENTION_POLICY.md` |
| `archival.md` | Lifecycle states, transitions, and why none is built |
| `legal-hold.md` | The record, the authorization, and what blocks building it |
| `security.md` | Threat model, controls, and what has not been reviewed |
| `configuration.md` | Settings, inheritance, and what is not configurable |
| `integration-contracts.md` | What the Control Plane and the portal would consume |
| `testing.md` | Strategy, traceability, and the gaps |
| `manual-test-plan.md` | 11 cases, **none executed** |

## The authoritative descriptions live one level up

- `docs/AUDIT_ARCHITECTURE.md` — how audit works, as built
- `docs/RETENTION_POLICY.md` — retention precedence for both features
- `docs/adr/0003-koras-storage-audit-governance.md` — the decisions

## The one thing to know before reading anything else

The table records, the classes work and the sweep runs. **Nothing searches,
nothing exports, nothing archives and nothing holds.** A reader who saw
`classification`, `retain_until` and `legal_hold` in the schema and inferred a
compliance capability would be wrong by a wide margin, and `user-stories.md` is
the document that says so story by story.
