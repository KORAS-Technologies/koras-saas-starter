# FW-HARDEN-001 — release notes

Post-G7 framework hardening. Maintenance against the accepted G7 R2 baseline,
commit 7199f85, on 2026-09-21.

**No product behaviour changes.** Nothing a customer can reach was touched, and
no generated application byte changes — see *Downstream* below.

---

## What changed, and why it mattered

### The framework's validation suite works on Windows

A fresh checkout on a Windows machine converts the 40 agent definitions to
CRLF, and the assertions that parse them were written for LF. 41 of 499 failed
— the whole family that validates the agent catalogue, plus the check that the
40 definitions are not 40 copies of one file.

It had never been seen because CI runs on Linux, and it did not show in a
long-lived local checkout because those files happen to sit there as LF.

The fix is one frontmatter parser, used by every assertion that needs one, and
it is **stricter** than what it replaced: the old check accepted a document
with no closing delimiter at all. Stripping carriage returns on read — the
obvious fix — was rejected, because it hides malformation along with line
endings.

Every structural assertion now runs over each of the 40 real documents rendered
both ways in memory, so a Linux pipeline exercises the CRLF path on every run.

### A change to product code is classified as a change to product code

The change-class globs decide which quality gates a diff invalidates and which
may be reused. They are rooted at a generated product, and nothing said so — so
when the factory ran the framework on its own product code, under
`profiles/product/template/`, every path classified as nothing. No classes
invalidates no gates, so the classifier reported every gate reusable for a
change to production code. G7 R2 hit this and made its gate decisions by hand.

The domain is now declared, and a factory path is normalised into it. One
vocabulary, one glob set, one step in front of them. A path that still matches
nothing is a stop rather than a silent reuse.

Proven against history: G7 R2's real diff now invalidates the four gates it
needed — accessibility, browser, screenshot evidence and independent review —
and is asserted not to have done so before.

### The telemetry summary has a place in the lifecycle

The derived summary and final acceptance could not both be satisfied, because
acceptance is itself an event. The summary is now a closure artifact finalised
immediately before the terminal transition; acceptance judges the event log and
the primary evidence; closure checks the summary, because otherwise nothing
would; and an escalated run's summary is checked by the human receiving it.

---

## Numbers

| | |
|---|---|
| Suite before | 499 assertions in the canonical file |
| Suite after | 558 |
| Full starter suite | 2351 generator, 424 documentation, 120 CLI, 21 e2e, 7 pytest |
| Mutations killed | 23 of 23, each by a named assertion |
| Windows proof | 61 files, 2244 tests, fresh CRLF checkout |
| Agents activated | 11 of 40 |
| Unclassified paths a product receives | 58 at the baseline, 19 now, 0 under any application directory |
| Files that lost a gate | 0, measured against the baseline vocabulary |

## Downstream

**No synchronisation required, verified rather than assumed.** What changed is
the orchestration contract, which ships into a generated product as
configuration, and a test file in the factory, which does not ship at all. No
application source, no migration, no dependency.

A generated product will receive the corrected contract the next time one is
generated or synced. Nothing in an existing product is wrong without it — the
old contract is not dangerous, it is incomplete — so no sync was initiated, and
initiating one is a separate decision with its own approval.

## Open after this cycle

| ID | Severity | Why it is open |
|----|----------|----------------|
| FW-GAP-007 | Medium | Not authorised by this cycle |
| FW-GAP-008 | Low | Not authorised by this cycle |
| FW-GAP-011 | Medium | The factory's own source is outside the declared domain — a question, not an edit |
| FW-GAP-012 | Low | `tests/**` classes a Node test as Python |
| FW-GAP-013 | Medium | 19 paths with no class; each needs a new class, and a new class needs a gate |

## The thing worth carrying

Two of the three HIGH findings in the independent review were defects in the
**fix**, not in what was being fixed — and one of them rebuilt the very
deadlock it was written to resolve, with `CLOSED` in place of
`final_acceptance`.

And then final acceptance found a third: the fix for the classifier had taken
eleven gates away from 26 product files, including independent review, by
writing the build-graph globs with a leading globstar. That is FW-GAP-006's own
failure mode produced by FW-GAP-006's fix.

Three remedies, three next defects, in one cycle. Each hid in the same place —
behind an assertion that asked what the contract *says* rather than what it
*does*. The telemetry group asserted the contract contained certain words,
which it did. The coverage assertion counted paths that classify as nothing,
so a path moving between two real classes was invisible to it. Both gaps are
now closed by assertions that measure an effect: an ordering, and a class
that may not appear inside an application.
