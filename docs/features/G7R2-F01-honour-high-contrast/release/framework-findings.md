# G7R2-F01 — framework findings

What the G7 R2 lifecycle found, 2026-09-21. None is a defect in the feature. Each is
either a question the V2.1 contract had not written down, or a gate whose reach does not
match its intent, or — in one case — a defect in the repository that only an isolated
worktree could expose.

Carried into `docs/platform/gap-defect-register.md` rather than left in a transcript.

---

## FW-GAP-006 — the change-class globs do not match the factory

`gate-invalidation.yaml` defines change classes by path glob, and the globs are written
for a **generated product root**: `frontend_code` is `packages/**`, `backend_code` is
`services/**`, `e2e_test` is `e2e/**`. In the factory the same code lives at
`profiles/product/template/packages/**`, and `packages/**` is not `**/packages/**`, so it
does not match. Separately, **no change class in the file matches a `.css` path at all**,
in either tree.

Consequence, worked through on this feature's actual diff: a classifier reading the diff
literally sees `automated_test_node` and nothing else. `frontend_code` never fires, so
`accessibility_pass`, `e2e_pass`, `screenshot_evidence_complete` and
`independent_code_review` are all reported reusable — every gate that most needed to run.
A framework whose reuse rule is "a gate is invalidated when a change touches one of its
inputs" cannot answer that question at all for factory-resident product code.

Found by `impact-analysis`, which was asked what the classes would be and said plainly
that they do not match rather than picking the nearest one. Not routed around: this run
applied the classes by their evident intent and made every gate decision as though
`frontend_code` had fired.

**Severity: High.** The remedy is either anchoring the globs (`**/packages/**`, and a
`**/*.css` entry) or stating that gate invalidation is evaluated post-generation only.
Both are decisions, not edits, and neither belongs in a FAST feature.

---

## FW-GAP-007 — the prose gates fire on evidence that policy forbids editing

`documentation-policy.yaml` `evidence_runs` says a run directory is **written once and
never edited afterwards**, and that a failed run stays. `tests/docs/` walks every `.md`
under `docs/` and requires, among other things, that a hedge sit in a dated context.

Those two rules met on this run and contradicted each other. The Planner's raw output,
captured verbatim into `testing/runs/2026-09-21-01/`, contains four undated hedges —
"not yet", "currently" — because that is what the agent wrote. The gate demanded an
edit; the evidence policy forbade one.

Resolved without weakening either: raw captured transcripts are `.txt`, not `.md`. The
prose gates walk `.md` only, and a captured transcript is **output**, not documentation
— the probe captures already sitting beside it in the same run directory were `.txt`
already. The convention now applies to agent transcripts too.

**Severity: Medium**, and the fix is a convention rather than a code change. What should
be written down is the convention itself, because the next person to capture an agent's
output as `.md` will meet the same contradiction and may resolve it by editing the
evidence.

---

## FW-GAP-008 — two limits of the documentation gates, found by tripping them

Both are narrow and both are real.

1. **The hedge check's date pattern rejects an ISO timestamp.** `DATE` is
   `/\b20\d\d-\d\d-\d\d\b/`, and `2026-09-21T17:40Z` does not match it: `1` and `T` are
   both word characters, so there is no boundary after the day. A document dated to the
   minute reads as undated. Written `2026-09-21, 17:40Z` it passes.
2. **The identifier check cannot tell naming from claiming.** It flags a backticked
   token that no file outside `docs/` contains. A document that names a token **in order
   to say the repository does not have it** — which is exactly what this run's telemetry
   amendment does — is indistinguishable from one claiming it exists. The workaround is
   to write such a token unquoted, which is what the amendment now does, with the reason
   stated in the document rather than left to look like a style choice.

**Severity: Low.** Neither hides a defect; both cost a cycle and will cost the next
person one.

---

## FW-DEF-002 — a fresh Windows checkout cannot pass the framework's own validation suite

The most consequential finding of the run, and the only one that is a defect in the
repository rather than in the contract.

`.gitattributes` declares `* text=auto`. On any Windows checkout that converts every
text file to CRLF. `generators/create-koras-app/tests/orchestration.test.ts` then
asserts, for each of the 40 agent definitions:

```
expect(body.startsWith('---\n')).toBe(true)
```

which is false for `---\r\n`. **41 of 499 assertions fail** — the whole
`has frontmatter naming itself` family plus one more — in a fresh clone on a default
Windows configuration. That is the suite that validates the entire 40-agent catalogue:
the registry count, the identifier resolution, the category totals, the profile
isolation.

It has never been seen because CI runs on Linux, and it did not appear in the main
working tree on this machine because those files happen to sit there as LF and git
reports them clean under `text=auto` normalisation. The committed blobs are LF; the
CRLF is produced by checkout.

Two things make this worth recording rather than fixing quietly.

**It was found only because the framework mandates an isolated worktree.** Every
previous run of this suite on this machine used the long-lived main checkout. The
worktree policy exists to keep concurrent work apart, and it exposed a defect nothing
else in the estate could have.

**The lesson had already been learned once, in the same file.** `.gitattributes` pins
`*.sh`, `*.bash`, `Dockerfile`, `Makefile` and `*.mk` to `eol=lf`, with a comment
explaining that bash reads `set -euo pipefail\r` as an option named `pipefail\r` and
aborts. The reasoning is exactly right and was applied to shell scripts and not to the
Markdown files that carry the framework's own definitions — and the test that reads them
assumes LF. `shared-template-parity.test.ts` learned the same lesson a third time, in its
own words: it normalises line endings *and* trailing whitespace because five duplicated
Python package markers hid behind a two-byte difference for months.

**Severity: High** — it makes the framework's validation suite unusable for anyone
developing on Windows, and a suite that is red for environmental reasons is a suite
people stop reading.

**Not fixed here.** It is outside the approved FAST scope, and the remedy is a choice
between two of them: pin `*.md` to `eol=lf` in `.gitattributes`, or make the test
line-ending robust (`/^---\r?\n/`). The second is better — it fixes the class rather
than one instance, and the file already contains four other assertions that read agent
Markdown. Both are one-line changes and neither should be smuggled into a feature about
contrast.

**Evidence:** the failed run is retained at
`testing/runs/2026-09-21-04/pnpm-test-attempt-1-summary.txt`. The same commit and the
same files, re-checked-out with `core.eol=lf`, pass 524 of 524
(`retest-lf-tree.txt`). Nothing about the content changed between the two runs.

---

## What the run did **not** find

Worth saying, because a findings document that only accumulates reads as though nothing
works.

- **No wrong rule.** As in R1, every finding above is a question the framework had not
  written down, or a reach that does not match an intent. Nothing the contract says is
  incorrect.
- **The risk model classified correctly.** FAST was right: the review found no security,
  tenancy, data or architecture concern, which is what "no floor signal fired" predicted
  before any code existed.
- **Capability routing held.** 17 of 40 agents activated. The 23 that were not would each
  have found nothing, and the review — which looked for exactly that — agreed.
- **The freeze points worked.** Code freeze held: the only tree change after it was a
  line-ending re-checkout that altered no tracked content, and `git status` was clean on
  both sides of it. Quality freeze held: the two LOW findings were recorded rather than
  fixed, which is the behaviour the freeze exists to produce.
- **The independent review returned PASS.** The previous four independent reviews in this
  estate all returned BLOCK, and the register says work that has not been independently
  reviewed should be assumed to carry defects of that class. This one did not — on a
  two-file change, in FAST, which is the size of change where that record was always most
  likely to break.
