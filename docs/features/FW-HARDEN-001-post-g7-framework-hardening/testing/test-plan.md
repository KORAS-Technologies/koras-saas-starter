# FW-HARDEN-001 — test plan

Written 2026-09-21, before implementation. Every case below is automated;
there is no manual case, because nothing in this change reaches a rendered
surface. That is a claim the `user_interface` condition is not met, not a
preference — see `../execution-plan.md`.

The rule this plan is written to: **a test that asserts the fix exists is not
a test.** Each group below names the mutation that must make it fail.

---

## Group A — FW-DEF-002, the frontmatter parser

Run against the real 40 agent documents, each rendered twice in memory: once
with every line ending LF, once with every line ending CRLF. The pair matters
more than either half — it is what lets a Linux pipeline defend a Windows
checkout.

| # | Case | Expected |
|---|------|----------|
| A1 | Each of the 40 documents, LF, parses and names itself | PASS |
| A2 | Each of the 40 documents, CRLF, parses and names itself | PASS |
| A3 | Each of the 40 yields the same frontmatter either way, once the endings are set aside | PASS |
| A4 | Section extraction finds responsibilities and boundaries under both endings | PASS |
| A5 | No opening delimiter | refused |
| A6 | Opening delimiter with trailing space — `--- ` | refused |
| A7 | Four dashes — `----` | refused |
| A8 | Opening delimiter present, closing delimiter absent | refused |
| A9 | Closing delimiter not at the start of its line | refused |
| A10 | Empty document | refused |
| A11 | Frontmatter naming a different agent | refused |

**Mutations that must break Group A**

| Mutation | Must fail |
|----------|-----------|
| Restore `startsWith('---\n')` | A2 |
| Restore the `\n\n` section regexes | A4 |
| Make the carriage return optional *after* the closing delimiter too, so any `---` anywhere matches | A8, A9 |
| Accept a document with no closing delimiter | A8 |
| Normalise the document before parsing instead of matching both endings | A6, A7 — because normalising hides malformation as well as line endings |

The last one is the mutation worth having. The obvious fix for this defect is
to strip carriage returns on read, and it would pass A1 through A4 while
quietly weakening every malformation case.

---

## Group B — FW-GAP-006, normalisation

Tested on its own, before it is composed with anything.

Paths below are written in fenced blocks rather than inline. They are inputs
to a classifier, and most of them name a file in a *generated product* or a
deliberately invented fixture — neither of which exists in this repository.
The prose gates skip a fenced block for exactly that reason, and writing them
inline would be this document claiming files the factory does not have.

```text
B1  profiles/product/template/packages/ui/src/x.tsx   -> packages/ui/src/x.tsx
B2  profiles/control-plane/template/apps/admin/x.tsx  -> apps/admin/x.tsx
B3  profiles/_shared/template/local/config/x.yaml     -> local/config/x.yaml
B4  packages/ui/src/x.tsx                             -> unchanged
B5  apps/web/globals.css.hbs                          -> apps/web/globals.css
B6  profiles/product/template/README.md.hbs           -> README.md
B7  docs/ARCHITECTURE.md                              -> unchanged
B8  profiles/product/manifest.yaml                    -> unchanged, no template segment
B9  a path with Windows separators                    -> separators normalised
```

**Mutations:** removing either strip rule must fail B1–B3 or B5–B6; making the
prefix strip greedy enough to eat `profiles/product/manifest.yaml` must fail
B8.

---

## Group C — FW-GAP-006, the classification matrix

Each factory row is paired with its generated-product row: "these two agree"
is the property, and two unpaired assertions would let one drift.

```text
C1   profiles/product/template/packages/ui/src/data-table.tsx        frontend_code
C2   packages/ui/src/data-table.tsx                                  frontend_code
C3   profiles/product/template/packages/ui/src/styles/tokens.css     frontend_code
C4   packages/ui/src/styles/tokens.css                               frontend_code
C5   profiles/product/template/apps/web/src/app/globals.css.hbs      frontend_code
C6   apps/web/src/app/page.tsx                                       frontend_code
C7   profiles/product/template/apps/admin/src/app/page.tsx.hbs       frontend_code
C8   apps/admin/src/app/page.tsx                                     frontend_code
C9   profiles/product/template/services/api/routers/files.py         backend_code
C10  services/api/routers/files.py                                   backend_code
C11  profiles/product/template/e2e/roundtrip/settings.spec.ts.hbs    e2e_test
C12  e2e/roundtrip/settings.spec.ts                                  e2e_test
C13  styles/brand.css                                                frontend_code
C14  services/api/static/mail.css                                    frontend_code
C15  docs/ARCHITECTURE.md                                            documentation
C16  docs/features/x/requirements/user-story.md                      feature_scope
C17  docs/features/x/testing/manual/results.md                       manual_evidence
C18  profiles/product/template/supabase/migrations/1.sql             database_migration_or_policy
C19  profiles/product/template/package.json.hbs                      dependency
C20  profiles/control-plane/template/apps/admin/src/page.tsx.hbs     frontend_code
C21  generators/create-koras-app/src/generation/writer.ts            unclassified
```

