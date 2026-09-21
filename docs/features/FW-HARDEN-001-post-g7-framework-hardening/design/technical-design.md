# FW-HARDEN-001 — technical design

Written 2026-09-21, after reproducing all three findings and before changing
anything. Every number below was measured on this machine on that date, and
the commands that produced them are in `../testing/test-plan.md`.

---

## 1. FW-DEF-002 — the line-ending class

### What was reproduced

A worktree of 7199f85 checked out with `core.autocrlf=true`, which is the
Windows default, then the canonical suite:

```
Tests  41 failed | 458 passed (499)
```

Identical to the count G7 R2 recorded. The rest of the generator suite and all
412 documentation assertions pass on the same tree, so the class is confined to
one file.

### The class, enumerated rather than guessed

Every assertion in `orchestration.test.ts` that parses the *structure* of an
agent Markdown document. There are three sites, and only two of them fail
loudly:

| Line | Assertion | Under CRLF |
|------|-----------|------------|
| 555 | `body.startsWith('---\n')` | **fails** — 40 of them |
| 556 | `body.slice(4, body.indexOf('\n---', 4))` | **silently wrong** — the slice begins one byte late, so the frontmatter block starts with a stray newline |
| 598–599 | `/## Responsibilities\n\n(...)\n\n## Boundaries/` | **fails** — the capture is empty, and the line count derived from it collapses to 1 |

The silent one is the reason this is treated as a class. It passes today and
would keep passing while measuring the wrong bytes.

Two further sites were suspected and cleared by measurement rather than by
reading:

- `/^description: (.+)$/m` is safe. In JavaScript a carriage return is a line
  terminator, so `.` already excludes it and `$` already matches before it.
- `split('\n')` on the section bodies yields the right *count*; only its input
  was broken.

Sites elsewhere in the file that read other file types were checked and are
safe for stated reasons: shell scripts are pinned to LF by `.gitattributes`,
generated output passes through `toUnixLineEndings` in the writer, and the two
remaining substring searches contain the newline they look for.

### The correction

One frontmatter parser, used by every site that needs one.

```ts
const AGENT_DOCUMENT = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/
const LINE = /\r?\n/
```

Chosen over the alternative — pinning `*.md` to `eol=lf` in `.gitattributes` —
for the reason the G7 R2 findings gave: pinning fixes this repository's
checkout and leaves the parser wrong, and the parser is what every future
assertion will reuse. Pinning also does nothing for a product generated into a
tree whose attributes nobody controls.

The parser is deliberately **stricter** than the code it replaces, not looser.
`body.startsWith('---\n')` accepts a document with no closing delimiter at all;
the regex requires both, and requires the closing delimiter to end the line.
Weakening validation to accommodate a line ending would be the wrong trade and
is asserted against.

### Why the correction does not need a Windows machine to be believed

The regression converts each of the 40 real agent documents to LF and to CRLF
in memory and runs the whole structural family over both. A Linux pipeline
therefore exercises the CRLF path on every run. The Windows checkout remains
the acceptance evidence; it is no longer the only thing that could catch a
regression.

---

## 2. FW-GAP-006 — one vocabulary, one path domain

### What was reproduced

The globs were applied to representative paths by a matcher implementing the
semantics the file declares — ordered classes, first match wins. Results on
7199f85:

| Path | Class |
|------|-------|
| `profiles/product/template/packages/ui/src/styles/tokens.css` | none |
| `profiles/product/template/packages/ui/src/shell/product-shell.tsx.hbs` | none |
| `profiles/product/template/e2e/roundtrip/settings.spec.ts.hbs` | none |
| packages/ui/src/data-table.tsx (a generated product) | `frontend_code` |
| services/api/static/mail.css (a generated product) | `backend_code` |

And the consequence, computed from the gate inputs rather than asserted:
from G7 R2's real diff only `automated_test_node` is derivable, which leaves
21 gates reusable including all four that feature most needed.

### One correction to the register's wording

The register says no class matches a `.css` path **at all, in either tree**.
That is not quite what is true, and the difference matters for the fix. A
stylesheet under `apps/` or `packages/` already classifies as `frontend_code`
— by its directory. What is actually wrong is that nothing classifies a
stylesheet *as a stylesheet*, so one sitting anywhere else is classified by its
neighbours: a stylesheet at services/api/static/ reads as server-side code, which
invalidates the backend gates and leaves the accessibility and screenshot
gates standing. Absence would have been safer than that.

### The two candidate models

**A — anchor the globs.** Rewrite `packages/**` as `**/packages/**` and so on.

Rejected. It does not add factory support so much as delete the root anchoring
that gives each glob its meaning. `**/e2e/**` would claim
`packages/ui/e2e/`, `**/tests/**` would claim `services/api/tests/`, and
`**/docs/**` would pull any application's own `docs/` directory into
`documentation`. It is also exactly the "ad-hoc globs with no defined path
domain" this cycle was told not to produce.

**B — declare the domain and normalise into it.** Chosen.

### The chosen model

