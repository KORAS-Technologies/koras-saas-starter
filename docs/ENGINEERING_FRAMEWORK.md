# The product engineering framework

How a generated KORAS **product** decides which of its forty agents to run,
which gates apply, what may be reused, when to stop, and when a feature is
actually finished.

This is the architecture. The phase-by-phase design, the V2 → V2.1 delta and
the upgrade path are in `docs/features/engineering-framework/`, and the
decision behind it is `docs/adr/0010-koras-engineering-framework-v2-1.md`.
The framework itself is configuration, not code: it lives at
`profiles/product/template/.claude/orchestration/` and is copied into every
product the generator builds. The Control Plane does not receive it.

## What it is for

Forty agent definitions and the rules that decide which of them run. Almost
all of them are dormant for any given feature. The framework's whole job is
to answer four questions the same way twice:

| Question | Answered by |
|----------|-------------|
| What kind of change is this? | `conditions.yaml` |
| How much machinery does it get? | `risk-model.yaml`, `execution-modes.yaml` |
| Which gates apply, and which may be reused? | `quality-gates.yaml`, `gate-invalidation.yaml` |
| When do we stop trying and ask a person? | `execution-budget.yaml` |

## The files, and what each one owns

```text
.claude/orchestration/
  conditions.yaml            The one applicability vocabulary
  risk-model.yaml            Boundary signals -> execution mode
  execution-modes.yaml       FAST, STANDARD, FULL
  agent-registry.yaml        The 40 agents and what each is for
  activation-rules.yaml      Condition -> the agents it brings in
  workflow.yaml              The engineering flow, and two freeze points
  quality-gates.yaml         The gates, their statuses, and their inputs
  gate-invalidation.yaml     Change classes, reuse, targeted remediation
  execution-budget.yaml      Caps, escalation, the stop report
  lifecycle.yaml             Feature states, through deployment to closed
  deployment-awareness.yaml  Push impact and partial deployment
  documentation-policy.yaml  Documents, evidence, manual QA, screenshots
  telemetry.yaml             What a run reports about itself
  definition-of-done.md      What done means, condition by condition
  WORKTREE-STANDARD.md       Worktree location, preparation and teardown
```

Every one of them is validated by
`generators/create-koras-app/tests/orchestration.test.ts`. This is
configuration describing other configuration, which fails silently: a gate
that names a condition nobody declared simply never fires, and nothing goes
red. That test is what makes it fail loudly.

## One vocabulary

A **condition** is a fact about a change — `user_interface`,
`security_boundary`, `database_or_data`. Eighteen of them, declared once, and
every other file's applicability comes from that list.

Before this existed there were three vocabularies. Measured on 2026-09-19,
`activation-rules.yaml` declared fourteen conditions, `quality-gates.yaml`
matched on ten and `documentation-policy.yaml` on five, and **the number of
tokens shared by all three was zero**. `user_interface`, `user_facing` and
`business_workflow_or_ui_change` were three spellings of one question. A test
now refuses an undeclared condition, an unconsumed one, and every retired
spelling.

## Risk is a boundary, never a subject area

The execution mode comes from which **boundaries** a change touches. Ten
floor signals force FULL; eight elevating signals select STANDARD; a change
with no signal at all, inside one package, with no migration and no new
dependency, earns FAST.

Every signal carries both a `boundary` (what must actually be touched) and a
`not_this` (the nearby change that looks like it and is not), and a test
requires both. `storage_data_boundary` means object keys, classification,
retention and who may read an object — *not* the wording on the files page.
`ai_authority_or_data_reach` means what a tool may do and what a prompt may
reach — *not* the wording of assistant output.

The rule matters in both directions, and the second is worse: a change that
never mentions storage and quietly widens what a tool may read is a floor
signal, and a label matcher would call it a copy fix.

A human may always raise a mode. Lowering one requires a written rationale
that names **each waived floor signal individually**, and no agent may do it.

## A mode changes cost, never standards

FAST, STANDARD and FULL differ in planning depth, evidence depth and whether
gate results may be reused across a code freeze. A mode cannot switch off a
gate whose condition is met, cannot waive independence, and cannot satisfy a
human gate — all three are asserted. FULL adds one agent to STANDARD. It is
not an instruction to run everything.

## Gate reuse

Each gate declares the change classes its result depends on. A gate is
invalidated when a change touches one of its inputs, and reused when it does
not. The matrix is derived from those declarations rather than written out,
because a separate table would be a second copy of the gate list.

