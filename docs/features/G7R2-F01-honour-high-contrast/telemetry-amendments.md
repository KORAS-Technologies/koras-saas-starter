# G7R2-F01 — telemetry amendments

Append-only. A correction is a new record naming what it corrects; nothing in
`telemetry-events.md` is ever rewritten in place. An amendment with no evidence
is a second guess, not a correction.

| at | amends | previous_value | corrected_value | reason | evidence |
|----|--------|----------------|-----------------|--------|----------|
| 2026-09-21T17:35Z | event 2, and the classification prose in `testing/runs/2026-09-21-02/README.md` | The probe-1 shortfall was classified TEST_DEFECT, and contrasted against SESSION_RUNTIME (both written without backticks here on purpose -- see the reason) | The contrast is now drawn against `SESSION_OR_TOOL_HEALTH`, and the instrument defect is described in prose rather than given a token | Neither of those two is a token this repository declares. Both came from the G7 R2 brief's own failure-classification list, which is not the framework's vocabulary: `agent-registry.yaml` `runtime_discovery` declares `SESSION_OR_TOOL_HEALTH` and nothing declares the other two. They are written here unquoted because `tests/docs/identifiers.test.ts` reads backticked tokens and cannot tell a document naming an identifier in order to say it does not exist from one claiming it does -- which is a real limit of that gate, recorded in `release/framework-findings.md` rather than worked around silently. Naming a token the repository does not have is the exact failure `tests/docs/identifiers.test.ts` exists to catch, and it caught it. | `tests/docs/identifiers.test.ts`, run 2026-09-21; the corrected README |
