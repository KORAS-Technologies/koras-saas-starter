# G7R2-F01 — QA evidence audit and documentation audit

Executed 2026-09-21 by `qa-reviewer`, which produced none of this evidence. Both gates
are independent and this was one pass — `max_documentation_audits` is 1.

Raw output: `testing/runs/2026-09-21-08/qa-reviewer-output.txt`.

| Gate | Verdict |
|---|---|
| `qa_evidence_audit` | **PASS** |
| `documentation_audit` | **PASS** |

0 CRITICAL, 0 HIGH. Six findings, three MEDIUM and three LOW. `blocking_severities` is
`[CRITICAL, HIGH]`, so none blocked either gate.

## What the auditor checked rather than accepted

It read the artefacts with a shell instead of trusting the prose, which is the only way
this gate means anything.

- **The screenshots.** All nine exist, all carry the PNG magic bytes, all are tracked in
  `e677b54`, all sit at the canonical path shape. It confirmed by md5 that TC01's
  `step-01` and `step-06` really are byte-identical — the claim that turning the setting
  off returns the page to exactly what it was.
- **The accessibility arithmetic, by hand.** It recomputed the border pair
  (`#2b2b2b` on white → 14.16:1), both focus-ring pairs (5.17:1 and 4.06:1) and the body
  pair (21.00:1), and found the numbers correct.
- **The primary-evidence block's timing**, which is the one thing that cannot be checked
  after the fact if it is not checked properly: it established that the block was
  committed in `e677b54` while the verdicts and the expanded results came afterwards, so
  the evidence really was declared before the validating action rather than chosen once
  the result was known.
- **The register's own row count**, independently: 115 ID-keyed rows minus the four
  docoris correspondences is 111, which is what the Summary claims.
- **Its own role.** As the independent verifier named in the primary-evidence block, it
  recorded that the retained TC01 captures support the before-and-after claim *and no
  more*.

## Findings, and what was done about each

| ID | Severity | Finding | Action |
|---|---|---|---|
| F1 | MEDIUM | The file named `attempt-1` actually held the **second** failure (CRLF), and the first failure's raw output — the seven documentation-gate failures — was not retained at all. Two telemetry events cited the same file for different runs. A breach of `historical_failed_runs_are_retained`. | **Corrected.** The first run's raw output is retained as `pnpm-test-attempt-1-docs-gates.txt`, the CRLF capture is renamed `pnpm-test-attempt-2-crlf.txt`, and `automated-test-results.md` now records all three attempts including the CRLF one that FW-DEF-002 is entirely about. |
| F2 | MEDIUM | `release-notes.md` claimed **seven** assertions were each shown to fail against a counter-example. Six were. The seventh — the guard recording the two sibling settings as still dead — was never mutation-tested. Exactly the guard-that-only-ever-passed risk `quality-gates.yaml` exists to stop. | **Corrected** in both `release-notes.md` and `automated-test-results.md`: six of seven, and the seventh named as not mutation-tested with the reviewer's L1 blind spot stated. |
| F3 | MEDIUM | The results document restated the static case fields only for TC01, and `test_data` was absent for TC02–TC05 everywhere — the guide does not carry it per case either. | **Corrected.** `test_data` is now stated per case in the results, and the document says where the other static fields live rather than leaving the reader to find out. |
| F4 | LOW | TC02's screenshot is byte-identical to TC01's `step-04` — the same file under two names, counted in "nine genuine screenshots" without disclosure. Unlike the TC01 `step-01`≡`step-06` pair, which *was* disclosed. | **Disclosed** in `manual-test-results.md`, with the reason: the screenshot policy forbids capturing the same state twice, so re-photographing it would have been the violation, and presenting it as a tenth distinct image would have been worse. The measurement that actually carries TC02 was read from the live page, not from the image. |
| F5 | LOW | The "147 passed" browser run was cited to a run directory that held no Playwright output. The count was plausible and the method documented, but the raw capture a number is quoted from was not retained. | **Corrected.** The browser suite's output is retained at `testing/runs/2026-09-21-07/playwright-roundtrip-147-passed.txt`, and an amendment corrects the event's pointer. |
| F6 | LOW (informational) | As of 2026-09-21 this file still carried its pending placeholder — accurate for this very audit for this very audit, which the auditor could not update because it has no write tools. | **Replaced** by this document. |

## What was deliberately not done

**No second audit was run.** `max_documentation_audits` is 1 and it is spent. Every
correction above is one the auditor itself specified, so re-running the audit would be
asking the same reviewer whether its own instructions had been followed. What happens
instead, per `workflow.yaml` `rework.require_independent_reverification`, is that the
agent which found the defects confirms the fixes — a bounded confirmation against six
named findings, not a fresh pass over the whole directory.

**One executable file changed, and saying otherwise was a defect.** This section first
read "no executable change was made". It was false: `dc4a946` added two `MOVED` entries
to `tests/docs/file-references.test.ts`, so that the renamed evidence file could be
corrected without rewriting the append-only telemetry events that name it. Everything
else in that commit is documentation.

The gate accounting was nonetheless right, which is why the error survived until
`final-acceptance` withheld READY for it. `workflow.yaml` says at the code freeze that
*a change to tests, fixtures or documentation* consumes no budget and invalidates
nothing by itself, so the test edit is free and the invalidated set really is
`documentation_audit` and `final_acceptance` and nothing else. What was wrong was the
description, sitting in the document whose job is to certify that the record says no
more than happened. Corrected here and recorded as an amendment rather than quietly
rewritten.

**The first attempt at that amendment named the wrong event**, and `final-acceptance`
refused READY a second time for it: the false phrase is in telemetry event 32, and the
amendment was aimed at event 33, which never contained it. So the record stood
uncorrected while a correction sat beside it looking like a fix — which is worse than no
correction, because it reads as done. Both the real amendment and a second one naming
what the first got wrong are in `../telemetry-amendments.md` at 20:20Z, under a budget
extension the repository owner granted with its reason after the automated budget was
exhausted.

## What this audit does not establish

That the feature is correct — that is the code review's and the tests' business. This
gate asks only whether the evidence says what happened, whether it says no more than
happened, and whether somebody who did not produce it can check. On all three, yes.
