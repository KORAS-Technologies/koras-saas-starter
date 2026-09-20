# Koras Agent Inventory

The shared engineering registry contains **40 agents**. This file is generated
from the same data as `.claude/orchestration/agent-registry.yaml`, and the
orchestration validation test asserts that the count here, the count in the
registry, and the number of definition files on disk are all the same number.

Product-owned domain agents are overlays under `.claude/domain/` and are
deliberately **not** counted here — the shared catalog stays domain-neutral and
identical in every KORAS product.

Each agent also declares what it is FOR, from the `capability_vocabulary` in
the registry — eighteen capabilities over forty agents, coarser than an agent
and finer than a category. The Orchestrator asks which capability a change
needs before it asks which agent, which is the difference between selecting a
minimum set and selecting a familiar one.

## By category

| Category | Agents |
|----------|-------:|
| orchestration | 1 |
| planning | 7 |
| development | 9 |
| testing | 10 |
| review | 5 |
| documentation | 2 |
| delivery | 6 |
| **Total** | **40** |

## The registry

"Modifies production code" is the agent's own declared authority. `limited`
means tests, fixtures, documentation or configuration only — never production
source.

| # | ID | Category | Role | Modifies production code |
|---:|---|---|---|---|
| 1 | `engineering-orchestrator` | orchestration | Engineering Orchestrator | no |
| 2 | `product-planner` | planning | Product & Feature Planner | no |
| 3 | `business-analyst` | planning | Business Analyst | no |
| 4 | `solution-architect` | planning | Solution Architect | no |
| 5 | `data-architect` | planning | Data Architect | no |
| 6 | `security-architect` | planning | Security Architect | no |
| 7 | `ux-ui-designer` | planning | UX/UI Designer | no |
| 8 | `impact-analysis` | planning | Dependency & Impact Analyst | no |
| 9 | `developer-1` | development | Developer Worker 1 (DEV-1) | yes |
| 10 | `developer-2` | development | Developer Worker 2 (DEV-2) | yes |
| 11 | `developer-3` | development | Developer Worker 3 (DEV-3) | yes |
| 12 | `frontend-specialist` | development | Frontend Specialist | yes |
| 13 | `backend-specialist` | development | Backend / API Specialist | yes |
| 14 | `database-specialist` | development | Database Specialist | yes |
| 15 | `integration-specialist` | development | Integration Specialist | yes |
| 16 | `ai-specialist` | development | AI / LLM Specialist | yes |
| 17 | `workflow-specialist` | development | Workflow & Automation Specialist | yes |
| 18 | `test-data` | testing | Test Data Agent | limited |
| 19 | `unit-test` | testing | Unit & Component Test Agent | limited |
| 20 | `api-integration-test` | testing | API & Integration Test Agent | limited |
| 21 | `e2e-test` | testing | E2E Automation Agent | limited |
| 22 | `manual-qa` | testing | Manual QA Agent | no |
| 23 | `accessibility-qa` | testing | Accessibility QA Agent | limited |
| 24 | `performance-qa` | testing | Performance QA Agent | limited |
| 25 | `security-test` | testing | Security Testing Agent | limited |
| 26 | `ai-evaluation` | testing | AI Evaluation Agent | limited |
| 27 | `bug-triage` | testing | Bug & Failure Triage Agent | no |
| 28 | `code-reviewer` | review | Code Reviewer | no |
| 29 | `architecture-reviewer` | review | Architecture Reviewer | no |
| 30 | `security-reviewer` | review | Security Reviewer | no |
| 31 | `qa-reviewer` | review | QA Evidence Reviewer | no |
| 32 | `privacy-compliance-reviewer` | review | Privacy & Compliance Reviewer | no |
| 33 | `test-documentation` | documentation | Test Documentation Agent | limited |
| 34 | `technical-writer` | documentation | Technical Writer | limited |
| 35 | `migration-upgrade` | delivery | Migration & Upgrade Agent | limited |
| 36 | `devops-cicd` | delivery | DevOps & CI/CD Agent | yes |
| 37 | `observability-sre` | delivery | Observability & SRE Agent | yes |
| 38 | `release-manager` | delivery | Release Manager | limited |
| 39 | `integration-regression` | delivery | Integration & Regression Agent | limited |
| 40 | `final-acceptance` | delivery | Final Acceptance Agent | no |

## Developer concurrency

`developer-1`, `developer-2` and `developer-3` are reusable worker slots, not
three different kinds of developer. At most three run at once, each in its own
Git worktree and branch at the canonical location, and only on work that
impact analysis has shown to be free of file, contract and migration overlap.
See `.claude/orchestration/WORKTREE-STANDARD.md`.

## Independence

No agent reviews, evidences or accepts its own work. The gates marked
`independent` in `quality-gates.yaml` must be closed by an agent that did not
implement the change.

## Domain agents

Each product owns its domain expert(s) under `.claude/domain/<domain>/` and
registers them in its own `domain-registry.yaml`. Domain agents advise and
validate; they do not normally implement production code, and they never
replace the generic engineering gates.
