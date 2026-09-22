# Settings framework — review of the F27 closure corrections

| | |
|---|---|
| **Purpose** | The independent review of the corrections made during F27 closure, and what each finding produced. Distinct from `review.md`, which reviewed the framework itself on 2026-09-19. |
| **Reviewed** | 2026-09-21, against the frozen closure tree. |
| **Scope** | The SET-05, SET-06, SET-07, SET-22 and SET-23 corrections only — 924 lines of diff across `profiles/` and `generators/`. |
| **Reviewer** | An agent that did not write the code, given the diff, the full files it touches, and ten specific questions. |

## Verdict

**BLOCK.** No Critical. No High. Four Medium, four Low.

That is the fifth BLOCK from five independent reviews in this repository, and
the pattern named in `review.md` holds again: **nothing here was caught by the
automated suites, and the corrections were written by a session that believed
they were finished.**

What it did *not* find is worth stating too. It confirmed the resolver was
correctly left alone, that the baseline mechanism cannot escalate anything,
that the per-type comparison is right for every type the catalogue declares,
that `heldMeans` is not backwards, that SET-07 breaks neither page, that the
in-block SQL move assertions are not vacuous, and that SET-23 left no dangling
translation.

## What each finding produced

### MEDIUM-1 — the `with check` blocks and their comment · **half accepted**

The reviewer argued the two `tmp_set22_select_all` blocks are vacuous, on two
grounds: that PostgreSQL applies SELECT policies only to the *existing* row on
an `UPDATE`, and that deleting `with check` falls back to `using`.

**The first is wrong, and it was settled by experiment rather than by
argument.** Three configurations, each setting `with check` *explicitly* so
the fallback cannot account for the result:

| `with check` | SELECT policy | Move |
|---|---|---|
| `tenant_id = current` | narrow | REFUSED |
| `true` | narrow | **REFUSED** |
| `true` | widened by a second permissive policy | **MOVED 1 row** |

The select policy does gate the new row, and widening it is exactly what
leaves `with check` alone to refuse the move. The runs are in
`docs/features/settings-framework/testing/runs/2026-09-21-01/set22-mutation-bisection.txt`
— which the reviewer was right to say was missing.

**The second is correct and useful.** `CREATE POLICY` falls back to the `using`
expression when no `with check` is given, and here the two are identical, so
*deleting* the clause is a semantic no-op that nothing can or should catch.
That is a sharper account of SET-22 than the original finding gave, and it
supports the severity downgrade rather than undermining it. Both suites now
say so in comments, and point at the evidence.

### MEDIUM-2 — SET-07 moved the disclosure rather than closing it · **accepted and fixed**

The best finding of the review. The first fix withheld `global_value`, but the
permissioned sibling route refuses the **organisation's** rows, not the
platform's — so a member could still read what their organisation had
configured for every key, which is precisely the data the permission guards.

`organization_value` is now withheld too, except where `can_override` is true.
There it is what the caller's own Reset restores and a control that cannot say
what it would do is worse than the disclosure; everywhere else it is
organisation configuration with no control depending on it. A second test
covers the case, using a value the definition actually accepts — the first
attempt used an invalid enum value, which the resolver passed over, and would
have passed for the wrong reason.

### MEDIUM-3 — SET-05 and SET-06 had no behavioural test · **accepted and fixed**

The finding this cycle most needed. Every assertion about those two
corrections was a substring search over template text, and the reviewer gave
the concrete consequence: change `same()` to `return true` and **no setting
can be saved on either page**, while all four assertions still pass and the
whole node suite stays green.

The obstacle was real — the logic lived in a Handlebars template importing a
generated package, so nothing in this repository could execute it. The
deciding logic is now `packages/ui/src/settings/form-values.ts`, plain
TypeScript with no generated import, and `product-settings-logic.test.ts`
drives it with real `FormData`. The application file keeps the generated types
and does no deciding.

**Mutation-tested against the three mutations the reviewer named:**

| Mutation | Result |
|---|---|
| `same() => true` (nothing can be saved) | **7 of 18 fail** |
| `same() => false` (SET-05 restored verbatim) | **11 of 18 fail** |
| `isHeldHere` always row-presence (SET-06 restored) | **2 of 18 fail** |

Writing it found one more thing worth keeping: the first fixture supplied
baselines only for the fields each test was thinking about, which is not a
form the product ever sends — the real form emits one per field — and three
tests failed confusingly as a result. The fixture models the whole form now.

### MEDIUM-4 — `same()`'s comment was wrong about its second caller · **accepted and fixed**

SET-06 gave `same()` a caller in `toField` where neither clause of its comment
holds: the operands are decoded from the API's JSON rather than produced by
`parseSubmitted`, and a spurious inequality there costs a wrong marker and a
Reset button rather than one redundant write. The comment now states both
callers and both consequences.

### The four Low findings

