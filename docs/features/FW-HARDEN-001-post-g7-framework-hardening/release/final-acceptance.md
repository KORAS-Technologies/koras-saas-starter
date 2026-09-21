# FW-HARDEN-001 — final acceptance

## Attempt 1, 2026-09-21, against `939fdd5` — **FAIL**

Performed by `final-acceptance`, an agent that neither wrote the code nor
reviewed it. It verified by running rather than by reading: the canonical
suite, the documentation suite, the whole generator suite, a mutation it chose
itself, a Windows checkout it created itself, and five malformed documents of
its own invention.

Most of what it checked was met. The verdict turned on one finding.

### The finding

**Twenty-six product files lost eleven quality gates, and the regression
document said the opposite.**

Widening `deployment_config` to reach the build graph was written with a
leading globstar. `deployment_config` sits above `frontend_code` in the
ordering, so that glob captured every application's and package's own
`tsconfig.json`, plus `packages/ui/turbo.json` — 26 files that had classified
as `frontend_code`.

`frontend_code` invalidates 16 gates. `deployment_config` invalidates 5. The
twelve lost include `automated_tests_pass`, `e2e_pass`, `accessibility_pass`,
`independent_code_review`, `security_review` and `regression_pass`.

An edit to `packages/ui/tsconfig.json` can change how every frontend file in
the product compiles. After the fix, it would have reused the test, browser,
accessibility and independent-review results.

**That is FW-GAP-006's exact failure mode, produced by FW-GAP-006's fix.**

Two things made it a blocker rather than a note. `testing/regression-results.md`
stated twice that no file had moved out of a class — false, and it was the one
measurement that would have caught this. And the YAML comment's own rationale
argued the other way: *"an edit to one can change every artefact"*, which
argues for more gates, while the effect was eleven fewer.

Nothing asserted it. The coverage assertion counts paths that classify as
*nothing*; a path moving between two real classes is invisible to it. That gap
is the general lesson, and it is what the remedy closes.

### Why the suite did not catch it

Confirmed by measurement, not conceded: 558 assertions passed with the defect
present. The classification matrix had no row for a `tsconfig.json`, the
coverage assertion could not see class movement, and the gate tests all start
from class names rather than from paths.

### Remediation

| Finding | Severity | Action |
|---------|----------|--------|
| 26 files lost 11 gates | HIGH | Build-graph globs anchored at the repository root. A package's own build file belongs to its package. Verified by measurement: **0 files lose a gate**, and every movement is unclassified → classified. |
| The gap that hid it | HIGH | A new invariant: nothing inside an application directory is `deployment_config` unless it is literally a deployment descriptor. Enumerated over the real tree, so it cannot be satisfied row by row. Mutation M23. |
| FW-GAP-013 cited seven times with no register row | MEDIUM | Row written. It was named in four documents and three times in a contract file that ships into every generated product, while the register stopped at 012 — the R-042 class, in the worst possible place. |
| Three numbers that do not reproduce | MEDIUM | Recounted on the 807 distinct paths a product receives, and corrected: 32 unclassified under `local/` rather than 25, all 19 scripts rather than 18, 38 moved to `deployment_config` rather than 25. |
| The Windows artefact recorded 552 against a HEAD of 557 | LOW | The event log named `575acaf` correctly; the two prose artefacts were loose. Re-run at the remediated commit and the artefact now records all runs and which commit each covers. |

The one item recorded and not acted on: acceptance noted that the derived
telemetry summary is unfinished, and agreed it is the contract being followed
rather than an omission. It did not judge it, which is what the amended
contract asks of it.

### The count

**Three remedies produced three next defects in one cycle** — FW-GAP-010's fix
rebuilt FW-GAP-010, FW-GAP-006's fix reproduced FW-GAP-006, and both were
found by the stage after the one that made them. G7 R2 recorded the same shape
twice. It is now five occurrences across three lifecycles, and the common
factor is an assertion that asks what a contract *says* rather than what it
*does*.

## Attempt 2 — **NOT RUN**

Every attempt-1 finding is remediated and each carries its own evidence, and
the full local baseline is green apart from one flake recorded below. But a
second independent acceptance pass **has not been performed**, and this
document does not claim one.

That is stated plainly rather than softened, because the alternative is the
failure this whole cycle is about: attempt 1 found a HIGH defect that 558
green assertions did not, and the two attempts before it each found something
the stage before had missed. Declaring PASS on my own work — having written
the code, the tests and the remediation — would be exactly the self-approval
`independent: true` exists to forbid.

**Status: REMEDIATED, ACCEPTANCE RE-RUN OUTSTANDING.**

What a second pass would have to re-check, since acceptance inherits nothing:

- the class-movement fix and its new invariant
- the FW-GAP-013 register row
- the three recounted numbers
- the Windows artefact now covering every commit it names
- everything attempt 1 passed, again, against the current tree

### The one open item in the local baseline

`product-governance.test.ts` fails a 120-second `beforeAll` hook timeout when
the generator suite runs under parallel load, skipping its 8 assertions. Run
alone it passes in 30 seconds, 25 of 25.

It is not caused by this cycle: G7 R2's event log records the same 120s hook
timeout on 7199f85 and calls it environmental. Clearing 192 stale temporary
directories did not stop it. Recorded as **FW-DEF-003** and deliberately not
fixed — it is a test-infrastructure decision unrelated to the three findings
this cycle was authorised for.

A flake that *skips* assertions rather than failing them is the kind that gets
papered over by a retry, which is why it has an ID.