> **The classifier's path domain is the generated product repository root.**
> A path from anywhere else is mapped into that domain before it is matched.

The mapping is two rules, both of which state the same thing — *what this file
becomes in a product*:

1. Strip a leading `profiles/<anything>/template/`.
2. Strip a trailing `.hbs`.

Then match, unchanged, against globs that keep their root anchoring.

This is one applicability vocabulary, as V2.1 requires. There is no second
classification system: there is one set of classes, one set of globs, and one
normalisation step in front of them. The factory/product difference is absorbed
once, in a named step that is tested on its own, instead of being smeared
across eleven glob lists.

The second rule earns its place independently of the factory question. 179 of
the product template's application files carry the `.hbs` suffix, and an
extension-matched class cannot see through it: `README.md.hbs` classified as
nothing before, and as `documentation` after.

Measured against the whole tracked set — 462 files under the product template's
`apps`, `packages`, `services`, `python-packages`, `e2e` and `supabase`
directories — the corrected classifier leaves **zero** unclassified.

### The stylesheet rule

`frontend_code` gains `**/*.css` and `**/*.scss`, and the class moves above
`backend_code` in the ordering so that an extension rule about presentation
beats a directory rule about where the file is served from. The two classes
share no directory, so nothing else changes hands.

### Fail closed

Before 2026-09-21 a path matching no class yielded the empty set, and the empty set
means every gate is reusable. That is the most dangerous possible default and
it is the shape of FW-GAP-006 itself. The contract gains an explicit rule: an
unclassified path is not "nothing changed", it is a stop, and a human decides.

The rule is backed by a test that enumerates the real tracked product files
rather than a hand-written list, so a file type nobody anticipated fails the
build on the day it is added rather than silently reusing every gate.

### Deliberately not fixed

Two things the matrix found that this cycle is not authorised to change, named
here and carried to the register so they are not rediscovered:

- **FW-GAP-011** — the factory's own source, `generators/` and `tooling/`, is
  outside the declared domain and classifies as nothing.
- **FW-GAP-012** — `tests/**` sits under `automated_test_python` and is reached
  before the Node patterns, so a Node test in the factory's root `tests/` tree
  classifies as a Python test. This repository has two such workspaces.

---

## 3. FW-GAP-010 — the summary is a closure artifact

### The deadlock, stated as an ordering problem

- `derived_summary.generated_after` is the final applicable lifecycle or gate
  event, and generating it with an applicable event outstanding is forbidden.
- `final_acceptance` is a gate, so running it produces events.
- Definition of Done item 7 requires documentation the change made wrong to be
  updated, and acceptance reads the summary as such a document.

Generate before acceptance and the contract is breached; generate after and
acceptance meets an unfinished document.

### The model adopted

```
gates … → final_acceptance          judges the event log and the primary evidence
        → human gates, escalations  append events
        → CLOSED                    terminal state reached
        → derived summary finalised last act of the lifecycle
```

Four answers, in the contract's own words:

| Question | Answer |
|----------|--------|
| When is the summary final? | At the terminal state — `CLOSED`, or the escalation for a run that stops there. |
| What does Final Acceptance judge? | The event log and the required primary evidence. Never the summary. |
| May acceptance append events after the summary? | It appends them after any *draft*. A draft is not the artifact the contract binds; regenerating is already declared safe. |
| Which is authoritative when they differ? | The log, which the contract already said. |

The summary is therefore **post-acceptance**, and it is excluded by name from
Definition of Done item 7 — not because it does not matter, but because it is
generated after the item is judged.

### Checked against the two things it could break

**FW-GAP-003** was a final count written *before* the event it counted. This
correction moves finalisation strictly later, never earlier. It cannot reopen
it, and the rule forbidding a value no event supports is untouched.

**A new hole**, had the change stopped at "acceptance does not judge the
summary": nothing would check the summary at all. So the `CLOSED` state gains
a requirement — the summary exists and agrees with the log — which runs after
acceptance and therefore closes the loop without re-creating the cycle.

### Why this is bounded

Contract wording in three files, one Definition-of-Done clause, and tests. No
runtime, no persistence, no state machine, no CLI. It qualifies for
implementation under this cycle's own rule rather than being left open.

---

## Files this design changes

| File | Change |
|------|--------|
| `profiles/product/template/.claude/orchestration/gate-invalidation.yaml` | Path domain, normalisation, stylesheet rule, class ordering, fail-closed rule |
| `profiles/product/template/.claude/orchestration/telemetry.yaml` | Summary finalisation and what acceptance judges |
| `profiles/product/template/.claude/orchestration/quality-gates.yaml` | What `final_acceptance` judges |
| `profiles/product/template/.claude/orchestration/lifecycle.yaml` | `CLOSED` requires the summary |
| `profiles/product/template/.claude/orchestration/definition-of-done.md` | Item 7 exclusion |
| `generators/create-koras-app/tests/orchestration.test.ts` | Frontmatter parser, classifier matrix, mutation proofs |
| `docs/platform/gap-defect-register.md` | Status of three rows, two new rows |