| ID | What | Outcome |
|---|---|---|
| LOW-1 | the `heldMeans` caveat was called "cosmetic", which is narrower than what it does — the marker flips as well as the button disappearing | Comment corrected: both halves, and why the trade is still the right one |
| LOW-2 | `baselineText`'s comment claimed it mirrors the DOM; a checked box submits `"on"`, not `"true"` | Comment corrected to say the *parsed* values must match, not the wire spelling |
| LOW-3 | the hidden-settings comment opened "Four." above a list of six | Corrected. Same R-042 class the cycle is nominally closing, introduced by the cycle itself |
| LOW-4 | an `object`-typed setting is unsaveable and nothing said so | `parseSubmitted` returns `undefined` for `object` and says why, rather than storing `"[object Object]"` |

## Security — APPLICABLE, and covered by this review rather than separately

The corrections touch an authorization boundary (SET-07), a row-level-security
test suite (SET-22) and a write path that now takes a browser-supplied input
(SET-05's baseline). Security review therefore applies, and treating it as
N/A would have been wrong.

**It was covered inside this review rather than commissioned separately**,
which is a narrowing worth stating plainly rather than dressing up: the
reviewer was asked the security questions directly — can a user cross scopes,
can an organisation cross tenants, can an ordinary member alter organisation
or global settings, can the baseline be abused, can an unknown key be
injected — and answered each against the code.

| Question | Answer |
|---|---|
| Can the browser-supplied baseline escalate anything? | No. It can only ever cause a key to be **omitted**; it cannot add a key, change a value, or bypass the API's scope, coercion and permission checks |
| Can an ordinary member write an organisation setting? | No — 403, and reproduced |
| Can one organisation read or write another's? | No — proven as the unprivileged role against a real database, including the row-move case that was previously untested |
| Can a member read what the permission refuses? | **This was the one real finding**, MEDIUM-2, and it is fixed |
| Is the resolved ladder still correct? | Yes, and the resolver was correctly left untouched |

No Critical or High security finding. **What has not happened is a dedicated
security-reviewer pass over the settings framework as a whole** — this covers
the changed surface only, and the framework's wider surface was reviewed on
2026-09-19.

## Privacy — APPLICABLE, and the change reduces exposure

The framework stores personal preferences against a ZITADEL subject, so
privacy applies. Three findings and no more:

- **The change is a narrowing.** SET-07 removes two columns of organisation
  and platform configuration from what an unpermissioned member is served. No
  new personal data is collected, stored or logged.
- **No setting value reaches a log line.** The audit trail records before and
  after per key, redacted for a `sensitive` definition — though SET-20 remains
  open, so nothing can be marked sensitive in practice today.
- **Deletion works and is exercised.** A person clearing a preference removes
  the row rather than nulling it, verified in TEST-SET-06; and the database
  refuses a credential-shaped key or value outright, verified in TEST-SET-09
  including the nested case.

**Not evaluated here:** export and erasure obligations across the framework as
a whole, which belong to the storage and audit governance work rather than to
this cycle.

## The documentation audit

**Ran 2026-09-21, after the corrections. Verdict: FAIL, on one finding.** An
independent agent checked every count, status, fix claim and evidence file
against the underlying artefacts rather than against the other documents.

**What it confirmed**, each by inspection rather than by cross-reference: all
five fixes are present in the code as described; the register and the finding
matrix agree on disposition, evidence and severity for every row; all nine
evidence files exist and contain what they are said to contain; SET-21's
"did not reproduce" is correct against the worker's three sweeps; `review.md`
was appended to and not rewritten; the manual arithmetic is 8 + 2 + 5 = 15
with each case appearing once; `product-settings-logic.test.ts` really has
eighteen tests; and **no document claims F27 is closed**.

**What it found is R-042, in the two highest-traffic files in the
repository.** `CLAUDE.md` and `STATUS.md` both said the review carried
*seventeen* findings, two lines above a sentence saying *eighteen* were
reconciled. Both numbers were defensible — `review.md` numbers SET-01 to
SET-21 and carries seventeen of them in its table, and names the eighteenth in
prose under "Gaps in the isolation suites", which is the finding the closure
cycle numbered SET-22 — but a paragraph that contradicts itself two lines
later is wrong however defensible each half is. Both now say which count is
which and why they differ, so the next reader does not reconcile it by
deleting one.

**And one thing the audit flagged was its own error**, which is worth the same
sentence the review's wrong finding got. It hand-traced the `same() => false`
mutation to ten failures against the documented eleven, and said so as
low-confidence because it could not execute the mutation. Re-run: **11 failed,
7 passed of 18**. The documented figure stands. Two independent gates in this
cycle produced one wrong claim each, and both were settled by running
something rather than by arguing.

## What this cost, and what it bought

Eight findings, none Critical or High, all resolved inside one correction
round — within the framework's `max_reviewer_cycles` of 2.

**The review paid for itself twice over.** MEDIUM-3 turned five assertions
that could not fail into eighteen that demonstrably do, and MEDIUM-2 found
that a fix recorded as closing SET-07 had moved the disclosure rather than
closing it — a finding that would otherwise have been written down as done.

**And one of its findings was wrong**, which is worth recording as plainly as
the seven that were right. MEDIUM-1's claim about PostgreSQL was refuted by
three statements against a real database. A review is evidence, not authority;
the correct response to a finding is to check it, and that is as true when it
comes from a reviewer as when it comes from the session being reviewed.
