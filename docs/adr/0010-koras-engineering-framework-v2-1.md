# ADR 0010 — The engineering framework bounds its loops and reuses its evidence

**Status.** Accepted, 2026-09-19. Supersedes nothing; V2.1 is an evolution of
the V2 orchestration contract in `profiles/product/template/.claude/`, and the
40-agent catalogue is unchanged.

**Context.** V2 delivered its first complete real feature lifecycle
successfully — implementation, tests, RLS, security, manual QA,
accessibility, regression, review, acceptance, merge, CI, browser E2E and a
dev deployment all passed. The execution cost was roughly five accessibility
cycles, five code reviews, five browser runs, five evidence audits, six
manual QA passes, three final acceptances, and about 164 screenshots for 20
manual cases.

That is not a quality problem and it was not carelessness. Every individual
decision to go round again was defensible on its own. The framework had no
point at which judgement was *required*, because two questions had no answer
anywhere in it:

1. **Did anything relevant to this gate change?** A gate recorded only
   whether it had passed. With nothing recorded about what a result depended
   on, the only safe habit is to re-run everything — and re-running
   everything is what happened, including re-establishing a row-level
   security suite against code that had not moved.
2. **When do we stop?** Nothing capped any loop. The only thing deciding
   whether to try again was whether the next attempt looked promising, and it
   always does.

A third, smaller problem made both worse: three files asked the same
applicability question in three vocabularies with **no token in common**, so
nothing could be derived from any of them.

**Decision.** Four changes, and no weakening of any gate.

1. **One applicability vocabulary.** Conditions are declared once in
   `conditions.yaml`. Activation, gates, documentation, risk and invalidation
   all read from it, and an undeclared or unconsumed condition fails a test.

2. **Risk is a boundary, not a subject area.** Execution mode is selected
   from signals that each name what must actually be touched and the nearby
   change that looks like it and is not. A mode changes planning depth,
   evidence depth and reuse; it can never switch off a gate, waive
   independence, or satisfy a human gate.

3. **A passed gate is reused when nothing it depends on changed.** Each gate
   declares the change classes its result depends on; invalidation is derived
   from those declarations. Reuse is a fact about the diff — elapsed time, a
   slow gate, and "nobody expects it to have changed" are explicitly not
   reasons.

4. **Every loop is bounded and every exit leads to a person.** Six caps, two
   outcomes, both of which stop the agent. Counters do not reset on a commit,
   a branch or a remediation. Two freeze points decide what a late change
   costs, so that correcting a sentence no longer re-opens the engineering
   lifecycle.

**Why not simply run fewer agents.** Because the agent count was never the
problem. A framework that activated eight agents and still re-ran their gates
five times each would cost the same. The expense was repetition, and
repetition is caused by not knowing what changed and not knowing when to
stop.

**Why the matrix is derived rather than written.** A change-class-to-gate
table would be a second copy of the gate list, and it would be wrong the
first time somebody added a gate and updated one of the two. Each gate
declares its own inputs; the matrix is a set operation. The same reasoning
kept three requested routing fields off the agent registry: gate ownership,
activating conditions and blocking authority are each already recorded in a
file that cannot drift from the thing it describes.

**Why this is not executable.** Every rule here is followed by an agent
reading it. A `koras orchestrate` command that computed conditions, mode,
agent set and reuse would make the contract unskippable, and it is not built,
deliberately: the contract had to be right before something depended on its
exact shape. Likewise the gate-result store — building a store before the
record's fields are settled is how a store comes to record the wrong ones.

**Consequences.**

- A change now re-runs the gates it affects. A browser-test correction
  invalidates the browser gate, CI and acceptance, and reuses the other
  twenty-one, including manual QA, accessibility, both reviews and
  regression.
- A product used to unlimited rework will eventually hit a cap and be stopped
  and asked. That is the intended behaviour, not a regression.
- `final-acceptance` reporting READY now closes one lifecycle state rather
  than the feature. A feature that deploys is not closed until CI and the
  environment have reported for themselves.
- A step switched off by policy is `NOT_APPLICABLE_BY_POLICY` — neither a
  failure nor an absence. Product-side Control Plane registration is the
  standing case (F2b and F3 in `docs/FOLLOW_UPS.md`).
- Applicability tokens were renamed. A product that hand-edited the three
  affected files must apply the mapping in
  `docs/features/engineering-framework/v2-to-v2-1.md`.
- Nothing measures whether any of this worked yet. The telemetry contract
  exists and no run has produced two reports to compare.

**Alternatives rejected.**

*Delete or merge agents.* Rejected before work began, and the reasoning held:
the catalogue is not what costs. Forty definitions of which eight run is
cheaper than eight definitions run five times each.

*A standalone invalidation matrix.* Rejected as a second copy of the gate
list — see above.

*Reuse judged per run by the reviewing agent.* Rejected because it is the
status quo. "Nobody expects this to have changed" is a prediction, and a
framework built on predictions re-runs everything the moment anybody is
unsure, which is exactly the behaviour being replaced.

*Hard screenshot limits.* Rejected. A quota would make high-risk workflows
under-evidenced while doing nothing about the real cost, which is that a
reviewer cannot tell which images prove anything. A required statement of
what a capture proves does address that, and it is self-enforcing: a purpose
that cannot be written in a phrase is a capture that proves nothing.