Three of those carry the argument rather than the coverage. **C13** is a
stylesheet outside any application directory, and **C14** one served by the
API — both are presentation, and neither used to say so. **C20** exercises
the other profile, because the classifier is shared. **C21** is FW-GAP-011,
asserted as a known hole so that closing it later has to be deliberate.

**Coverage assertion, not a table.** Every tracked file in all three template
trees is classified, and the orphan set is asserted **exactly** against the
count the contract declares — not merely asserted empty. Adding a file type
moves the set and fails; so does closing a hole without saying so; so does
deleting a glob.

The first version of this assertion could not fail, and the independent review
proved it: it walked the filesystem rather than git, so it counted
`__pycache__`; and five of its six roots were catch-all directory globs, so no
new file type under them could ever be unclassified. Removing the `.hbs` rule
left it green. It is the one case in this plan that had to be rewritten after
being written, and it is worth saying so — a coverage test that cannot fail is
worse than no coverage test, because it is counted.

**Mutations that must break Group C**

| Mutation | Must fail |
|----------|-----------|
| Remove the template-prefix strip | C1, C3, C5, C7, C9, C11, C18, C19, C20, coverage |
| Remove the `.hbs` strip | C19, coverage |
| Remove `**/*.css` | C13, C14 |
| Move `frontend_code` back below `backend_code` | C14 |
| Broaden `documentation` to `**/*` | C1, C2 and most of the table |
| Narrow `frontend_code` so product code reads as docs-only | C1, C2 |
| Remove `local/**` from `deployment_config` | coverage — the orphan count moves |
| Use a glob syntax the matcher does not implement | the glob-syntax guard |

---

## Group D — FW-GAP-006, gate consequence

Classification is not the point; what it licenses is.

| # | Case | Expected |
|---|------|----------|
| D1 | The G7 R2 diff, classified by path, invalidates `accessibility_pass`, `e2e_pass`, `screenshot_evidence_complete` and `independent_code_review` | PASS |
| D2 | The same diff under the uncorrected globs leaves all four reusable | PASS — the historical witness, asserted as a *negative* so the fix is proven to have changed something |
| D3 | A documentation-only edit still reuses the executable gates | PASS |
| D4 | An unclassified path does not read as "no classes, reuse everything" | PASS |
| D5 | A diff mixing a classified and an unclassified path returns both the classes **and** the stop list | PASS |

D5 exists because the first implementation of the diff helper filtered the
unclassified paths away — the precise thing the fail-closed rule it was written
to demonstrate forbids in as many words. A reference implementation that breaks
its own rule teaches the defect to everyone who copies it.

D2 is the load-bearing case. Without it the suite proves the new behaviour and
not that the old behaviour was wrong.

---

## Group E — FW-GAP-010, lifecycle ordering

| # | Case | Expected |
|---|------|----------|
| E1 | The contract names the terminal state at which the summary is finalised | PASS |
| E2 | The contract says acceptance judges the log, and names the summary as not its input | PASS |
| E3 | `final_acceptance` does not require the summary | PASS |
| E4 | `CLOSED` requires the summary to exist and agree with the log | PASS |
| E5 | The ordering summary → acceptance → closure → summary is not circular: acceptance has no dependency on the summary | PASS |
| E6 | The append-only and "zero is a measurement" rules are unchanged | PASS — FW-GAP-003 is not reopened |
| E7 | The summary is finalised *before* the closure transition, and the transition is not an event it waits for | PASS |
| E8 | The escalated branch names who checks the summary | PASS |

E7 is the load-bearing one, and it was added after the fact. The first draft
said the summary was finalised **at** the terminal state while closure required
a finalised summary to be entered — FW-GAP-010 rebuilt one step further on,
with `final_acceptance` swapped for `CLOSED`. Group E as first written was
entirely "the YAML contains this string", and nothing in it could have caught
that. E7 asserts the ordering instead.

---

## Group F — the suites that must stay green

| Suite | Why it is listed |
|-------|------------------|
| Full generator suite | The 40-agent catalogue, the profile isolation, the template parity |
| Documentation suite | These documents are inside its walk |
| Repository lint and typecheck | The test file changes are TypeScript |
| Product, product-full, product-minimal, Control Plane generation | The contract files are template-owned and ship into a product |
| Python lint, typecheck and tests | Unchanged by this work, run to show it |
| Windows CRLF worktree, canonical suite | FW-DEF-002's acceptance evidence |

---

## What is not tested, and why

- **No manual case.** Nothing reaches a rendered surface.
- **No browser case.** Same reason.
- **No security case.** No floor signal fired; the change touches no
  authentication, authorization, tenancy, secret or data path. Stated so that
  its absence reads as a decision.
