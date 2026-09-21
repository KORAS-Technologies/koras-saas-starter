# FW-HARDEN-001 — automated test results

Executed 2026-09-21 on this machine. Every number below is from a run whose
command is given; none is inferred.

Platform matters for this cycle more than usual: Windows 11, Git configured
`core.autocrlf=true` and `core.eol=crlf`, which is the configuration FW-DEF-002
is about.

---

## Reproductions, before any change

Run against a worktree of 7199f85 — a genuine fresh checkout under the Git
configuration above, not a simulation.

| What | Command | Result |
|------|---------|--------|
| FW-DEF-002 | `vitest run tests/orchestration.test.ts` | **41 failed, 458 passed (499)** — identical to the count G7 R2 recorded |
| The class boundary | `vitest run` (whole generator suite) | Only `orchestration.test.ts` fails on line endings. One other file failed on an unbuilt `dist`, which is my worktree and not a defect. |
| Documentation suite on the same tree | `vitest run` in `tests/docs` | 412 passed — CRLF-clean |
| FW-GAP-006 | a matcher implementing the contract's declared semantics, over representative paths | every `profiles/product/template/**` path returns no class |
| FW-GAP-006 consequence | computed from the gate inputs | from G7 R2's real diff only `automated_test_node` is derivable; 21 gates reusable, including all four that feature most needed |

The 41 failures break down as the 40 `has frontmatter naming itself`
assertions plus `does not ship forty near-identical files`, which is the
`\n\n` section regex. A third site — a `slice` one byte late under CRLF —
passed on both trees while measuring the wrong bytes, and was found by probe
rather than by failure.

---

## After the fix, attempt 1

| Suite | Result |
|-------|--------|
| `orchestration.test.ts` | 552 passed (was 499) |
| `pnpm lint` | 5 tasks successful; ruff all checks passed |
| `pnpm typecheck` | 5 tasks successful; mypy no issues |
| `pnpm test` | **FAIL** — 5 documentation-gate failures |

The five were all in this cycle's own evidence: three `file-references`
failures for example paths that name files in a generated product rather than
in the factory, and two `hedged-claims` failures for undated hedges.

Resolved without weakening either gate. The classifier's example paths moved
into fenced blocks, which the prose gates skip because — in the check's own
words — a fenced path names a shape rather than a file; writing them inline
would have been these documents claiming files the factory does not have. The
two hedges were dated.

## After the fix, attempt 2

| Suite | Files | Tests |
|-------|-------|-------|
| `create-koras-app` | 61 | **2351 passed** |
| `koras-docs-tests` | 5 | **424 passed** |
| `koras-cli` | 7 | **120 passed** |
| `koras-e2e` | 2 | 21 passed, 2 skipped |
| `pytest` | — | 7 passed |
| `pnpm lint` | 5 tasks | passed, plus ruff |
| `pnpm typecheck` | 5 tasks | passed, plus mypy |

Generation is covered inside the generator suite: `generated-builds.test.ts`
builds a product and a Control Plane from the templates, and the capability
variants are exercised by the suites around it.

---

## Windows proof

A worktree created fresh from the fix commit under this machine's normal Git
configuration. The agent definitions arrive CRLF — verified at the byte level
before running anything.

| What | Result |
|------|--------|
| Canonical suite at `575acaf` | **552 of 552 passed**, where 7199f85 failed 41 |
| Whole generator suite at `575acaf` | **61 files, 2244 tests, 0 failed** |
| Canonical suite at `939fdd5`, after review remediation | **557 of 557 passed** |
| 40 agents registered | yes |
| 40 agents valid | yes |
| Line-ending failures | none |

The second run was needed because `939fdd5` changed the parser regex itself,
so the first no longer covered the tree being accepted. Final acceptance made
the same observation independently and re-ran it, getting the same result.

The generator-suite row also settles the independent review's HIGH-2, which predicted
two further files would fail on CRLF. They do not: each defines a reader that
strips carriage returns, with a comment recording that this defect bit it once
already.

---

## Mutation proof

Each mutation is applied to the real tree, the suite is run, and the tree is
restored. A mutation that produces a compile error rather than a failing
assertion is not counted as a kill, and none did.

**Round 1: 16 of 16 killed.** **Round 2, after the independent review: 22 of
22.** **Round 3, after final acceptance: 23 of 23.** Each round added one
mutation per upheld finding, so every finding is now defended by something
that fails when it regresses.

| # | Mutation | Killed by |
|---|----------|-----------|
| M01 | Restore the LF-only opening delimiter | 42 assertions, starting with the frontmatter family |
| M02 | Restore the LF-only section regex | `does not ship forty near-identical files` |
| M03 | Stop requiring a closing delimiter | `refuses a document with no closing delimiter` |
| M04 | Normalise on read instead of matching both endings | 41 assertions |
| M05 | Accept a sloppy delimiter | `refuses a document with an opening delimiter with a trailing space` |
| M06 | Remove the factory prefix rule | 14 assertions |
| M07 | Remove the `.hbs` suffix rule | 5 assertions |
| M08 | Remove the stylesheet globs | the two stylesheet rows |
| M09 | Put `frontend_code` back below `backend_code` | the API-served stylesheet row |
| M10 | Broaden `documentation` over executable code | 21 assertions |
| M11 | Narrow `frontend_code` so packages escape | 5 assertions |
| M12 | Weaken the fail-closed rule | the known-hole assertion |
| M13 | Let acceptance judge the summary again | `keeps acceptance judging the log` |
| M14 | Drop the summary requirement from closure | `makes closure check the summary` |
| M15 | Claim the summary is final before acceptance | `finalises the summary after acceptance` |
| M16 | Drop the rule that acceptance may not be held | `does not reopen FW-GAP-003` |
| M17 | Remove `local/**` from `deployment_config` | the exact-orphan coverage assertion |
| M18 | Misstate the declared orphan count | the same |
| M19 | Let the diff helper drop unclassified paths | `reports an unclassified path as a stop` |
| M20 | Finalise the summary *at* closure instead of before it | `does not make closure wait for a summary that waits for closure` |
| M21 | Drop the escalated-branch checker | `says who checks the summary on the branch that never reaches closure` |
| M22 | Restore the untempered lazy capture | `stops at the first delimiter line` |
| M23 | Let the build-graph globs reach into packages again | `keeps a package own build configuration with its package` |

M17 and M18 are the ones worth noting: the coverage assertion they kill is the
one the independent review proved could not fail in its first form. Removing
the `.hbs` rule left the old version green.
