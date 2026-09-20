# Product Usage Examples

How the multi-agent framework is actually used in a generated KORAS product.

## 1. Bootstrap the product's domain layer

The starter ships the domain contract, template and example — and no domain
facts. Create the product's own layer:

```text
.claude/domain/
  domain-registry.yaml              copied from domain-registry.example.yaml
  <domain>/
    domain-expert.md                copied from DOMAIN-AGENT-TEMPLATE.md
    knowledge/*.md                  authoritative domain notes
```

One directory per domain, named for the domain this product actually has —
`documents/`, `matters/`, `policies/`. Point the registry at the product's
authoritative documentation. Domain rules never go into the 40 shared agents,
which are identical in every KORAS product.

## 2. Ask what to build next

```text
/plan-next Review the current implementation and roadmap. Recommend the next
three dependency-ready features. Generate the implementation prompt for the top
recommendation, but do not start it.
```

You get three ranked recommendations and one ready-to-run prompt. Nothing
starts: the Planner recommends, and you authorize.

## 3. Approve and run one feature

```text
/orchestrate-feature APPROVED: DOC-127 Scheduled Document Requests. Use the
implementation prompt produced by /plan-next. Do not merge.
```

The Orchestrator runs impact analysis, selects only the agents the feature
needs, allocates one worker to an isolated worktree, and enforces the gates.

## 4. Run three independent features at once

```text
/run-parallel APPROVED: DOC-127 Scheduled Requests; DOC-129 Extension Requests;
DOC-135 Dashboard Filters. Validate dependencies first. Assign DEV-1/2/3 only if
safe; otherwise explain the required sequence. Do not merge.
```

Overlap analysis comes first. If DOC-127 and DOC-129 both touch the same
migration, they are sequenced and you are told why — three workers is a
ceiling, not a target.

## 5. Produce the manual test evidence package

```text
/manual-test-doc DOC-127. Execute the manual cases in the available test
environment, capture real step screenshots, and produce the guide, results and
evidence package. If the environment is unavailable, mark execution BLOCKED
rather than inventing evidence.
```

## 6. Fix one failure without restarting the feature

```text
/remediate DOC-127. The browser test asserts the old empty-state copy. Root
cause established from the run output. Fix the assertion only.
```

The change class is `e2e_test`, so the browser gate, CI and acceptance
re-run, and the other twenty-one gates are reused — including manual QA,
accessibility, both reviews and regression. You are told which, and why.

## 7. Check where everything stands

```text
/agent-status
```

Worker assignments, active worktrees, feature stages, blocking findings, the
ready and blocked queues, and the next human gate.

## 8. The feature documentation structure

Defined authoritatively in
`.claude/orchestration/documentation-policy.yaml`. Templates for every file are
in `.claude/templates/feature/`.

```text
docs/features/<feature-id>-<slug>/
  requirements/
    user-story.md
  design/
    technical-design.md
    functional-design.md
    ux-design.md
  testing/
    test-plan.md
    automated-test-results.md
    regression-results.md
    manual/
      manual-test-guide.md
      manual-test-results.md
      screenshots/
        <test-case-id>/
          step-01-<description>.png
          step-02-<description>.png
  security/
    threat-model.md
    security-review.md
  documentation/
    user-guide.md
    admin-guide.md
  release/
    release-notes.md
```

## 9. The model, in one paragraph

The 40 shared agents are **definitions, not 40 running processes**. Almost all
of them are dormant for any given feature. The Planner recommends; a human
authorizes; the Orchestrator activates the minimum required set and allocates
up to three isolated developer workers; no agent verifies or accepts its own
work; and merge and production release stay human decisions.

What V2.1 added is not more orchestration. It is the ability to answer two
questions the framework previously could not: *did anything relevant to this
gate change* — so a passed gate can be reused instead of re-run — and *when
do we stop trying* — so a loop ends in a person rather than in another
attempt.
