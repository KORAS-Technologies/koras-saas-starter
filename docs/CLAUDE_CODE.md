# Claude Code

How the KORAS factory defines its Claude Code configuration, and how every
generated repository inherits it.

## The shape of it

There is one definition, in one place, plus one overlay per profile:

```
koras-saas-starter/
  .claude/                                   ← COMMON. Single source of truth.
    CLAUDE.md                                  Shared engineering instructions
    commands/  feature.md review.md test.md ui-review.md
    agents/    architect.md frontend.md reviewer.md tester.md
    skills/
      koras-*/                               12 Koras skills
      frontend-design/ webapp-testing/       vendored external skills
      react-best-practices/ web-design-guidelines/
    scripts/sync-external-skills.mjs
    external-skills.yaml                     what is vendored, and from where
    external-skills.lock.json                the exact commit of each

  profiles/product/template/.claude/skills/
      koras-profile-product/                 ← OVERLAY. Product only.

  profiles/control-plane/template/.claude/skills/
      koras-profile-control-plane/           ← OVERLAY. Control Plane only.
```

**Common configuration + one profile overlay.** There is deliberately no second
copy of the common tree per profile. That duplication is the mechanism behind
most of this repository's recurring defects — a fix lands in one profile and the
other keeps the old version — and `docs/SYNC_BACKLOG.md` exists because of it.

### Why the skills are flat

The logical structure is grouped (Koras, profiles, external). The physical
structure is flat, because Claude Code discovers skills at
`.claude/skills/<name>/SKILL.md` and does not descend further. The grouping
survives in the names: `koras-*` for the common skills, `koras-profile-*` for
the overlays, and the plain upstream name for a vendored external skill, whose
provenance is recorded in `external-skills.yaml` rather than in a directory.

## How a generated project inherits it

Both profile manifests declare the common tree as a shared asset:

```yaml
# profiles/<profile>/manifest.yaml
shared_assets:
  - source: infrastructure/terraform/modules
    target: infrastructure/terraform/modules
  - source: .claude
    target: .claude
```

`create-koras-app` then generates in this order:

1. Walk `profiles/<profile>/template/`, rendering `.hbs` files through
   Handlebars. This is where the profile overlay skill and the root `CLAUDE.md`
   come from.
2. Copy every `shared_assets` directory **verbatim** — no Handlebars. This is
   where the common `.claude/` tree comes from. Shared assets are never
   rendered, so a skill may contain `{{...}}` without being mangled.
3. Write `.koras/project.yaml` from starter and profile metadata.
4. Validate the written repository — including that the common tree and the
   *correct* profile skill both landed.

Result:

| Invocation | Receives |
|------------|----------|
| `--profile product` | common `.claude/` + `koras-profile-product` |
| `--profile control-plane` | common `.claude/` + `koras-profile-control-plane` |

A product never receives `koras-profile-control-plane`, and vice versa, because
the overlay lives in the profile's own template tree and the template walk only
ever visits one of them.

## How `.koras/project.yaml` determines profile

`.koras/project.yaml` is written into every generated repository and is the
authoritative answer to "what is this repository":

```yaml
schema_version: 1
project:
  name: example-product
  slug: example-product
  profile: product
generator:
  name: create-koras-app
  starter_version: 0.1.0        # from the starter's root package.json
  profile_version: 1.0.0        # from profiles/<profile>/manifest.yaml
  template_digest: <sha256>     # digest of the whole profile tree
components:
  applications: [...]
  services: [...]
  capabilities: [...]
```

`.claude/CLAUDE.md` instructs Claude to read this file before anything
profile-sensitive, and to prefer it over the directory name, the git remote or
an inference from the code. A repository with **no** `.koras/project.yaml` is
the starter itself — the factory, which belongs to neither profile.

Versions are never hardcoded: `starter_version` is read from the workspace
`package.json` at generation time and `profile_version` from the profile
manifest, both validated as semver before anything is written.

## Commands

| Command | What it does |
|---------|--------------|
| `/feature <request>` | Full workflow: search, plan, implement, test, browser-verify, review |
| `/review [scope]` | Diff review, findings classified CRITICAL/HIGH/MEDIUM/LOW |
| `/test [target]` | Verification-only pass, including Playwright on critical paths |
| `/ui-review [target]` | Focused frontend review against the design system and accessibility |

Agents (`architect`, `frontend`, `reviewer`, `tester`) are the specialist
prompts those commands delegate to.

## The common skills

| Skill | Use for |
|-------|---------|
| `koras-architecture` | Where new code belongs; package boundaries |
| `koras-feature-development` | End-to-end feature workflow |
| `koras-ui-design-system` | Product UI, tokens, shared primitives |
| `koras-forms` | React Hook Form + Zod + shared schemas |
| `koras-api-client` | Typed API access, error normalization |
| `koras-auth` | Sessions, roles, permissions, ZITADEL |
| `koras-multitenancy` | Tenant-scoped data and trusted context |
| `koras-supabase` | Schema, RLS, generated types, storage |
| `koras-security` | Trust boundaries, the review checklist |
| `koras-accessibility` | WCAG 2.2 AA for user-facing UI |
| `koras-testing` | Test strategy and completeness |
| `koras-code-review` | Final diff review |

## The profile skills

