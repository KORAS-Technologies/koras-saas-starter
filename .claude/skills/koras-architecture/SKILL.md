---
name: koras-architecture
description: Koras Architecture guidance for Koras applications.
---

# Koras Architecture

Use this skill when creating applications, packages, services, cross-cutting infrastructure, or deciding where new code belongs.

## Goal

Preserve a modular Koras monorepo with clear dependency direction and low coupling.

## Procedure

1. Inspect the current repository structure before proposing changes.
2. Find analogous modules or features.
3. Identify the owning layer: app, shared package, service, or infrastructure.
4. Prefer extending an existing abstraction when it has the correct responsibility.
5. Introduce a new package only when it has a stable reusable responsibility and more than one likely consumer, or when isolation is important for security/architecture.
6. Keep server-only code out of browser bundles.
7. Prevent circular dependencies.
8. Document new architectural boundaries when they are non-obvious.

## Expected Boundaries

```text
apps/             deployable UIs
services/         APIs, workers, schedulers, AI/background execution
packages/ui       reusable UI primitives/components
packages/auth     shared auth helpers and types
packages/database database access, migrations/types helpers as applicable
packages/config   shared typed configuration
packages/validation shared schemas
packages/api-client typed API clients
packages/types    shared domain contracts
packages/observability telemetry/logging helpers
infrastructure/   Terraform and platform configuration
```

Apps may depend on packages. Packages must not depend on apps.

## Decision Rules

- Page-specific presentation belongs near the page/feature.
- Reusable presentation primitives belong in `packages/ui`.
- Shared validation belongs in `packages/validation`.
- Shared cross-boundary DTO/domain contracts belong in `packages/types` or the established contract package.
- External-system integrations should be wrapped in an adapter/client rather than scattered across components.
- Business logic that must be trusted belongs server-side.
- Infrastructure provisioning belongs under `infrastructure/`, not app runtime code.

## Reject These Patterns

- Duplicate shared components in multiple apps.
- Package importing from an app.
- Browser code importing server secrets.
- Database calls directly from arbitrary presentational components.
- Security decisions made only in client-side code.
- New framework/pattern introduced when the repository already has a valid equivalent.
