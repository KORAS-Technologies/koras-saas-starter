# Koras Feature Definition of Done

A feature is done when every applicable condition below holds. "Applicable" is
decided by `activation-rules.yaml`, not by preference — but a condition that
applies and was not met means the feature is not done, however small the gap.

## Always

1. Every requirement and acceptance criterion traces to an implementation and
   to an executed verification.
2. Automated tests pass, evidenced by actual executed results rather than by a
   claim that they were run.
3. The implementation matches the approved design, or every deviation is
   documented and accepted.
4. Independent code review has run, performed by an agent that did not write
   the code, with no unresolved CRITICAL or HIGH findings.
5. Tenant isolation, authorization, input validation and secret handling are
   correct on every changed path.
6. No control, test or type check was disabled, skipped or weakened to make the
   change pass.
7. Documentation affected by the change is updated — including documentation the
   change made wrong, not only documentation it adds. The derived telemetry
   summary is the one exclusion: `telemetry.yaml` makes it a closure artifact,
   finalised after acceptance, so it is not expected to be finished when this
   item is judged. Closure checks it instead (FW-GAP-010, 2026-09-21).
8. `final-acceptance` reports READY.

## When the feature is user-facing

9. Critical paths are verified in a real browser at desktop and mobile width,
   with the browser console checked.
10. Manual QA has executed the approved cases against a real, identified
    environment, recording expected and actual results per case.
11. Every manual case carries a verdict of PASS, FAIL or BLOCKED. BLOCKED
    carries a documented reason and is never counted as a pass.
12. Screenshots are genuine captures from the executed steps, stored at the
    canonical paths, and mapped feature → test case → step → screenshot.
13. Accessibility meets WCAG 2.2 AA for the changed surfaces, verified by
    keyboard and focus interaction rather than by an automated scan alone.
14. `qa-reviewer` has independently audited the evidence and found no gaps.

## When the risk triggers apply

15. Security review has independently confirmed that the specified controls are
    actually implemented, with no unresolved CRITICAL or HIGH findings.
16. Abuse cases from the threat model were genuinely executed, including
    cross-tenant access attempted and shown to fail.
17. Privacy and compliance review has run where personal, sensitive or
    regulated data is involved.
18. AI features have been independently evaluated for correctness, grounding,
    citation integrity, injection resistance and tool authority.
19. Domain review has run where the feature is domain-heavy, by the product's
    own domain agent.

## When scope is wider than one feature

20. Migration ordering, reversibility and rolling-deploy compatibility are
    established and tested.
21. Regression scope identified by impact analysis has passed, on the
    *integrated* result rather than on each branch separately.
22. Observability exists for the new production paths, and any new alert has a
    documented action.

## When and BUILD are different questions

Items 9–14 and item 8 name gates that `acceptance-batching.yaml` may allow a
BUILD-disposition feature to satisfy in a later validation batch rather than
before it reaches `IMPLEMENTED_PENDING_VALIDATION`. That changes *when* the
item is judged, never *whether*: a feature is not done, in either lifecycle
state, until every applicable item on this page holds. Item 13's own targeted
half — accessibility on the changed surface — is never deferred, in any
disposition; what a validation batch may add is the broader check across a
combined surface, which is the epic-level check `lifecycle.yaml` already
describes. A feature meeting any floor signal in `risk-model.yaml` is never
BUILD-eligible, so items 15–19 are never the ones a batch defers.

## What done does not mean

Done is not merged and not deployed. Human approval remains required for
starting planner-recommended work, for material architecture changes, for
merging to a protected branch, and for production release. `final-acceptance`
reporting READY enables those gates; it does not satisfy them.
