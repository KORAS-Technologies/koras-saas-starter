# /remediate

Fix one failure with a **proven** root cause, without restarting the feature.

This exists because the alternative has a measured cost. A browser test once
asserted something untrue; the fix was to the browser test; and what followed
was a full lifecycle re-run — the Python suite, the Node suite, the row-level
security suite, the security review, manual QA, accessibility and regression,
all re-established against code that had not moved.

Do not use this when the root cause is suspected. A narrow fix to the wrong
cause is worse than a wide re-run, because it comes with a report saying the
rest was fine.

1. **Establish the root cause**, and say what the evidence for it is. If the
   evidence is "this change made the symptom go away", the cause is not
   established.
2. **Name the change classes** the fix will touch, from
   `.claude/orchestration/gate-invalidation.yaml`.
3. **Derive the invalidated gates**: every gate in `quality-gates.yaml` with
   one of those classes in its `inputs`. Derive the reused gates: the rest.
   Do not decide this by judgement — it is a set operation on the diff.
4. **Check the floor.** If the fix touches any floor signal in
   `risk-model.yaml`, this is not remediation. Stop and re-classify.
5. **Make the fix, and nothing else.** The area being open is not a reason to
   widen it.
6. **Run exactly the invalidated gates**, and record each result with every
   field in the `gate_result` contract.
7. **Report**, with all seven parts:

   - the root cause, and the evidence for it
   - the scope affected
   - the scope actually changed, by change class
   - the gates invalidated, and why
   - the gates reused, and the input classes that were untouched
   - the validation now required
   - whether a human decision is needed

Budget counters **carry over**. Remediation is not a fresh feature and does
not reset a cycle count; if the same failure is being remediated for a third
time, that is `repeated_gate_failure` and it escalates to a human instead.

Never reuse a gate whose inputs the fix touched on the grounds that the fix
was small. Small is not a change class.

Failure to remediate:
```text
$ARGUMENTS
```
