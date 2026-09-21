# FW-HARDEN-001 — execution plan

Maintenance cycle against the accepted G7 R2 baseline, commit 7199f85.
Branch `feature/FW-HARDEN-001-post-g7-framework-hardening`. Opened 2026-09-21.

---

## Mode: STANDARD

Selected by `risk-model.yaml`, rule `any_elevating_signal`.

### Floor signals — none fired

| Signal | Why not |
|--------|---------|
| `authentication_or_session` | Nothing authenticates or issues a session. |
| `authorization_or_permission` | No permission is defined, granted, evaluated or enforced. |
| `tenant_isolation` | No query, policy or cache key. |
| `secret_or_credential_handling` | No secret is read, passed or stored. |
| `destructive_or_irreversible_data_change` | No migration and no data path. |
| `storage_data_boundary` | No object key, provider seam or retention rule. |
| `payment_or_subscription` | Nothing priced or charged. |
| `ai_authority_or_data_reach` | No tool authority and no retrieval reach. |
| `sensitive_or_regulated_data_path` | No personal or regulated data. |
| `platform_contract` | **Considered and rejected.** The orchestration files are a contract more than one repository reads, but not the kind this signal names: they are configuration copied into a product at generation time, not a registration payload, public API shape or webhook another repository's code parses at runtime. Changing them here changes nothing in an already-generated repository until somebody syncs it. The reach is real, so it is caught by `cross_feature_convergence` below rather than dismissed. |

### Elevating signals

| Signal | Fired | Boundary touched |
|--------|-------|------------------|
| `cross_feature_convergence` | **yes** | "A contract more than one feature reads." `gate-invalidation.yaml`, `telemetry.yaml`, `quality-gates.yaml` and `definition-of-done.md` are read by every feature that follows, in this repository and in every product generated from it. |
| `schema_change` | no | No table, column, index or policy. |
| `background_work` | no | Nothing runs after a response. |
| `external_integration` | no | No call leaves the estate. |
| `multi_step_user_workflow` | no | No user-facing sequence. |
| `business_rule_change` | no | No customer-visible outcome or entitlement. |
| `deployment_or_infrastructure` | no | No pipeline, image or promotion path changes. |
| `performance_exposure` | no | Test-time only. |

### Selection

First matching rule: `any_elevating_signal` → **STANDARD**.

FAST was checked separately and is not earned regardless: the change does not
stay inside one package — it spans the product template's orchestration
contract and the generator's test package — and it alters a contract more than
one repository reads.

---

## Conditions met

From `conditions.yaml`, and these decide the gates and the documents.

| Condition | Met | Consequence |
|-----------|-----|-------------|
| `architecture_impact` | **yes** | Crosses a package boundary — the product template's contract and the generator's test package — and introduces a path-normalisation step the vocabulary did not have. Activates `architecture-reviewer`. |
| `cross_feature_or_release` | **yes** | A shared contract changed. Activates `integration-regression` and `release-manager`; requires a regression-results document. |
| `documentation_impact` | **yes** | The change makes register rows and framework prose wrong. Activates `technical-writer`. |
| `automated_verification_executed` | **yes** | Requires an automated-test-results document. Activates nobody. |
| `user_interface` | no | Nothing renders. No manual pass, no screenshots, no user guide. |
| `security_boundary` | no | No threat model, no security review document. |
| `business_workflow` | no | No functional design. |
| `operational_configuration` | no | Nothing an operator configures or runs. |
| `sensitive_or_regulated_data` | no | — |
| `database_or_data` | no | — |
| `ai` | no | — |
| `api_or_integration` | no | — |
| `scheduled_or_background` | no | — |
| `performance_sensitive` | no | — |
| `needs_test_state` | no | No fixtures, tenants or named accounts. |
| `release_or_migration` | no | No migration, no dependency upgrade, no promotion. |
| `domain_feature` | no | The factory has no product domain overlay. |
| `gate_failure` | no | At plan time. Revisited if a gate fails. |

Documents therefore required: the four for all features, plus two by
condition. Six, not sixty.

