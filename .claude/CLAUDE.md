# Koras Engineering Instructions

## Purpose

This repository uses Claude Code as an engineering assistant. Claude must preserve the existing architecture, reuse established abstractions, implement scoped changes, verify behavior, and avoid declaring work complete merely because the project compiles.

## Which repository is this?

Read `.koras/project.yaml` before doing anything profile-sensitive. It is the
authoritative identification record written by `create-koras-app`, and it is the
only source to trust for this question — not the directory name, not the git
remote, not a guess from the code.

```yaml
project:
  profile: product | control-plane
```

| `project.profile` | What this repository is | Profile skill to load |
|-------------------|-------------------------|-----------------------|
| `product`         | A customer-facing multi-tenant KORAS SaaS product | `koras-profile-product` |
| `control-plane`   | KORAS Control Plane — the platform authority       | `koras-profile-control-plane` |

Load that profile skill in addition to the common skills below. Its rules are
narrower than these and take precedence where the two differ.

If `.koras/project.yaml` is absent, this is the `koras-saas-starter` factory
itself rather than a generated project. The factory carries the common skills
only; it belongs to neither profile, and profile-specific rules are authored
here rather than applied here.

## Core Engineering Principles

1. Search before creating. Reuse existing components, hooks, utilities, clients, schemas, types, services, and patterns where appropriate.
2. Keep changes scoped to the requested feature. Do not refactor unrelated code unless required to complete the task safely.
3. Preserve package boundaries and dependency direction.
4. Prefer explicit, typed, testable abstractions over hidden coupling.
5. Treat authentication, authorization, tenant isolation, accessibility, validation, error handling, and observability as product requirements.
6. Never expose secrets, service-role credentials, private tokens, or privileged API keys to client bundles.
7. Never trust tenant IDs, roles, permissions, ownership, redirect URLs, filenames, or security-sensitive state supplied by the browser without server-side verification.
8. Do not disable security controls just to make a feature work.

## Repository Shape

Use the existing repository structure as the source of truth. The expected Koras pattern is:

```text
apps/
services/
packages/
infrastructure/
```

Typical responsibilities:

```text
apps/            Deployable frontend/admin applications
services/        APIs, workers, schedulers, AI/background services
packages/ui      Shared UI primitives and components
packages/auth    Shared auth/session helpers
packages/database Database access and generated types
packages/config  Shared configuration
packages/validation Shared validation schemas
packages/api-client Typed client-side/server-side API clients
packages/types   Cross-package domain types
packages/observability Logging, tracing, telemetry helpers
infrastructure/  Terraform and deployment infrastructure
```

Apps may depend on packages. Packages must not depend on apps. Avoid circular dependencies.

## Required Feature Workflow

For a new feature or meaningful change:

1. Understand the request and acceptance criteria.
2. Search the repository for related code and established patterns.
3. Identify affected apps, packages, services, APIs, database objects, tests, and documentation.
4. Produce a concise implementation plan before large changes.
5. Implement the smallest coherent change.
6. Apply React/Next.js best practices when frontend code is involved.
7. Apply the Koras UI design system when UI is involved.
8. Validate forms and external inputs using shared schemas where appropriate.
9. Review authentication, authorization, tenant isolation, and security impacts.
10. Review accessibility for user-facing changes.
11. Add or update automated tests.
12. Run required checks.
13. Exercise critical user flows with Playwright for user-facing features.
14. Check browser console errors and obvious responsive regressions.
15. Review the resulting git diff for architecture, quality, security, duplication, and unrelated changes.
16. Update relevant documentation.

## Required Verification

Run the commands that exist in the repository. Prefer the workspace-standard scripts, commonly:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

For user-facing features also perform:

- Playwright verification of the critical path.
- Browser console check.
- Desktop and mobile-width verification.
- Keyboard and focus-state verification where interactive controls changed.
- Loading, empty, error, unauthorized, forbidden, and validation states where applicable.

Do not claim a check passed if it was not executed successfully.

## UI Rules

- Search `packages/ui` before creating a new primitive.
- Prefer existing shadcn/ui or Radix-based primitives when already adopted by the repo.
- Use design tokens and semantic classes; avoid arbitrary hardcoded colors and ad hoc design systems.
- Every async screen should consider loading, empty, success, and error states.
- Forms must have labels, validation, accessible errors, submit protection, and visible disabled/loading behavior.
- Interactive controls must work with keyboard navigation and visible focus.
- Avoid creating page-local duplicates of reusable buttons, dialogs, tables, form fields, alerts, and layout primitives.

