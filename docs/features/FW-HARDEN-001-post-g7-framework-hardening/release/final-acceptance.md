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

## Attempt 2, 2026-09-21, against `bc3ddac` — **PASS**

A second independent pass, inheriting nothing. It re-derived every disputed
number with its own classifier rather than reading the evidence: the six
classification rows, class movement across all 869 tracked template files,
the 32 / 19 / 38 recounts, 179 `.hbs` files, 462 application files, 807
distinct paths, and the 19 orphans in three groups.

What it did beyond re-checking:

- **Confirmed the attempt-1 defect was real and is reversed.** It classified
  the tree at `939fdd5` as well as at `bc3ddac` and measured 26 files moving
  back from `deployment_config` to `frontend_code`. The gate arithmetic it
  computed independently — 12 lost, 1 gained, net 11 — matches attempt 1's
  figure exactly.
- **Zero files lose a gate**, re-derived under the regression document's own
  methodology as well as its own.
- **Refused six malformed documents of its own invention**, none of them in
  the suite's list: a byte-order mark before the delimiter, a leading blank
  line, leading whitespace, a closing delimiter followed by a tab, CR-only
  endings, and a five-dash close.
- **Killed mutation M23** by its own choice, reverted it, and verified the
  tree clean.
- **Checked the new invariant could actually fail**, by measuring that 26
  application files would classify as `deployment_config` under M23 —
  independently of the six explicit rows beside it.

### Findings — 3 LOW, 2 informational. No CRITICAL, HIGH or MEDIUM.

| # | Severity | Finding | Action |
|---|----------|---------|--------|
| 1 | LOW | A scale label wrong in three places: "the 807 distinct paths a product receives". 807 is all three template trees; a product receives 786. And the regression table was headed with one scale while counting at another. | **Fixed.** Both scales named where they differ, and the two load-bearing cells noted as holding at all three. |
| 2 | LOW | The release notes called an unsynced product's older contract "not dangerous, just incomplete". FW-GAP-006 was rated High precisely because an incomplete classifier **fails open**. | **Fixed.** The reassurance is withdrawn and replaced with what is actually true, including why it is still not urgent. |
| 3 | LOW | The amendment table listed A4 after A5 — out of order, in the one table whose value is order. | **Fixed.** Ordered by when each amendment was made, with the one row whose occurrence differs saying so. |
| 4 | INFO | `bc3ddac`, the remediation of the attempt-1 HIGH, has not itself been independently *reviewed*; `review.md` predates it. Acceptance measured its effect directly instead. | Recorded. Stated here so the record does not imply a review it did not have. |
| 5 | INFO | Anchoring the build-graph globs means an application's own `tsconfig.json` no longer invalidates `deployment_preflight` — the one gate `deployment_config` has that `frontend_code` lacks. | Recorded. The correct trade, since it gains twelve, but a real consequence that went unremarked. |

**Verdict: PASS.** Reached by independent measurement, not by reading the
evidence documents — which is the standard attempt 1 set when it failed this
work on a number that nobody had measured.