`architecture_impact` deserves a note, because trimming it would have been
easy and wrong. The instinct was to call this a test change and move on. It
crosses a package boundary in the plainest sense — the contract lives in
`profiles/product/template/` and the code that enforces it lives in
`generators/create-koras-app/` — and the path-domain decision is the one
judgement in this cycle that a later reader will either inherit or fight.
That is what `architecture-reviewer` is for.

---

## Agents

Registered in `agent-registry.yaml`: 40. Discoverable: 40.

### Activated — 11

| Agent | Brought in by |
|-------|---------------|
| `engineering-orchestrator` | `always_consider` |
| `impact-analysis` | `always_consider`. Also the agent that found FW-GAP-006 in G7 R2. |
| `business-analyst` | `always_consider` — acceptance criteria, for a scope given as prose |
| `solution-architect` | `always_consider` — the path-domain model |
| `unit-test` | `always_consider` — every deliverable here is a test |
| `code-reviewer` | `always_consider`, independent |
| `final-acceptance` | `always_consider`, independent |
| `architecture-reviewer` | `architecture_impact` |
| `integration-regression` | `cross_feature_or_release` |
| `release-manager` | `cross_feature_or_release` |
| `technical-writer` | `documentation_impact` |

### Excluded — 29

Grouped by reason; every id below is a real registry entry.

| Group | Agents | Why they would find nothing |
|-------|--------|-----------------------------|
| Planning not brought in | `product-planner` | The scope was given, not discovered. |
| Architecture specialists | `data-architect`, `security-architect` | `database_or_data` and `security_boundary` are both unmet. |
| Product implementation | `developer-1`, `developer-2`, `developer-3`, `ux-ui-designer`, `frontend-specialist`, `backend-specialist`, `database-specialist`, `integration-specialist`, `ai-specialist`, `workflow-specialist` | No product code is written. What changes under `profiles/product/template/` is four YAML contracts and one Markdown policy. |
| Security and privacy | `security-reviewer`, `security-test`, `privacy-compliance-reviewer` | No floor signal fired. Their absence is the risk model's prediction, and the independent review is asked to contradict it if it can. |
| Browser and manual evidence | `manual-qa`, `accessibility-qa`, `e2e-test`, `performance-qa`, `qa-reviewer`, `test-data` | Nothing renders; `user_interface` is unmet. |
| Data and API verification | `api-integration-test`, `migration-upgrade` | No schema, no endpoint, no migration. |
| AI | `ai-evaluation` | No model, prompt, tool or retrieval step. |
| Deployment and operations | `devops-cicd`, `observability-sre` | Their post-merge gates still run and still invoke them when due. Exclusion here means not staffed up front, which `execution-modes.yaml` states explicitly. |
| Defect intake and test docs | `bug-triage`, `test-documentation` | No failing gate at plan time, and no test documentation deliverable without `user_interface`. |

7 + 4 activated, 29 excluded, 40 registered. The number to be held to is the
eighth line of the telemetry report: **agents available but not activated —
29**.

---

## Freeze points

| Freeze | Meaning here |
|--------|--------------|
| Code freeze | After the last implementation commit. A line-ending re-checkout that alters no tracked content does not break it — the precedent is G7 R2. |
| Quality freeze | After the independent review. Findings below HIGH are recorded, not fixed. |

---

## Sequence

1. Reproduce all three findings. **Done before this plan was written**, which
   is why the design carries measured numbers rather than expectations.
2. Write the plan documents. This document.
3. Tests first, failing, for FW-DEF-002 and FW-GAP-006.
4. Implement FW-DEF-002.
5. Implement FW-GAP-006.
6. Implement FW-GAP-010 if it stays bounded; leave it open with a
   recommendation if it does not.
7. Targeted validation, then the full starter baseline.
8. Windows CRLF worktree, canonical suite.
9. Independent review.
10. Final acceptance against the current tree.
11. Human merge gate.
12. Register reconciliation and closure.

The derived telemetry summary is written at step 12 and not before — which is
the FW-GAP-010 ruling being followed rather than described.
