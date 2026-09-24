# ADR 0011 — Acceptance evidence may be deferred to a validation batch

**Status.** Accepted, 2026-09-23. Extends ADR 0010; the 40-agent catalogue,
`risk-model.yaml`'s FAST/STANDARD/FULL modes and every existing gate are
unchanged.

**Context.** A process-change request asked the framework to reduce feature
cycle time by letting normal LOW/MEDIUM-risk features skip manual QA,
screenshots, exhaustive E2E, the documentation audit and Final Acceptance at
implementation time, deferring them to a later batch, while auth, tenant
isolation, payments, migrations, security and accessibility kept their
existing gates. The request named its three states BUILD, VALIDATE and FULL.

Two things needed reconciling before any file changed. First, this package
already has a FULL — the risk-model mode selected by a floor signal — and
giving the same word a second meaning inside one framework is the exact
defect ADR 0010's `conditions.yaml` exists to prevent: three files once asked
the same applicability question in three vocabularies with zero tokens in
common, and a fourth vocabulary appearing here would be that failure
returning in a new file. Second, "skip QA and accessibility for normal
features, except when risk requires them" is not a new rule if the risk
model already says which features that is. `risk-model.yaml`'s floor signals
already are the auth/authorization/tenant-isolation/secrets/destructive-data/
storage/payments/AI-authority/sensitive-data/platform-contract list the
request's own HIGH-RISK EXCEPTION names. Writing a second list of the same
subjects would be the change-class-to-gate table ADR 0010 already rejected,
in a new shape.

**Decision.**

1. **A new axis, not a fourth mode.** `acceptance-batching.yaml` answers
   "when does this feature's remaining evidence get produced", which is a
   different question from `execution-modes.yaml`'s "how much machinery does
   this change get". The request's FULL is renamed IMMEDIATE here, because
   this package's FULL already means something else. BUILD and IMMEDIATE are
   the two per-feature dispositions; VALIDATE is not a disposition a feature
   holds, it is the batch process that runs a set of BUILD features' deferred
   gates together — the request's own text describes it as an operation over
   several pending features, not a state one feature is in.

2. **BUILD is derived from risk mode, not enumerated a second time.** A
   feature may be BUILD only when `risk-model.yaml` selects FAST or STANDARD.
   Whenever it selects FULL, the disposition is IMMEDIATE, with no override in
   either direction — an agent may not lower this any more than it may lower
   a risk mode. Because every floor signal already forces FULL, this one rule
   is the whole of "preserve the applicability/risk-based mandatory gates":
   nothing auth-, tenant-, secret-, destructive-data-, storage-, payment-,
   AI-authority-, sensitive-data- or platform-contract-shaped ever reaches
   BUILD, and there is no second list of those subjects to fall out of sync
   with the first.

3. **Seven gates may be deferred, named individually, on the gate itself.**
   `manual_qa_pass`, `screenshot_evidence_complete`, `qa_evidence_audit`,
   `e2e_pass`, `documentation_audit`, `regression_pass` and `final_acceptance`
   carry `deferrable_in_build: true` in `quality-gates.yaml`, the same place
   a gate already declares its `inputs` — because a standalone deferred-gate
   table would drift from the gate list the first time either changed without
   the other. Seventeen gates do not carry the flag and are named
   individually in `acceptance-batching.yaml`'s `never_deferred`, including
   the reason each one is not — `independent_code_review` and
   `automated_tests_pass` because the request's own BUILD minimum requires
   them now; `security_review` and `privacy_review` because they are
   unreachable in BUILD by decision 2; `accessibility_pass` because the
   request's own HIGH-RISK EXCEPTION requires a targeted check now, and only
   the *broader* validation across a combined surface may wait.

4. **The broader check reuses `epic_acceptance`, rather than inventing a
   third acceptance vocabulary.** `lifecycle.yaml` already has a shape for
   "gates a story's own gates could not test, run once after several units of
   work converge": cross-feature regression, one end-to-end manual pass,
   accessibility and security across the combined surface. A validation batch
   runs that same list over the batch instead of an epic's stories. It is not
   a full substitute, because a batch does something an epic pass does not:
   the epic pass only tests seams, because a story already closed its own
   gates before the epic runs; a BUILD feature's own gates were never run at
   all, so a validation batch runs those too, per feature, before it runs the
   seam checks. This distinction is stated explicitly in
   `acceptance-batching.yaml` because it is the one most likely to be missed
   by anyone reusing the epic shape without reading why it fits.

