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
  acceptance-batching.yaml   BUILD vs IMMEDIATE, and the validation batch
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

FAST, STANDARD and FULL differ in planning depth and in whether gate results
may be reused across a code freeze. They do **not** differ in evidence: gates
are selected by the conditions a change meets, and whether a *person* must
satisfy one is decided by `documentation-policy.yaml`. A mode that could
lower evidence would be a mode switching off a gate, which is forbidden two
lines below — so the `evidence_depth` field that once implied otherwise was
removed on 2026-09-20, after the first real FAST run showed nothing read it. A mode cannot switch off a
gate whose condition is met, cannot waive independence, and cannot satisfy a
human gate — all three are asserted. FULL adds one agent to STANDARD. It is
not an instruction to run everything.

An agent set is also not a gate list. `always_consider` is a *planning*
default; it says who is staffed before anyone knows what the change touched.
`devops-cicd` and `observability-sre` are in no mode's set and their three
post-merge gates run for every feature, which is the general rule: a gate
whose owner the mode did not plan for invokes that owner when it comes due.
The single exception is `owner_optional_in`, declared per gate, on
`requirements_ready` and `architecture_ready` in FAST only. There the
Orchestrator may close the gate itself under `owner_optional_closure` —
recording the gate, the normal owner, the mode, why that owner was not
invoked, the rationale that satisfies the gate, its own identity and the
time. It is on no independent gate and never will be, and standing up a
requirements pass purely to satisfy ownership is the cost the mode exists to
avoid, paid anyway. G7 R1 resolved both gates correctly by judgement and left
no record; the record is the change.

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

Two questions, asked once each: `quality-gates.yaml` decides whether a gate
*concerns* a change, and `documentation-policy.yaml` decides whether a
*person* must satisfy it. Each names the other rather than answering both.
Where automated verification observes exactly what a person would, the three
human-evidence gates are NOT_APPLICABLE with the clause named — never PASS,
and never BLOCKED, because "a person was not needed" and "a person was needed
and unavailable" are different facts.

One artefact usually does the proving, and it used to be the least governed
thing in the lifecycle. `primary_evidence` names it in the execution plan
**before** the validating action runs: its type, its producer, where the raw
capture is retained under `evidence_runs`, the agent that did not produce it
who will verify it, and both what it proves and what it does not. Independent
verification is not re-execution — reading the retained capture answers the
verifier's question, and in FAST that is explicitly enough, because a race or
a first-load warning may not reproduce on demand and the least reproducible
defects should not get the weakest evidence. It adds no gate: a change whose
correctness the suite already shows declares that output and is done.

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

## Build now, validate later

A second and unrelated question sits beside "how much machinery does this
change get": *when* does the evidence a feature still owes get produced.
`acceptance-batching.yaml` answers it, and it is deliberately not a fourth
value on `execution-modes.yaml` — that file already changes two things
(planning depth, gate-reuse restriction) and a third, unrelated thing it
changed once before, `evidence_depth`, was removed on 2026-09-20 for reading
as though it controlled evidence while controlling nothing.

A feature is BUILD or IMMEDIATE, never both and never chosen by preference.
BUILD is available only when `risk-model.yaml` selects FAST or STANDARD;
every floor signal already forces FULL, which forces IMMEDIATE, with no
override in either direction. That single rule is the whole of "auth, tenant
isolation, secrets, destructive data, storage, payments, AI authority,
sensitive data and platform contracts keep their gates" — there is no second
subject-area list to fall out of sync with the first.

Seven gates may be deferred by a BUILD feature, flagged individually on the
gate in `quality-gates.yaml` rather than kept in a second table:
`manual_qa_pass`, `screenshot_evidence_complete`, `qa_evidence_audit`,
`e2e_pass`, `documentation_audit`, `regression_pass`, `final_acceptance`. A
BUILD feature reaches `IMPLEMENTED_PENDING_VALIDATION` instead of
`LOCAL_ACCEPTANCE_READY` once implementation, automated tests, targeted
integration coverage, one independent review and its own documentation are
in place — the gates the request behind ADR 0011 called the BUILD minimum,
none of which moved.

Deferred is a timing decision, never a discount: a deferred gate keeps its
independence, its evidence rules and its budget accounting, and runs, later,
in a validation batch — `/validate-batch`, over the features a risk
boundary, a dependency or a milestone actually justifies batching, never a
fixed count. A batch does two things: it runs each feature's own deferred
gates, and it runs the batch-wide seam checks `epic_acceptance` already has a
shape for (cross-feature regression, one end-to-end manual pass, broader
accessibility and security across the combined surface) — reused rather than
duplicated, because a second acceptance vocabulary is how the two come to
disagree about what "accepted" means. See
`docs/adr/0011-koras-engineering-framework-build-validate.md` for the
reconciliation this required and the alternatives it rejected.

## What it reports, and when it may say it

At the end of a run: the mode and the signals behind it, agents invoked
against agents available, gates executed against gates reused, every loop
count against its cap, the lifecycle state reached, and any escalation.
Engineering telemetry only — no customer data, nothing transmitted, nothing
stored outside the repository.

The rules always forbade inventing a number; they did not say when one may be
written down, and that was the same defect wearing a different hat. In G7 R1 a
final count was recorded before the event it counted had happened — nothing
fabricated, just the plan stored where the history goes. So the report is
derived rather than kept. Events are appended as they occur and are immutable;
a correction is an **amendment** naming what it corrects, the previous value,
the reason and the evidence, never an edit; and the summary is generated after
the last applicable lifecycle or gate event, from events plus amendments.
Where the summary and the log disagree the log wins, because the summary is a
reading of the record rather than the record. A metric no event supports is
**UNKNOWN** — not 0, which claims somebody was watching.

## When the agents are not there

`agent-registry.yaml` describes 40 agents and the test checks that description
against the files on disk. Neither says what the tool sees in any one
session, and
those came apart during G7: one long-lived session listed 25 of the 40, a
fresh process listed all 40 from the same commit, and no file had changed.

The dangerous repair is the obvious one — a missing agent looks exactly like a
misfiled one, and flattening the categories or adding a replacement changes a
correct repository to work around a runtime that has since recovered. So
`runtime_discovery` says: before a lifecycle, check that the agents *the plan
selects* are discoverable, not all forty, which would be over-activation paid
at startup. A full sweep is for validating the framework itself. A required
agent that has vanished is `SESSION_OR_TOOL_HEALTH`: stop before its gate,
restart Claude Code, re-check, and resume only if the evidence so far survives
the restart. Never substitute silently, never reorganise the directories, and
never move the canonical count off 40.

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