`koras-profile-product` — the repository is a customer-facing, multi-tenant
KORAS SaaS product. Priorities: tenant isolation, organization context,
onboarding, tenant domains and branding, subscriptions, plans, entitlements,
customer-facing responsive UX, RLS, ZITADEL, API security, tenant-aware storage,
observability, accessibility, testing. Two rules override convenience: never
trust a browser-supplied tenant identifier, and never bypass authorization or
RLS.

`koras-profile-control-plane` — the repository administers the KORAS platform
itself, across Dashboard, Organizations, Products, Tenants, Plans,
Subscriptions, Entitlements, Domains, Branding, Identity, Enterprise SSO, AI,
Storage, Infrastructure, Provisioning, Reconciliation, Audit and Platform
Health. Priorities: operational visibility, information density, explicit
authorization, auditability, safe destructive actions. Three rules override
convenience: never expose infrastructure secrets, never weaken `platform_admin`
authorization, and never treat navigation visibility as authorization — admin
actions are enforced server-side.

## External skills

Four external skills are vendored into `.claude/skills/`:

| Skill | Source | Role |
|-------|--------|------|
| `frontend-design` | `anthropics/skills` | Visual direction, polished UI |
| `webapp-testing` | `anthropics/skills` | Playwright browser verification |
| `react-best-practices` | `vercel-labs/agent-skills` | React/Next.js quality and performance |
| `web-design-guidelines` | `vercel-labs/agent-skills` | UX, accessibility, interface review |

They are **committed**, not fetched during generation. A generated project needs
no network access to obtain its standard configuration, and it can never
silently pick up an upstream revision nobody reviewed.

### Upgrading them

```bash
node .claude/scripts/sync-external-skills.mjs            # install anything missing
node .claude/scripts/sync-external-skills.mjs --dry-run  # show what it would do
node .claude/scripts/sync-external-skills.mjs --update   # re-resolve declared refs
node .claude/scripts/sync-external-skills.mjs --skill react-best-practices
```

Without `--update` the script is idempotent: a skill already present is left
alone, and anything missing is installed at the commit recorded in
`.claude/external-skills.lock.json`. `--update` re-resolves each declared `ref`
and rewrites the lock, which is the only thing that moves a pinned commit — so
an upgrade arrives as a reviewable diff of both the lock and the skill content.

The script refuses any skill whose name begins with `koras-`, so an external
skill can never displace one of ours.

## How to add a new Koras skill

1. Create `.claude/skills/koras-<name>/SKILL.md` with frontmatter:

   ```markdown
   ---
   name: koras-<name>
   description: <one line — this is what Claude matches on>
   ---
   ```

2. Add it to the routing list in `.claude/CLAUDE.md`.
3. Add it to `KORAS_COMMON_SKILLS` in
   `generators/create-koras-app/src/validation/claude-config.ts`. That single
   list drives post-write validation and the generator tests.
4. Add a routing row to both `profiles/*/template/CLAUDE.md.hbs` if it is worth
   routing to from a generated project.
5. `pnpm --filter create-koras-app test`.

Nothing else. The skill reaches every generated project as part of the shared
asset — there is no per-profile copy to remember.

## How to add a new application profile

1. `profiles/<profile>/manifest.yaml` and `defaults.yaml`, including the
   `.claude` shared asset. Add the profile to the `profile` enum in
   `generators/create-koras-app/src/profiles/types.ts` and to
   `KorasProjectManifestSchema` in `src/generation/project-manifest.ts`.
2. `profiles/<profile>/template/.claude/skills/koras-profile-<profile>/SKILL.md`
   — the overlay, stating what the repository is, what it owns, and the rules
   that override convenience.
3. `profiles/<profile>/template/CLAUDE.md.hbs`, naming that overlay in its
   "Before implementing anything" section.
4. Register the overlay in `CLAUDE_PROFILE_SKILLS` in
   `src/validation/claude-config.ts`. Validation throws for a profile with no
   declared skill rather than silently checking nothing.
5. Extend `tests/claude-config.test.ts` — in particular the negative assertions
   that the new profile does not receive the other profiles' instructions.

## Bringing an existing project back into alignment

A project generated before this configuration existed has no `.claude/`. It is
a shared asset, so the generator can re-copy it in place without touching
anything else in the repository:

```bash
pnpm create-koras-app <slug> --profile <profile> \
  --output-dir <parent-of-project> --refresh-modules
```

`--refresh-modules` re-copies **only** the declared shared assets — the
Terraform modules and `.claude/`. Everything else in the project, including
application source, is left exactly as it is. It reports each file it would
change; add `--dry-run` to see the list without writing.

The profile overlay is template-owned rather than a shared asset, so it needs
the path-refresh form:

```bash
pnpm create-koras-app <slug> --profile <profile> \
  --output-dir <parent-of-project> \
  --refresh .claude/skills/koras-profile-<profile>/SKILL.md \
  --refresh CLAUDE.md
```

Naming a path explicitly is the operator saying "this file is the generator's".
`CLAUDE.md` in particular is often edited in a live project — run
`--check-drift --all` first, and merge rather than overwrite if it has diverged.

## Known limitation

`generator.template_digest` in `.koras/project.yaml` is a digest of
`profiles/<profile>/` only. It moves when a profile overlay changes and does
**not** move when the common `.claude/` tree changes — the same gap that already
applies to the shared Terraform modules. A project can therefore be behind on a
common skill while its digest still matches. Until that is addressed, use
`--refresh-modules --dry-run` rather than the digest to answer "is this
project's Claude configuration current?".
