# V2 to V2.1 — what changed, and what did not

Read with `docs/ENGINEERING_FRAMEWORK.md`, which describes the result. This
document is the difference, and the defects found on the way.

## New files

| File | Owns |
|------|------|
| `conditions.yaml` | The one applicability vocabulary |
| `risk-model.yaml` | Boundary signals, selection, override |
| `execution-modes.yaml` | FAST, STANDARD, FULL |
| `execution-budget.yaml` | Caps, escalation, the stop report |
| `gate-invalidation.yaml` | Change classes, reuse, remediation, scenarios |
| `lifecycle.yaml` | Feature states, epic acceptance, policy-disabled steps |
| `deployment-awareness.yaml` | Push impact, partial deployment, diagnosis |
| `telemetry.yaml` | The end-of-run report |
| `commands/remediate.md` | Targeted remediation |
| `local/scripts/process-tree.mjs` | Terminating a process tree (shared) |
| `local/scripts/config-typecheck.sh.hbs` | Typed configuration preflight (shared) |

## Changed files

| File | Change |
|------|--------|
| `activation-rules.yaml` | Keyed by condition; triggers moved to `conditions.yaml` |
| `quality-gates.yaml` | Applicability re-expressed; `statuses`; `inputs` per gate; `stage`; four gates added |
| `documentation-policy.yaml` | Conditions re-expressed; `required_by_condition`; timing; evidence runs; manual QA aim; screenshot policy; `evidence_purpose` |
| `workflow.yaml` | `engineering_flow` with two freeze points; rework bounded |
| `agent-registry.yaml` | `capability_vocabulary` and `capabilities` per agent |
| `WORKTREE-STANDARD.md` | Dependency preparation; process-tree teardown |
| `engineering-orchestrator.md` | Classify, plan, reuse, budget, push impact, lifecycle, telemetry |
| `final-acceptance.md`, `bug-triage.md`, `manual-qa.md`, `test-documentation.md`, `technical-writer.md`, `qa-reviewer.md`, `product-planner.md` | One concern each |
| `orchestrate-feature.md`, `plan-next.md`, `agent-status.md`, `manual-test-doc.md` | Matching command behaviour |
| `.gitignore.hbs`, `dev-app.mjs`, `dev-service.mjs.hbs`, `doppler-bootstrap.sh.hbs`, `deploy.yml`, both `secrets.manifest.hbs` | The three shared-template fixes |

## Gates: 20 → 24

Four added, none removed.

| Gate | Owner | Why |
|------|-------|-----|
| `documentation_audit` | `qa-reviewer` | The engineering flow named the stage and no gate existed, so a documentation correction had nothing to re-run — and in practice re-ran everything. |
| `ci_verified` | `devops-cicd` | Local evidence is not pipeline evidence. |
| `deployment_preflight` | `devops-cicd` | Typed configuration, ahead of the migration. |
| `environment_verified` | `observability-sre` | A deployment that finishes is not a deployment that works. |

## The applicability rename

| Was | Is |
|-----|-----|
| `user_facing` | `user_interface` |
| `api_or_integration_or_database` | `[api_or_integration, database_or_data]` |
| `security_risk_triggered` | `security_boundary` |
| `user_or_operator_visible_change` | `documentation_impact` |
| `cross_feature_or_shared_contract_or_release` | `cross_feature_or_release` |
| `business_workflow_or_ui_change` | `business_workflow` + `user_interface` |
| `configurable_or_operational_feature` | `operational_configuration` |
| `security_or_sensitive_data` | `security_boundary` + `sensitive_or_regulated_data` |
| `any_automated_verification_executed` | `automated_verification_executed` |
| `required_for_user_facing_features` (a field name) | `required_by_condition` (a keyed map) |

Four conditions were referenced but declared nowhere: `domain_feature`,
`business_workflow`, `operational_configuration`,
`automated_verification_executed`.

## Defects found while doing the work

Recorded here rather than quietly fixed, because each one is a class rather
than an instance.

**Three vocabularies, zero shared tokens.** Measured before P1. Nothing could
have caught it: the test checked every *agent id* rigorously and had no
source of truth to check a *condition* against.

**A stage with no gate.** P3 added a `documentation_audit` stage to the
engineering flow; no such gate existed. Found in P4 while deriving the
documentation-only scenario, which came out invalidating nothing.

**A gate that would invalidate itself.** If `manual_qa_pass` took
`manual_evidence` as an input, writing down the result would invalidate the
run that produced it — permanently. Same shape for the technical writer's
gate and `documentation`. Both are now asserted.

**A parser that would have swallowed the new column.** `doppler-bootstrap.sh`
reads `name class source` with `read -r`. A fourth manifest column would have
landed in `source` and corrupted **every `derived` row**, silently writing
wrong values into Doppler. Found by reading the parser before editing the
file it reads.

**A retired spelling reintroduced within one phase.** P2 named an elevating
signal `user_facing_workflow`, which contains the `user_facing` token P1 had
retired. P1's own test caught it. Renamed `multi_step_user_workflow`, which
describes the boundary better.

**Two mutation checks that proved nothing.** A mutation script used `\n`
against CRLF files, so the tree was never modified and the suite passed on an
unmutated tree; and a validator test put a Windows-style path on `PATH` in a
POSIX shell, so the real Doppler CLI answered instead of the stand-in. Both
were caught by the output making no sense, not by anything failing. Every
mutation since is verified to have applied before its result is trusted.

**A headline number wrong within one phase.** P4 reported a browser-test
correction reusing 19 of 21 gates. P5 added `ci_verified`, and the honest
figure became 21 of 24 — CI genuinely must re-run. The direction is worth
noting: the claim got more accurate, and the expensive reuses were untouched.

## What was deliberately not built

- `templates/feature/execution-plan.md`. The execution plan is an output
  contract, not a mandatory per-feature document; adding ceremony in the
  phase whose purpose is removing it would be the wrong trade.
- Stored routing metadata for gate ownership, activating conditions and
  blocking authority. All three are derived by the test from the files that
  already own them, and the registry is asserted to carry no `gates:` field.
- An epic-level gate list. Epic acceptance is prose; gates for it would be
  more orchestration than this work should add.
