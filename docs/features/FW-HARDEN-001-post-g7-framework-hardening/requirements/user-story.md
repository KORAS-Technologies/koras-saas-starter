# FW-HARDEN-001 — post-G7 framework hardening

Maintenance, not a product feature. The user is whoever runs the next feature
through the engineering framework, and the three things below are ways the
framework misinformed them as of 2026-09-21.

Raised 2026-09-21, from the findings G7 R2 produced and deliberately did not
fix. The accepted G7 R2 baseline is commit 7199f85; this work starts there.

---

## Story

As an engineer running a feature through the Koras engineering framework, I
need the framework's own validation and classification to be correct on the
machine I work on and for the paths I actually edit, so that a green suite
means the catalogue is intact and a reused gate means nothing relevant changed.

---

## The three findings in scope

### FW-DEF-002 — High, defect

A fresh Windows checkout cannot pass the framework's own validation suite.
`.gitattributes` declares `* text=auto`, which converts Markdown to CRLF on
checkout, and `orchestration.test.ts` parses the 40 agent definitions with
assertions written for LF.

**Expected:** a valid agent document validates whatever its line endings;
an invalid one is refused.
**Actual, measured on this machine 2026-09-21:** 41 of 499 assertions fail.

### FW-GAP-006 — High, gap

The change-class path globs in `gate-invalidation.yaml` are written for a
generated product root. The factory holds the same product code under
`profiles/product/template/`, and the directory-anchored globs do not reach it.
Stylesheets are classified by the directory they sit in rather than by what
they are.

**Expected:** an edit to product code is classified as product code, wherever
that code lives in this estate.
**Actual, measured 2026-09-21:** every factory-resident product path classifies
as nothing, so every gate reads as reusable.

### FW-GAP-010 — Medium, gap

The derived telemetry summary and the `final_acceptance` gate cannot both be
satisfied, because acceptance is itself an event and the contract requires the
summary to be generated after the last event.

**Expected:** an ordering exists that satisfies the contract.
**Actual:** none does. G7 R2 resolved it by a ruling from the repository owner
and recorded the ruling rather than amending the contract.

---

## Acceptance criteria

### FW-DEF-002

1. Every one of the 40 agent definitions validates when its content is LF.
2. Every one of the 40 validates when the identical content is CRLF.
3. A document with no opening delimiter is refused.
4. A document with a malformed opening or closing delimiter is refused.
5. A document whose frontmatter does not name its own agent is refused.
6. Restoring the line-ending assumption makes the suite fail — the regression
   proves the defect, not the fix's existence.
7. The correction addresses every assertion in the file that parses agent
   Markdown structure, not the first one observed to fail.

### FW-GAP-006

8. The file declares, in prose a reader cannot mistake, which path domain its
   globs are written against.
9. A factory-resident product path and its generated equivalent classify
   identically.
10. A stylesheet classifies as client-side production code.
11. Every tracked file under the product template's application directories
    classifies as something.
12. The four gates G7 R2 needed — `accessibility_pass`, `e2e_pass`,
    `screenshot_evidence_complete` and `independent_code_review` — are
    invalidated by that feature's real diff, and were not before.
13. A documentation-only edit still reuses the executable gates.
14. Removing any part of the correction makes a test fail.

### FW-GAP-010

15. The contract states when the derived summary is final, relative to
    acceptance.
16. The contract states what `final_acceptance` judges.
17. No ordering of summary, acceptance and closure is left circular.
18. The correction does not reopen FW-GAP-003, whose failure was a count
    written *before* the event it counted.

---

## Explicit exclusions

Named so that the next reader does not have to work out whether they were
forgotten.

| Excluded | Why |
|----------|-----|
| FW-GAP-007, FW-GAP-008 | Open, and not authorised by this cycle. |
| FW-GAP-009 | Already fixed in G7 R2. |
| A third G7 round | G7 is complete. This is maintenance against its baseline. |
| Any change to agent count, names, capabilities or activation rules | The catalogue is not in question; the suite that validates it is. |
| Rewriting any G7 R2 evidence | Referenced, never edited. |
| Downstream product repositories | Verified not required rather than assumed — see the release notes. |
| The factory's own generator and tooling source | Outside the classifier's declared domain. Recorded as FW-GAP-011 rather than fixed here. |
| Node test files under the factory's root `tests/` tree | A misclassification found while building the matrix. Recorded as FW-GAP-012 rather than fixed here. |
