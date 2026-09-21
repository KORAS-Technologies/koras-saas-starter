# G7R2-F01 — test plan

Written before implementation. What will be run, by whom, and what each thing can and
cannot establish.

## Gate → evidence map

| Gate | Owner | What runs | Where the raw output goes |
|---|---|---|---|
| `automated_tests_pass` | `unit-test` | the factory's Node suites (`generators/create-koras-app/tests/`) and the Python suite | `testing/runs/<run-id>/` |
| `e2e_pass` | `e2e-test` | the product template's Playwright suite against a generated product, at 1440 and 375 | `testing/runs/<run-id>/` |
| `manual_qa_pass` | `manual-qa` | the cases in `manual/manual-test-guide.md`, against a running generated product | `manual/manual-test-results.md` |
| `screenshot_evidence_complete` | `test-documentation` | genuine captures from the executed steps | `manual/screenshots/<test-case-id>/` |
| `accessibility_pass` | `accessibility-qa` | computed-colour contrast measurement, keyboard and focus | `testing/runs/<run-id>/` |
| `qa_evidence_audit` | `qa-reviewer` | independent audit of the above | `testing/qa-evidence-audit.md` |

## Automated tests to be added

### `generators/create-koras-app/tests/product-shell.test.ts`

1. The generated shell reads `accessibility.highContrast` through `useSettingValue`
   with a `false` fallback.
2. The generated shell emits `data-contrast` on its root element, conditionally, and
   emits `undefined` (not `"normal"`, not `""`) in the false case.
3. `tokens.css` carries a `[data-contrast="high"]` rule.
4. That rule re-declares **only** custom properties that already exist in `:root` — a
   property invented inside the override is a failure.
5. Every value in that rule is a `light-dark()` pair — a flat colour would pin the
   appearance and break the theme toggle for these users.
6. The rule does **not** contain `!important`, and does **not** touch
   `--brand-primary`, `--brand-secondary` or `--brand-accent`.

### `generators/create-koras-app/tests/product-settings.test.ts`

7. A surfaced accessibility setting is honoured by client code. The suite already
   asserts the converse — that the four **hidden** settings are read by nothing — and
   the absence of this assertion is how a surfaced-but-dead control survived. The
   assertion is written so that it names the two siblings that are *still* dead, so
   that it records the open defect rather than asserting a falsehood about them.

### Mutation discipline

Each assertion above is a protective guard, so each is shown to **fail** against a
deliberate counter-example before its passing run is evidence. Planned mutations:

| # | Mutation | Must fail |
|---|---|---|
| M1 | delete the `data-contrast` attribute from the shell root | 1, 2 |
| M2 | change the false case to `'normal'` | 2 |
| M3 | delete the `[data-contrast="high"]` block from `tokens.css` | 3, 4, 5 |
| M4 | add a new `--brand-hc-foreground` property inside the block | 4 |
| M5 | replace one `light-dark()` pair with a flat hex | 5 |
| M6 | add `!important` to one declaration | 6 |

A mutation that does **not** fail is reported as a finding, not quietly dropped.

## Browser test

One Playwright case in the product template's `e2e/`, asserting the marker's presence
and absence and that the computed background actually changes — not merely that an
attribute is present. Run at 1440 and at 375.

**What it cannot establish:** whether the result is *readable*. That is measured, not
seen.

## Manual cases

Five, detailed in `manual/manual-test-guide.md`:

| ID | Scenario | Priority |
|---|---|---|
| TC01 | The flip — enable, navigate, observe the whole shell change; disable, observe it return with no `data-contrast` in the DOM | Critical |
| TC02 | Structure via borders — panels and cards remain distinguishable when surfaces stop being distinguished by tint | High |
| TC03 | Dark appearance — the pairs hold; white on black, not a pinned light mode | High |
| TC04 | **A tenant brand does not defeat it** — the decisive case | Critical |
| TC05 | 375px: mobile drawer, keyboard, focus visibility, Escape and focus return | High |

Verdicts are PASS, FAIL or BLOCKED and nothing else. BLOCKED carries a reason and is
never counted as a pass.

## Known limitation of this plan, stated up front

The factory has no running product. Every browser and manual case therefore runs
against a product **generated from the commit under test** into a scratch directory,
and the run record names the generation commit and the template digest. That is the
same arrangement Generator Integration uses, and it is the only one available: the
starter's own suites never render the application, which is why a defect that broke
every dashboard page once passed every local check.