5. **One new lifecycle state, reached instead of `LOCAL_ACCEPTANCE_READY`,
   never in addition to it.** `IMPLEMENTED_PENDING_VALIDATION` sits between
   `TESTING` and `LOCAL_ACCEPTANCE_READY`, `applicable_when` the feature's
   disposition is BUILD. `workflow.yaml`'s engineering flow is not restated
   to add a second stage list; a single note at the point the flow suspends
   points at `acceptance-batching.yaml` instead, because two lists of the
   same sequence is how `lifecycle.yaml`'s own header warns the two come to
   disagree.

**Why not a fourth value on `execution-modes.yaml`.** That file's mode
already changes two things — planning depth and gate-reuse restriction — and
adding a third, unrelated thing it changes (evidence timing) is exactly the
shape of defect `execution-modes.yaml`'s own history warns about:
`evidence_depth` was removed from that file on 2026-09-20 because a mode
field that reads as though it controls evidence and does not is worse than no
field. Evidence *timing* is a real thing to control, unlike the removed
field, so it gets its own file rather than reoccupying the one that already
learned this lesson once.

**Why BUILD is derived rather than authorized per feature by a human writing
a fresh judgement each time.** `risk-model.yaml`'s central discipline is that
mode selection is deterministic and comes from boundary signals, never
preference — "chosen by preference, by deadline, or by how the last feature
was run" is explicitly forbidden there. Making BUILD eligibility a second,
independently-judged decision would reopen exactly the door that file closed,
one file over.

**Why the deferred gates are flagged on the gate rather than listed in
`acceptance-batching.yaml` alone.** Belt and suspenders would be a claim that
the two files might disagree; a single flag, read by both, cannot. The gate
list in `acceptance-batching.yaml` is retained anyway, spelled out, because a
reader auditing what BUILD defers should not have to scan twenty-four gate
definitions in a different file to find seven flags — the flag is the
source of truth, the list is where a reviewer starts.

**Consequences.**

- A BUILD feature reaches `IMPLEMENTED_PENDING_VALIDATION` with its
  implementation, tests, targeted integration coverage, one independent
  review and documentation written — `IMPLEMENTED_PENDING_VALIDATION` in the
  request's own vocabulary — and does not reach `LOCAL_ACCEPTANCE_READY` or
  `CLOSED` until a validation batch runs its deferred gates.
- `/validate-batch` is a new command; `/plan-next` now states an execution
  mode, the gates that run immediately, and the gates deferred, for each
  recommendation, and recommends a validation batch by risk/dependency/
  milestone boundary rather than by count.
- A feature meeting any floor signal is never BUILD-eligible and this ADR
  changes nothing about how it is built, reviewed or accepted.
- Nothing about gate independence, evidence requirements or budget accounting
  changes for a deferred gate. It runs later; it does not run more cheaply.
- Downstream products (`docoris`, `lexveria`, `koras-control-plane`'s
  orchestration-free profile is unaffected by definition) do not have this
  file until it is hand-carried to them, the same way ADR 0010's V2.1 has not
  reached any of them as of this writing. This ADR changes the factory's
  product-profile template only; no generated product was touched to produce
  it.

**Alternatives rejected.**

*A fourth value on `execution-modes.yaml`.* Rejected — see above. That file's
mode already changes machinery and reuse; adding timing is a third axis
wearing the first axis's clothes, and the file's own history is a proof this
is the failure mode to avoid.

*A second HIGH-RISK subject-area list, checked against the feature's
description.* Rejected. `risk-model.yaml`'s whole point is that risk is a
boundary a diff touches, never a label on the feature, and a parallel list of
"security, tenant isolation, payments, migrations" as subject areas would be
exactly the label-matching that file was written to prevent — both
directions of failure it already documents (a wording change misclassified
as high-risk; a quiet authority change misclassified as safe) reappear the
moment eligibility is judged by subject rather than derived from the existing
signals.

*Deferring gates by mode instead of naming them individually.* Rejected. A
gate's deferrability is exactly the kind of fact ADR 0010 already insists be
declared where a test can check it against something else — here, against
`acceptance-batching.yaml`'s own list — rather than left as "FAST and
STANDARD skip the slow ones," which is unfalsifiable and was the shape of the
removed `evidence_depth` field.

*Treating a validation batch as a second epic mechanism with its own rules.*
Rejected. It is close enough to `epic_acceptance` that a second, independent
rule set would drift from it the first time one was changed without the
other; reusing the shape and stating the one real difference (a batch also
runs each feature's own deferred gates, which an epic pass does not) is
cheaper and harder to get wrong.
