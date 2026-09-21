# G7R2-F01 — execution plan

Published **before** implementation, per `.claude/orchestration/workflow.yaml`. The
Orchestrator owns this document; the Planner owns
`testing/runs/2026-09-21-01/planner-output.txt` and owns nothing here.

| | |
|---|---|
| **Feature ID** | `G7R2-F01` |
| **Title** | Honour the surfaced `accessibility.highContrast` setting |
| **G7 round** | R2 |
| **Repository** | `koras-saas-starter` (the factory), branch `develop`, base commit `48e762a` |
| **Approved by** | The repository owner, 2026-09-21, human gate `start_planner_recommended_feature` |
| **Execution mode** | **FAST** |

## What is wrong today

`accessibility.highContrast` is declared in the product's settings catalogue
(`services/api/koras_api/settings_catalogue/standard.py:514`) with `surfaced` at its
default `True`, a `TOGGLE` control, and `Scope.GLOBAL_ORG_USER`. It is listed as a
known key (`packages/ui/src/settings/types.ts:97`), translated into English, German
and Spanish, and drawn on `/dashboard/preferences`.

**Nothing reads it.** A customer can turn high contrast on, the value is stored,
resolved and returned by `GET /settings/effective` — and the product looks exactly
the same. That is the PLAT-DEF-001 class: a control that does nothing, which is the
precise failure `surfaced=False` was introduced four days before this run to prevent.
Its two siblings, `accessibility.reducedMotion` and `accessibility.fontScale`, are in
the same state; this feature closes one third of the defect and names the rest.

## Scope

**In scope — two production files, both inside one package:**

- `profiles/product/template/packages/ui/src/shell/product-shell.tsx.hbs`
- `profiles/product/template/packages/ui/src/styles/tokens.css`

**In scope — tests and evidence:**

- `generators/create-koras-app/tests/product-shell.test.ts`
- `generators/create-koras-app/tests/product-settings.test.ts`
- `profiles/product/template/e2e/` (one browser assertion)
- this feature directory

**Explicitly out of scope, and touching any of them is scope creep:** the settings
catalogue, `types.ts`, `packages/i18n`, the preferences page, `apps/**`,
`services/**`, `profiles/_shared/**`, any migration, `accessibility.fontScale`,
`accessibility.reducedMotion`, GR-248, GR-250, PLAT-DEF-013, E18-F01, E18-F02,
`koras-control-plane`, `docoris`.

## Risk classification

Deterministic, from `.claude/orchestration/risk-model.yaml`, evidenced in
`testing/runs/2026-09-21-01/impact-analysis-output.txt` section 5.

**Floor signals fired: none.** All ten walked individually:
`authentication_or_session`, `authorization_or_permission`, `tenant_isolation`,
`secret_or_credential_handling`, `destructive_or_irreversible_data_change`,
`storage_data_boundary`, `payment_or_subscription`, `ai_authority_or_data_reach`,
`sensitive_or_regulated_data_path`, `platform_contract` — not fired. The change reads
one already-resolved boolean out of a React context and re-declares CSS custom
properties. It defines, grants, evaluates and relaxes no permission; it reaches no
query, policy, cache key or join; it adds no data path.

**Elevating signals fired: none.** All eight walked.

**Signals this looked like and is not** — the half of the rationale that makes a
classification arguable:

- `multi_step_user_workflow`. It looked like one because the demonstration is "change
  a setting, then observe a page". Rejected: the boundary is *a sequence a person
  completes, where a wrong state leaves them stuck*, and its `not_this` is *one
  screen's styling*. Nothing here has a half-completed state.
- `security_boundary`. It looked like one because the word *accessibility* sits beside
  *permissions* on the same preferences page. Rejected on the condition's own note:
  the boundary, not the subject area. A contrast marker decides appearance.
- `architecture_impact`. It looked like one because this is the first component to
  read a setting outside the data table. Rejected: `useSettingValue` is an existing
  pattern with an existing consumer, the token cascade is the existing mechanism, and
  nothing crosses a package boundary.

