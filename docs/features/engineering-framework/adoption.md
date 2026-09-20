# Adopting V2.1 in an existing product

V2.1 is an evolution of V2. No agent was added, removed, renamed or merged,
so an existing product keeps its catalogue, its domain overlay and its
history.

**No regeneration is required.** The framework is configuration in
`.claude/`, and a product can take it without rebuilding anything else.

## What to copy

```text
.claude/orchestration/          all of it, replacing the V2 files
.claude/commands/remediate.md   new
.claude/agents/                 the eight files listed in the delta document
.claude/templates/feature/manual-test-results.md
.claude/AGENT-INVENTORY.md .claude/MASTER-PROMPT.md .claude/PRODUCT-USAGE-EXAMPLES.md
.claude/skills/koras-profile-product/SKILL.md
```

Plus the three shared-template fixes, which are not orchestration and are
worth taking on their own:

```text
local/scripts/process-tree.mjs          new
local/scripts/config-typecheck.sh       new
local/scripts/dev-app.mjs local/scripts/dev-service.mjs
local/scripts/doppler-bootstrap.sh
local/config/secrets.manifest
.github/workflows/deploy.yml
.gitignore
```

## What to keep

- `.claude/domain/` — the product's own, untouched by this work.
- `.claude/orchestration/product-profile.yaml` if the product created one.
  Nothing in V2.1 reads a new key from it.

## The one breaking change

**Applicability tokens were renamed.** The mapping is in
`v2-to-v2-1.md`. This matters only for a product that hand-edited
`activation-rules.yaml`, `quality-gates.yaml` or `documentation-policy.yaml`;
a product that took the starter's copies unmodified is unaffected, because it
is replacing all three together.

If a product did edit them, apply the rename to the edits before copying, and
then run the orchestration test — an unrecognised condition now fails rather
than being silently ignored, which is the point of the change.

## Things that behave differently afterwards

| | |
|---|---|
| **Fewer gates re-run** | A change now invalidates only the gates whose declared inputs it touched. A browser-test correction re-runs two product gates instead of everything. |
| **Loops stop** | Six caps, and exhausting one is an escalation to a person rather than another attempt. A product used to unlimited rework cycles will hit a cap eventually, and that is the feature. |
| **Acceptance means less** | `final-acceptance` READY now closes one lifecycle state, not the feature. A feature that deploys is not closed until CI and the environment have reported. |
| **A new required test-case field** | `evidence_purpose`. Existing manual test documents predate it; they are not invalid, and the field applies to cases written from now on. |
| **`next-env.d.ts` becomes ignored** | If a product tracked one, `git rm --cached` it once. Nothing in the estate did as of 2026-09-19. |
| **Deployment can now fail earlier** | Typed preflight runs before the migration and will refuse a malformed value that previously reached a service. That is the intended behaviour, and the first run after adoption is the one most likely to surface a value that was always wrong. |

## Order

1. Copy the shared-template fixes and run a deployment to a non-production
   environment. Typed preflight is the change most likely to find something.
2. Copy `.claude/orchestration/` and the agent, command and template edits.
3. Run the product's own generator or orchestration tests if it has them.
4. Run one small feature through `/orchestrate-feature` and read the
   telemetry at the end. A FAST classification on something trivial, with the
   rejected signals listed, is the cheapest way to see whether the risk model
   behaves sensibly in that product.

## Downstream state

As of 2026-09-19 nothing downstream has V2.1. `docoris`,
`koras-control-plane` and `output/koras-e2e-*` are untouched by this work,
deliberately, and a synchronisation plan is proposed separately rather than
executed.
