# Storage Architecture & Data Protection — SAG-F1

Part built as of 2026-09-16. See `feature.md` for what that means precisely.

| Document | What it holds |
|----------|---------------|
| `feature.md` | Purpose, scope, requirements, risks, Definition of Done |
| `architecture.md` | Diagrams and the feature-scoped design decisions |
| `user-stories.md` | 20 stories, each classified `EXISTING` / `EXTEND` / `NEW` / `NOT REQUIRED` |
| `acceptance-criteria.md` | Criteria per story, each naming its test or admitting there is none |
| `security.md` | Threat model, controls, and what has not been reviewed |
| `backup-restore.md` | Feature-scoped notes; the design is `docs/BACKUP_AND_RESTORE.md` |
| `configuration.md` | Every setting, where it comes from, and what may override what |
| `integration-contracts.md` | What the Control Plane and the customer portal would consume |
| `testing.md` | Strategy, traceability matrix, and the gaps |
| `manual-test-plan.md` | 14 cases, **none executed** |

## The authoritative descriptions live one level up

This directory does not duplicate them:

- `docs/STORAGE_ARCHITECTURE.md` — how storage works, as built
- `docs/RETENTION_POLICY.md` — retention and holds
- `docs/BACKUP_AND_RESTORE.md` — backup and restore design
- `docs/adr/0003-koras-storage-audit-governance.md` — the decisions
- `docs/adr/0004-storage-provider-abstraction.md`
- `docs/adr/0005-storage-object-hierarchy.md`
- `docs/adr/0006-backup-strategy.md`

## Fastest way in

Read `user-stories.md` first. It is the only document that says, story by story,
what is actually built — and the gap between the schema and the behaviour is
wide enough here that reading the migration would mislead you.