**Selection rule that decided the mode:**
`no_signal_and_every_fast_requirement_holds → FAST`. Every FAST requirement in
`execution-modes.yaml` holds and was checked individually: no signal; one package
(`packages/ui`, confirmed by impact analysis section 1 against a rejected alternative
that would have needed `apps/`); no migration and no stored schema or policy; no new
runtime dependency; no contract another repository reads.

**No human override.** The mode was not raised and not lowered.

## Change classes — and a finding about them

Expected classes, from `.claude/orchestration/gate-invalidation.yaml`:

| Edit | Intended class |
|---|---|
| `packages/ui/src/shell/product-shell.tsx.hbs` | `frontend_code` |
| `packages/ui/src/styles/tokens.css` | `frontend_code` |
| `generators/create-koras-app/tests/*.test.ts` | `automated_test_node` |
| `profiles/product/template/e2e/**` | `e2e_test` |
| this directory | `feature_scope`, then `documentation` and `manual_evidence` |

**Impact analysis found that the first two do not actually match.** The globs are
written for a generated product root — `packages/**`, `apps/**`, `e2e/**` — and the
factory holds the same code at `profiles/product/template/packages/**`. `packages/**`
is not `**/packages/**`, so it does not match; and no change class in the file matches
a `.css` path at all, in either tree. A classifier reading the diff literally would
report this feature as "a Node test changed" and would therefore reuse
`accessibility_pass`, `e2e_pass`, `screenshot_evidence_complete` and
`independent_code_review` — every gate that most needs to run.

This is recorded as a framework finding (see `release/framework-findings.md`) and is
**not** routed around: the classes above are applied by their evident intent, and the
gate decisions in this run are made as though `frontend_code` fired, which it should.

## Agent activation — capability-based routing

`always_consider` for FAST is five agents; the conditions met add the rest. Nothing
else is invoked.

| Agent | Capability needed | Work assigned | Why activated |
|---|---|---|---|
| `engineering-orchestrator` | coordinate | this plan, routing, gate decisions, telemetry | FAST `always_consider` |
| `product-planner` | plan_product | the three candidates and the recommendation | the human asked what to build; completed before this plan existed |
| `impact-analysis` | analyse_impact | containment, reach, conditions, classes, signals | FAST `always_consider` |
| `ux-ui-designer` | design_solution | which tokens change, and to what, at AA | `user_interface` |
| `developer-1` | implement | both production files and the tests | the developer pool |
| `frontend-specialist` | implement | consulted by developer-1 on the token cascade | `user_interface` |
| `unit-test` | verify_automated | the Node and Python suites, executed | FAST `always_consider` |
| `e2e-test` | verify_browser | the browser assertion at two widths | `user_interface` |
| `accessibility-qa` | verify_human | WCAG 2.2 AA contrast, keyboard, focus | `user_interface` |
| `manual-qa` | verify_human | the manual cases against a running product | `user_interface` |
| `test-documentation` | record_evidence | the manual guide, the results, the screenshots | `user_interface` |
| `qa-reviewer` | review_independent | the evidence audit and the documentation audit | `user_interface`, `documentation_impact` |
| `code-reviewer` | review_independent | the independent review | FAST `always_consider` |
| `technical-writer` | document | the user-facing note | `documentation_impact` |
| `final-acceptance` | accept | the Definition of Done walk | FAST `always_consider` |
| `devops-cicd` | deliver | `ci_verified`, `deployment_preflight` — post-merge | gates apply `always`; no mode staffs this agent |
| `observability-sre` | deliver | `environment_verified` — post-merge | as above |

**Activated: 17 of 40.** Representative agents deliberately **not** activated, with
the reason each is unnecessary:

