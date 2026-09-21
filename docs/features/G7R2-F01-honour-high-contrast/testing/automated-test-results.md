# G7R2-F01 — automated test results

Required because `automated_verification_executed` is met. Executed results, not
claims. Raw output lives in the run directories under `testing/runs/`, which are
append-only; this document points at them and does not absorb them.

| | |
|---|---|
| **Base commit** | `48e762a` on `develop`, plus this feature's working-tree diff |
| **Where** | the feature worktree, `../.koras-worktrees/koras-saas-starter/G7R2-F01` |
| **Executed by** | `developer-1` (targeted suites, mutations) and `engineering-orchestrator` (full suite) |
| **Date** | 2026-09-21 |

## Targeted suites — `developer-1`

Command, verbatim, from `generators/create-koras-app`:

```
pnpm exec vitest run tests/product-shell.test.ts tests/product-settings.test.ts
```

```
 RUN  v4.1.11 .../G7R2-F01/generators/create-koras-app
 Test Files  2 passed (2)
      Tests  109 passed (109)
   Duration  3.07s
```

Seven new assertions, all passing:

- `product-settings.test.ts > a surfaced accessibility setting is honoured > honours accessibility.highContrast, and records its two siblings still dead`
- `product-shell.test.ts > the shell honours the high-contrast setting >` — reads the setting through `useSettingValue`; emits `data-contrast` conditionally with `undefined` when off; adds the `[data-contrast="high"]` rule; re-declares only properties that already exist in `:root`; writes every override as a `light-dark()` pair; uses no `!important` and leaves the brand identity tokens alone.

## Mutation results — the guard discipline

`quality-gates.yaml` requires a new protective guard to be shown failing against a
deliberate counter-example before its passing run counts as evidence. Six mutations,
applied one at a time and reverted between.

| # | Mutation | Expected to fail | Failed? |
|---|---|---|---|
| M1 | delete the `data-contrast` attribute from the shell root | assertions 1, 2 | yes — and only those |
| M2 | change the false case to `'normal'` | 2 | yes — only 2; 1 still passed |
| M3 | delete the `[data-contrast="high"]` block | 3, 4, 5 | yes |
| M4 | add a new `--brand-hc-foreground` inside the block | 4 | yes — only 4 |
| M5 | replace one `light-dark()` pair with a flat hex | 5 | yes — only 5 |
| M6 | add `!important` to one declaration | 6 | yes — only 6 |

No mutation survived, and each failed exactly the assertions predicted before it was run.

**Six of the seven new assertions are covered here, not all seven.** M1-M6 exercise the six
assertions in `product-shell.test.ts`. The seventh - the guard in `product-settings.test.ts`
recording that `accessibility.reducedMotion` and `accessibility.fontScale` are still read by
nothing - was **not** mutation-tested: no mutation honoured a sibling. The independent review
judged it meaningful rather than tautological, because it can fail when somebody honours one,
and named its blind spot as finding L1: it inspects only the shell file, so a sibling honoured
in `tokens.css` would leave it green. Stated here because `quality-gates.yaml` requires a new
protective guard to be shown able to fail, and this one has not been.

**A measurement error inside this mutation run, recorded rather than smoothed over.**
On the first attempt `developer-1` reverted M1 with `git checkout -- <file>`. The
implementation was uncommitted working-tree state, so that restored the file to `HEAD`
and removed the feature entirely; M2 then ran against an un-implemented file and
produced a spurious "M2 also fails assertion 1". It was caught from the assertion diff
— the received file had no `useSettingValue` import — the implementation was
re-applied, the baseline re-established at 109 passing, and all six mutations were
redone with file backups. The table above is the corrected run. The first, wrong result
is recorded here because a mutation table that has only ever been right is the same
kind of artefact as a guard that has only ever passed.

## Full suite — `engineering-orchestrator`

Command, verbatim, from the worktree root: `pnpm test`.

**First run: FAIL.** `koras-docs-tests` — 7 failed, 387 passed of 394. Every failure
was in this feature's own documentation, and every one was real:

| Check | What it caught |
|---|---|
| `file-references` (5) | Documents naming files that did not exist yet — the results, audit and findings documents this run had planned but not written. |
| `hedged-claims` (1) | Four undated hedges — "not yet", "currently" — inside `testing/runs/2026-09-21-01/planner-output`, which is **raw append-only agent output that policy forbids editing**. |
| `identifiers` (1) | SESSION_RUNTIME and TEST_DEFECT (unquoted here deliberately), two tokens this repository does not declare, used to classify a probe result. |

Classification: a documentation defect, all seven, in this feature's evidence. No
product code was implicated and the product suites were unaffected.

**Remediation, cycle 1 of `max_test_fix_cycles` 2, targeted:**

- The raw agent transcripts moved from `.md` to `.txt`. The prose gates walk `.md`
  under `docs/` only, and a captured transcript is output, not documentation — the
  probe captures in the same run directory were already `.txt`. This resolves the
  contradiction without editing a word of the evidence and without weakening the gate
  for anything that *is* documentation.
- The two invented tokens were corrected to `SESSION_OR_TOOL_HEALTH`, which is the
  vocabulary `agent-registry.yaml` actually declares, and the correction was recorded
  as a telemetry amendment rather than as a silent edit.
- The missing documents were written.

Both are recorded as framework findings in `release/framework-findings.md`; neither is
a defect in the product.

**Second run: FAIL, for a different and unrelated reason.** 41 of 499 in
`orchestration.test.ts`, plus a 120-second `beforeAll` timeout in
`product-governance.test.ts` while the browser suite held the machine. Neither was this
feature: the 41 are FW-DEF-002, a CRLF checkout artefact that makes the 40-agent validation
suite fail in any fresh Windows clone, and the timeout is contention. Retained at
`testing/runs/2026-09-21-04/pnpm-test-attempt-2-crlf.txt`.

**Third run: PASS**, on the frozen commit with the worktree re-checked-out at `core.eol=lf`
so that it holds what the blobs actually contain. 2191 + 400 + 120 + 21 Node assertions,
7 Python, 5 of 5 turbo tasks, exit 0. Retained at
`testing/runs/2026-09-21-04/pnpm-test-attempt-3-green.txt`. Nothing about the tracked content
differed between the second run and the third; `git status` was clean on both sides.

## What these results do not establish

That anything renders. Every assertion above reads a template or a generated file as
text, or asserts a rule's presence. The browser case added to
`e2e/roundtrip/settings.spec.ts.hbs` was **not executed by `developer-1`** — the factory
has no running product, no database and no `E2E_DATABASE_URL`, and the `.hbs` spec is
only runnable once rendered into a generated product. It was verified by inspection
there, and executed separately; that execution is recorded in its own run directory and
in `manual/manual-test-results.md`.