Worked, and asserted mechanically:

| The change | Invalidates | Reuses |
|------------|-------------|--------|
| A browser test only | `e2e_pass`, `ci_verified`, `final_acceptance` | 21 of 24, including manual QA, accessibility, both reviews and regression |
| Documentation only | `documentation_audit`, `ci_verified`, `final_acceptance` | 21 of 24 |
| Deployment configuration only | the deployment gates | every product gate |

Reuse is a fact about the diff. Elapsed time, a slow gate, a flaky gate and
"nobody expects it to have changed" are all listed as **not** reasons, and
the gate result record has no confidence field to hide one in.

A gate's own output is never among its inputs — otherwise writing the manual
evidence would invalidate the run that produced it, permanently.

## Nothing loops forever

Six caps, one escalation table, two outcomes: `HUMAN_REVIEW` and `BLOCKED`.
Both stop the agent. A *retry* is a gate re-run with nothing changed, of
which one is allowed; a *cycle* is a re-run after a fix, and that is what the
caps bound. Counters never reset on a new commit, branch, session or
remediation — only on closure, or a human granting more with a reason.

Two freeze points decide what a late change costs. After **code freeze**, a
product-code change invalidates gates and spends budget. After **quality
freeze**, a documentation correction invalidates the documentation audit and
acceptance and nothing else — unless the document was right and the code was
wrong, which is an implementation defect found by writing prose and is
recorded as one.

## A feature is not done when the local tree says so

Eleven states, from `PLANNED` to `CLOSED`. `final-acceptance` reporting READY
closes exactly one of them, and it is a verdict about a local tree.

Three gates are `post_merge` — `ci_verified`, `deployment_preflight`,
`environment_verified` — because none of them can run before a merge. Local
evidence never satisfies one, however identical the command was.

A step switched off by policy is `NOT_APPLICABLE_BY_POLICY`: not a failure,
and not something nobody wanted. Product-side Control Plane registration is
the standing case — see `docs/FOLLOW_UPS.md`, F2b and F3.

## Deployment is not one fact

A push to `develop` runs CI and deploys the whole of dev, migrations
included. Nobody is asked to approve a push without being told that.

A deployment records a state for **every** component, including the ones a
run never reached, because a component with no entry is indistinguishable
from one that quietly succeeded. `FAILED` and `NOT_DEPLOYED` are different
things. A migration is never re-run because a later stage failed: the worker
crash-looping says nothing whatever about the schema. An unknown deployment
state is `BLOCKED`, not a guess.

Typed configuration is validated **before** the migration, by
`local/scripts/config-typecheck.sh`. It reads only settings the manifest has
given a type, refuses any whose name looks like a credential even when typed,
and never prints a value.

## Evidence is aimed, and appended

Manual QA is required where a person can reach the surface, complete the
sequence, or see the boundary — and is not softened anywhere else: every
verdict rule, the no-fabrication rules and PASS/FAIL/BLOCKED all survive
unchanged, and a test asserts they do.

Screenshots have no maximum and no quota. A capture earns its place by
proving something a sentence could not, and where that is not obvious the
case says in a phrase what it proves. Raw runs are appended at
`testing/runs/<run-id>/`, written once, never edited; a failed run stays,
because a directory in which every run passed is a claim rather than a
record.

## Stories and epics

A story is accepted on its own gates and closes without waiting for its
siblings — a story that cannot close cannot be built on. The epic pass runs
once, after the last story, and tests the **seams**, reusing the story gates.
The exception: a floor-signal story touching a surface a sibling also touches
runs its cross-story check immediately, because deferring a tenancy seam
means building on it first.

## What it reports

At the end of a run: the mode and the signals behind it, agents invoked
against agents available, gates executed against gates reused, every loop
count against its cap, the lifecycle state reached, and any escalation.
Engineering telemetry only — no customer data, nothing transmitted, nothing
stored outside the repository.

## What it deliberately is not

- **Not executable.** Every rule here is followed by an agent reading it. A
  `koras orchestrate` command that computed routing and reuse directly is the
  obvious next step and is not built.
- **Not a gate-result store.** The record's fields are specified; nothing
  writes them automatically yet.
- **Not measured across features.** One report per run, compared by hand.

Those three are the recommended next steps, in that order, and they are
recorded in `docs/features/engineering-framework/README.md` rather than
started.