| Not activated | Why not |
|---|---|
| `business-analyst`, `solution-architect` | FAST trims exactly these two. Their gates still apply and are closed under `owner_optional_closure` — below. |
| `security-architect`, `security-reviewer`, `security-test` | `security_boundary` not met. Invoking them would be the over-activation the framework exists to stop, and would teach everybody that a security review means nothing. |
| `data-architect`, `database-specialist`, `migration-upgrade` | No schema, no migration, no policy, no data. |
| `backend-specialist`, `integration-specialist`, `api-integration-test` | No server code and no endpoint change. The value is already served. |
| `ai-specialist`, `ai-evaluation` | No model-facing behaviour. |
| `workflow-specialist`, `performance-qa`, `test-data` | No background work; no hot path; the existing fixtures suffice. |
| `privacy-compliance-reviewer` | No personal, sensitive or regulated data. |
| `architecture-reviewer` | `architecture_impact` not met; and FAST is not FULL. |
| `integration-regression`, `release-manager` | One feature, no converging work, no release assembly. |
| `bug-triage` | Activated only on `gate_failure`. Not applicable yet, and will be if a gate fails. |
| `developer-2`, `developer-3` | See parallelism. |

## Parallelism

**PARALLELISM_APPLICABLE: NO. DEVELOPER_SLOTS_USED: 1 (`developer-1`).**

The Planner assessed parallel safety per candidate and returned NO for all three. The
two production files are a single cohesive change: the marker on the shell root is
meaningless without the token override, and the override is dead without the marker.
Splitting them across two worktrees would produce two branches neither of which can be
verified alone, and a merge whose combined behaviour nobody tested — precisely the
seam `workflow.yaml`'s `pre_parallel_checks` exist to refuse.

The alternative offered at the approval gate was to run `G7R2-F02` concurrently on
`developer-2` purely to exercise three slots. The human approved F01 alone. A
legitimate NO is recorded here rather than a manufactured YES.

**Worktree.** One worktree at the canonical location,
`../.koras-worktrees/koras-saas-starter/G7R2-F01/`, branch
`feature/G7R2-F01-honour-high-contrast`. Never inside the repository — `.claude/` is
copied verbatim into every generated project, and a worktree created inside it shipped
a second copy of the starter on 2026-09-15.

## Gates

Selected by the conditions met, not by the mode. A mode may not switch a gate off.

| Gate | Applies because | Owner | Expected |
|---|---|---|---|
| `requirements_ready` | `always` | business-analyst | PASS via `owner_optional_closure` |
| `impact_analyzed` | `always` | impact-analysis | PASS — already executed |
| `architecture_ready` | `always` | solution-architect | PASS via `owner_optional_closure` |
| `implementation_complete` | `always` | developer-1 | PASS |
| `automated_tests_pass` | `always` | unit-test | PASS, executed output |
| `e2e_pass` | `user_interface` | e2e-test | PASS, executed output |
| `manual_qa_pass` | `user_interface` | manual-qa | executed against a running product |
| `screenshot_evidence_complete` | `user_interface` | test-documentation | genuine captures |
| `accessibility_pass` | `user_interface` | accessibility-qa | PASS |
| `independent_code_review` | `always` | code-reviewer | independent of developer-1 |
| `qa_evidence_audit` | `user_interface` | qa-reviewer | independent |
| `documentation_complete` | `documentation_impact` | technical-writer | PASS |
| `documentation_audit` | `documentation_impact` | qa-reviewer | one audit, after quality freeze |
| `final_acceptance` | `always` | final-acceptance | READY or NOT READY |
| `ci_verified` | `always`, post-merge | devops-cicd | the run for the pushed commit |
| `deployment_preflight` | `always`, post-merge | devops-cicd | see applicability below |
| `environment_verified` | `always`, post-merge | observability-sre | see applicability below |

**Not applicable, with the reason:** `api_integration_tests_pass` (no
`api_or_integration`, no `database_or_data`), `architecture_review`, `security_review`,
`privacy_review`, `ai_evaluation`, `regression_pass`, `domain_review` (the factory
carries no `.claude/domain/` registry; it authors the overlay rather than owning one).

**Manual QA is required and is not exempted.** `documentation-policy.yaml`
`manual_qa.required_when`: the change alters something a person sees, and its
correctness depends on what the browser actually does — a token that resolves but does
not visibly re-skin the shell is exactly the failure being fixed. The
`not_required_when` clause "automated verification observes exactly what a person
would" does **not** hold: a template-text assertion proves the rule was written, not
that anything rendered.

## Owner-optional closures

