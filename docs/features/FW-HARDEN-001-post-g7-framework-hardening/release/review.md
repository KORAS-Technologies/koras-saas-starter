# FW-HARDEN-001 — independent review

Performed 2026-09-21 by `code-reviewer`, an agent that did not write the code,
against the tree at `575acaf`. It read the diff, ran the suite, and wrote three
probes to measure the classifier, the glob matcher and the frontmatter regex
rather than read them.

**Verdict: BLOCK.** Three HIGH, four MEDIUM, five LOW.

That is the fifth BLOCK from five independent reviews in this estate. The
previous one, G7 R2's, returned PASS and was noted at the time as the first —
on a two-file change, in FAST. This was a larger change in STANDARD, and the
record held.

**Two of the three HIGH findings were defects in the fix itself rather than in
the thing being fixed.** That is the observation worth carrying: a cycle whose
whole subject is "the framework's own rules were wrong in ways nothing could
see" produced, on its first pass, two more of exactly that kind.

---

## The findings, and what happened to each

### HIGH-1 — the FW-GAP-010 fix rebuilt the deadlock one step further on

**Upheld, and it is the most important finding of the review.**

`lifecycle.yaml` made a finalised summary a precondition of entering `CLOSED`.
`telemetry.yaml` said the summary is finalised *at* the terminal state. And
`generated_after` was unchanged, while `lifecycle_state_reached` is an event
kind — so reaching CLOSED is an applicable event the summary must follow, while
CLOSED cannot be entered until the summary exists.

That is FW-GAP-010 with `final_acceptance` swapped for `CLOSED`. The comment
asserting "after acceptance and therefore not circular" was true about
acceptance and false about closure: the loop it created was not the loop it
checked.

**Fixed.** The summary is finalised *immediately before* the terminal
transition, and the transition itself plus the summary's own finalisation are
declared not to be events it waits for. The ordering is now asserted rather
than described — Group E as first written was entirely "the YAML contains this
string", and nothing in it could have caught this. Mutation M20 restores the
old wording and fails the new assertion.

Worth recording plainly: **the shape of this defect — two files each assuming
the other's answer — has now occurred twice in the same contract**, and the
second time was in the fix for the first.

### HIGH-2 — the line-ending class escapes `orchestration.test.ts`

**Refuted, with measurement.**

The review found two further `/…\n\n/` regexes reading source-tree files, in
`product-frontend.test.ts` and `product-shell.test.ts`, confirmed that
`.gitattributes` leaves those files `text: auto`, and probed the regex against
the CRLF bytes to show it does not match. All of that is correct.

What it did not read is the `read()` each of those files defines, which strips
carriage returns before matching — each with a comment recording that this
exact defect bit that file once already.

Settled by running it rather than arguing: the **whole generator suite** on a
fresh CRLF checkout is 61 files, 2244 tests, zero failures.

The finding was specific, testable and wrong, which is the useful kind. It cost
one command to settle and it is recorded rather than dropped, because "we
checked and it was fine" is itself evidence.

### HIGH-3 — the reference implementation broke the rule it introduced

**Upheld.**

`classesOf` filtered unclassified paths away. `path_domain.unclassified.never`
forbids that in as many words: *"Reading an unclassified path as 'nothing
relevant changed'"*. It is the only executable implementation of the classifier
in the repository, and it is what the two headline behaviour tests run through
— so anybody copying it reproduces FW-GAP-006.

**Fixed.** It returns the classes *and* the paths it could not place, both call
sites assert the stop list, and a new test covers a mixed diff. Mutation M19.

### MEDIUM-4 and MEDIUM-7 — the declared holes were 2, the real ones 42

**Upheld, and it changed the shape of the fix.**

The fail-closed rule turns an unclassified path into a stop. With 42 tracked
files unclassified — the whole of `local/` including `migrate.sh` and
`register-with-control-plane.sh`, the build graph, repository hygiene, and the
framework's own contract — routine edits would have become surprise stops,
against a contract block saying there were two known holes.

**Fixed, in two parts.** Two groups had an obvious answer and were given one:
`local/**` and the build graph are `deployment_config` by that class's own
words, and `pnpm-workspace.yaml` is a `dependency`. That leaves 19, in three
coherent groups, which are now **counted in the contract and asserted exactly**
— recorded as FW-GAP-013 rather than hidden. Mutations M17 and M18.

### MEDIUM-5 — the coverage test could not fail

**Upheld, and this is the finding that most deserved catching.**

It walked the filesystem rather than git, so it counted `__pycache__`. Five of
its six roots were catch-all directory globs, so no file type added under them
could ever be unclassified — which is precisely what its own comment claimed it
would catch. The reviewer verified that removing the `.hbs` rule, or the
stylesheet globs, left it green.

**Fixed.** It enumerates every tracked file in all three template trees and
asserts the orphan set exactly against the declared count, grouped so a failure
names which hole moved.

A coverage test that cannot fail is worse than none, because it is counted.

### MEDIUM-6 — the escalated branch was unchecked

**Upheld.** An escalated run never reaches `CLOSED`, so the new closure check
would have been nowhere — the same hole the amendment closes, in the branch the
amendment forgot. `checked_by` now names both branches. Mutation M21.

### LOW findings

| # | Finding | Outcome |
|---|---------|---------|
| LOW-8 | The lazy capture walked past a near-miss closing delimiter, so `--- ` and the prose after it landed inside the frontmatter. The header comment claimed the parser was stricter than its predecessor; this was the one direction where it was looser. | **Fixed** — tempered capture, plus a regression case. Mutation M22. |
| LOW-9 | `judges` / `does_not_judge` read through `as unknown as` casts, so a typo in either YAML key degraded to an empty array. | **Fixed** — typed on the interface, and both asserted non-empty. |
| LOW-10 | Nothing pinned the glob syntax the matcher implements. A future `**/*.{css,scss}` would silently match nothing. | **Fixed** — a guard asserting every glob uses only `*`, `**` and literals. |
| LOW-11 | The YAML comment presented a stylesheet served by the API as a measured misclassification; no such file exists, and measuring the old vocabulary against the new changed the class of nothing. | **Fixed** — the comment now says the rule costs nothing today and is written for the next stylesheet. |
| LOW-12 | The test plan said "byte-identical frontmatter"; the assertion is CRLF-equivalence. | **Fixed** — wording corrected. |

---

## What the review confirmed

Recorded because a review record that lists only failures reads as though
nothing was right.

- **No G7 R2 evidence was rewritten.** Verified against the diff.
- **No scope expansion.** The changed files match the design's own table.
- **One path domain, clearly stated** — not two competing systems.
- **The glob matcher agrees with standard semantics** on every construct the
  contract uses; the reviewer checked `**` spanning zero segments, `*` not
  crossing a separator, and four other cases.
- **The normalisation loop is correct**, including the two edges that would
  have been easy to get wrong: `profiles/product/manifest.yaml` is untouched
  because it has no `template/` segment, and only one prefix is ever stripped.
- **`asLf` / `asCrlf` are correct on mixed input**, verified round-trip.
- **FW-GAP-003 is not reopened.**
- **The frontmatter matrix is genuinely mutation-resistant** — the reviewer ran
  eight malformation cases of its own beyond the ten in the suite.

## What this review changed about the work

Beyond the fixes: the mutation set grew from 16 to 22, with one mutation per
upheld finding, so each is now defended by something that fails when it
regresses. The three documentation claims the reviewer falsified are corrected
in place with the correction visible, rather than quietly rewritten.