## React and Next.js Rules

- Prefer server components where appropriate and keep client boundaries intentional.
- Avoid unnecessary `useEffect`, derived state, and repeated client fetching.
- Avoid request waterfalls when independent work can execute concurrently.
- Keep component APIs composable instead of adding many boolean flags.
- Lazy-load heavy client-only functionality where appropriate.
- Keep client bundles free of server-only dependencies and secrets.
- Use stable keys and avoid unnecessary rerenders.

## Forms

Preferred pattern:

```text
React Hook Form + Zod + shared validation schema
```

Use shared schemas when the same business validation is required on both client and server. Handle default values, async submission, server validation, dirty state, reset behavior, and duplicate submission protection explicitly.

## API Access

Do not scatter raw `fetch()` calls across unrelated UI components when an API client abstraction exists or is appropriate. Prefer a typed API client with consistent:

- request/response types
- authentication
- validation
- error normalization
- timeout handling
- request IDs / correlation IDs
- safe retry behavior where appropriate

## Authentication and Authorization

Authentication and authorization are different concerns.

Every protected operation must verify the authenticated principal and the required permission. For tenant-owned resources, also verify trusted tenant context and resource ownership or permitted tenant access.

Client-side route guards are UX helpers, not security boundaries.

## Multi-Tenancy

For tenant-owned data:

- Scope server-side queries by trusted tenant context.
- Do not trust a browser-provided tenant ID as authorization evidence.
- Fail closed on ambiguous tenant context.
- Review RLS/policy implications for database changes.
- Prevent cross-tenant cache leakage.
- Include tenant context in relevant audit events and logs without exposing sensitive data.

## Security

Review changes for at least:

- authentication and authorization
- tenant isolation
- input validation
- XSS
- CSRF where relevant
- SSRF for server-side fetches
- SQL/query injection
- path traversal
- file upload validation
- secret exposure
- unsafe logging
- rate limiting / abuse paths
- webhook verification
- unsafe redirects
- CORS configuration

Never move privileged credentials into `NEXT_PUBLIC_*` variables.

## Accessibility

Target WCAG 2.2 AA for product UI. New and changed UI must use semantic HTML, correct labels, keyboard operability, visible focus, useful error association, sensible heading hierarchy, and reduced-motion support where motion is used.

## Testing

Test behavior rather than implementation details.

Use the appropriate mix of:

- unit tests for deterministic logic
- integration tests for package/service boundaries
- component tests where useful
- Playwright for critical user journeys

A feature is not complete while critical or high-severity defects discovered during review remain unresolved.

## Git Discipline

- Do not overwrite unrelated user changes.
- Keep commits focused when commits are requested.
- Do not force-push, rewrite history, or delete branches unless explicitly instructed.
- Review `git diff` before completion.
- Do not commit generated secrets or local environment files.

## Skill Routing

Skills live at `.claude/skills/<name>/SKILL.md` — one directory per skill, which
is the layout Claude Code discovers. The `koras-` prefix carries the logical
grouping that a nested directory would otherwise.

Common skills, present in every KORAS repository:

- `koras-architecture`
- `koras-feature-development`
- `koras-ui-design-system`
- `koras-forms`
- `koras-api-client`
- `koras-auth`
- `koras-multitenancy`
- `koras-supabase`
- `koras-security`
- `koras-accessibility`
- `koras-testing`
- `koras-code-review`

Profile skills, exactly one of which is present, selected at generation time
from `--profile` and recorded in `.koras/project.yaml`:

- `koras-profile-product`
- `koras-profile-control-plane`

External skills, vendored under `.claude/skills/external/` and pinned in
`.claude/external-skills.yaml`, cover frontend design, React best practices, web
design review, and browser testing. Use them when present. Their absence is not
an error — the Koras skills above are complete without them, and nothing in a
KORAS repository requires network access to obtain its standard configuration.

## Commands

- `/feature <request>` — full implementation workflow
- `/review [scope]` — diff review
- `/test [target]` — verification-only pass
- `/ui-review [target]` — focused frontend review