Two, both permitted: FAST is listed in each gate's `owner_optional_in`, neither gate is
`independent`, and all seven required fields are recorded — here, before the gate came
due, rather than afterwards.

| field | `requirements_ready` | `architecture_ready` |
|---|---|---|
| gate | `requirements_ready` | `architecture_ready` |
| normal_owner | `business-analyst` | `solution-architect` |
| mode | FAST | FAST |
| owner_not_invoked_because | FAST's `always_consider` trims exactly this agent; standing up a requirements pass for a change whose whole requirement is "the control that is already specified, translated and drawn must now do what it says" would be the cost the mode exists to avoid, paid anyway. | As above. A change that stays in one package, adds no dependency, alters no stored schema and introduces no new pattern has answered the architecture question by being that change. |
| rationale | The requirement is fully stated by the existing setting definition: key, data type, default `False`, scope, control, and three translations already agreed. Acceptance criteria are in `requirements/user-story.md` and are testable. Nothing about *what done means* is open. | Impact analysis established the containment point, the rejected alternative and the reason (`impact-analysis-output.txt` sections 1 and 7): the marker goes on an element that already exists inside `packages/ui`, read through an existing hook with an existing consumer, and the override follows the existing `light-dark()` token cascade rather than a second mechanism. No new pattern, no boundary crossed. |
| closed_by | `engineering-orchestrator` | `engineering-orchestrator` |
| recorded_at | 2026-09-21T16:59Z, in this plan at publication | 2026-09-21T16:59Z, in this plan at publication |

## Primary evidence — declared before the validating action

Per `documentation-policy.yaml` `primary_evidence`. This change is made in response to
an observed defect, so the block is required. It is written now, while the outcome can
still be wrong.

| field | value |
|---|---|
| **type** | `screenshot` |
| **producer** | `manual-qa`, executing the manual cases against a running generated product |
| **raw_evidence_location** | `testing/manual/screenshots/G7R2-F01-TC01/`, and the run directory under `testing/runs/` for the same session |
| **independent_verifier** | `qa-reviewer`, which did not produce it, reviewing the retained captures against the claim |
| **claim_proved** | That with `accessibility.highContrast` resolved true, the signed-in shell renders with the high-contrast token set — a visible, before-and-after difference in the same browser, same build, same account, same page — and that with it false the page is unchanged from today. |
| **claim_not_proved** | It does **not** prove the contrast ratios meet WCAG 2.2 AA: that is `accessibility-qa`'s measurement, against computed values, and a screenshot cannot establish it. It does not prove the setting persists across sessions, which is the settings framework's property and not this change's. It does not prove anything about `fontScale` or `reducedMotion`, which remain dead. And it does not prove the override reaches components that hardcode a colour instead of using a token — only that the tokens themselves changed. |

The prediction, stated before the capture: the header, sidebar and page background
will change together, because all three resolve through `var(--brand-*)`; anything
that does **not** change is a component bypassing the token layer, and finding one is
a result rather than a failure of the run.

## Budgets

From `.claude/orchestration/execution-budget.yaml`, per feature, not per gate:
`max_gate_retries` 1, `max_test_fix_cycles` 2, `max_reviewer_cycles` 2,
`max_documentation_audits` 1, `max_final_acceptance_attempts` 2,
`same_agent_max_invocations` 2. Counters do not reset on a new commit, a new worktree,
a new session or a targeted remediation. Exhausting one is a stop, and the stop report
carries all five fields.

## Merge, push and deployment implications

Merging to `develop` and pushing triggers **CI**, **Security** and **Generator
Integration** on the pushed commit. Generator Integration is the only thing in this
estate that renders the generated application in a browser, so it is the gate that
would catch a shell that fails to render — and it has been cancelled at its 30-minute
limit before, on a crash that read as a slow suite.

The factory **deploys nothing of its own**: it has no dev environment, no Fly
application and no Vercel project. `deployment_preflight` and `environment_verified`
are therefore `NOT_APPLICABLE` for this feature with that reason recorded, not
`PENDING`. `koras-e2e-shop` and `docoris` receive this change only by a hand-carried
sync, which is a separate decision and is not part of R2.

No merge happens without the `merge_to_protected_branch` human gate.
