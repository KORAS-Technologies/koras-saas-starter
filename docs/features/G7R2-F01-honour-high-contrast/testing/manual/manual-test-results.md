# G7R2-F01 — manual test results

Executed by `manual-qa` against a running product on 2026-09-21. Verdicts are PASS,
FAIL or BLOCKED and nothing else.

## Build and account context

| | |
|---|---|
| **Commit under test** | `e677b54` on `feature/G7R2-F01-honour-high-contrast` (code freeze) |
| **Build** | a product generated from that commit by `create-koras-app` into a scratch directory, `pnpm install`, `next build` — the same arrangement Generator Integration uses, because the factory has no running product of its own |
| **Template digest** | recorded in the generated project's `.koras/project.yaml` |
| **Stack** | a Postgres database created for this pass, this product's own migrations applied in order, `e2e/support/seed.sql`, a local identity provider, this product's FastAPI API against that database, and the web application pointed at both |
| **Nothing bypassed** | the API discovers the provider's JWKS and verifies an RS256 signature, the audience, the issuer and the expiry exactly as in production. The API refused to start on a role granted BYPASSRLS, so row-level security is enforced. What is local is the provider, not the verification. |
| **Account** | the seeded member, `signInAs` minting a session through the application's own function |
| **Widths** | 1440 for TC01–TC04, 375 for TC05 |
| **Executed by** | `manual-qa`, driving a real Chromium through the product's own harness |

**One thing this context does not claim.** No human being looked at these screens. The
`manual_qa` gate's owner in this framework is an agent, and the evidence below is an
agent executing the steps in a real browser against a real database. That is stronger
than an automated assertion and weaker than a person's eye, and calling it either one
without saying so would be the dishonesty the evidence rules exist to prevent.

## Results

**Where the static fields live.** Each case's objective, priority and preconditions are in
`manual-test-guide.md` and are not restated per case below, except for TC01. The results
document carries what execution produced: steps, expected, actual, verdict and evidence.
`test_data` is stated per case here, because it is the one required field the guide does not
carry for every case.

| Case | Test data | Verdict | Evidence |
|---|---|---|
| G7R2-F01-TC01 — the flip | `accessibility.highContrast`: false → true → false | **PASS** | `screenshots/G7R2-F01-TC01/` |
| G7R2-F01-TC02 — structure via borders | `accessibility.highContrast`: true; viewport 1440; light appearance | **PASS** | `screenshots/G7R2-F01-TC02/` |
| G7R2-F01-TC03 — the dark appearance | `accessibility.highContrast`: true; `prefers-color-scheme: dark` | **PASS** | `screenshots/G7R2-F01-TC03/` |
| G7R2-F01-TC04 — a tenant brand does not defeat it | `tenant_settings.branding` set to a strong palette (`backgroundColor` `#fde68a`, `surfaceMutedColor` `#fef9c3`, `primaryColor` `#b91c1c`, and the dark pair for each); `accessibility.highContrast`: false → true | **PASS** | `screenshots/G7R2-F01-TC04/` |
| G7R2-F01-TC05 — 375px, keyboard and focus | `accessibility.highContrast`: true; viewport 375×812 | **PASS** | `screenshots/G7R2-F01-TC05/` |

5 planned, 5 executed, 5 PASS, 0 FAIL, 0 BLOCKED.

---

### G7R2-F01-TC01 — the flip

| | |
|---|---|
| **Priority** | Critical |
| **Preconditions** | Signed in as the seeded member; `accessibility.highContrast` unset, so the platform default `false` applies; light appearance. |
| **Test data** | `accessibility.highContrast`: false → true → false |

| # | Action | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | Load `/dashboard` | stock palette, no marker | `data-contrast` **absent**; shell root background `rgb(248, 250, 252)`; heading `rgb(15, 23, 42)` | PASS |
| 2 | Inspect the shell root | no `data-contrast` attribute | absent — not `""`, not `"normal"` | PASS |
| 3 | Turn **High contrast** on at `/dashboard/preferences` and save | the value is stored | saved; the page announced the outcome | PASS |
| 4 | Return to `/dashboard` | the whole signed-in surface re-skins | `data-contrast="high"`; background `rgb(255, 255, 255)`; heading `rgb(0, 0, 0)`; tokens resolved to `light-dark(#fff,#000)` and `light-dark(#000,#fff)` | PASS |
| 5 | Inspect the shell root | `data-contrast="high"` | as expected | PASS |
| 6 | Turn it off and return to `/dashboard` | the page is exactly as it was | marker absent; background `rgb(248, 250, 252)`; heading `rgb(15, 23, 42)` | PASS |

**Evidence:** `step-01-stock-palette-off.png` (the starting state, without which step 4 is
meaningless), `step-04-high-contrast-on.png` (the transition this case exists to show),
`step-06-returned-to-stock.png` (the return — a one-way change would pass step 4 and
still be a defect).

**Worth recording:** `step-01` and `step-06` are **byte-identical**, 73,826 bytes each.
Turning the setting off returns the rendered page to precisely what it was, which is a
stronger statement of AC2 than the assertion that asked for it.

**On timing.** The test plan predicted, before execution, that the flip would appear on
the next server render rather than instantly, because effective settings are resolved
once per request in the dashboard layout. That is what was observed: the change is
present after navigating, and the case was written to navigate. No instant client-side
repaint was seen or expected.

---

### G7R2-F01-TC02 — structure survives when tint stops carrying it

| # | Action | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | With high contrast on, load `/dashboard` at 1440 | the sidebar and cards stay distinguishable by border once surfaces stop differing by tint | sidebar right border computed `rgb(43, 43, 43)` (`#2b2b2b`) against a `rgb(255, 255, 255)` surface — 14.16:1, visibly present rather than a hairline | PASS |

**Evidence:** `step-01-borders-carry-structure.png`. **Disclosure: this is the same capture as
TC01's `step-04`, byte for byte** - the same page in the same state, kept under TC02's name
because TC02's claim is about what that image shows rather than about a different moment. The
screenshot policy forbids capturing the same state twice, and re-photographing it would have
been exactly that; presenting it as a tenth distinct image would have been worse. The border
measurement that carries this case is `rgb(43, 43, 43)`, read from the live page rather than
from the image. *Purpose: proves the design's central
trade — hierarchy moved from tint to border — actually works. This was named in the plan
as the case most likely to fail.*

---

### G7R2-F01-TC03 — the dark appearance

| # | Action | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | With high contrast on, switch to the dark appearance | white on black, still maximal; not a pinned light mode and not the stock dark palette | `data-contrast="high"`; shell root background `rgb(0, 0, 0)`; heading `rgb(255, 255, 255)` | PASS |

**Evidence:** `step-01-dark-high-contrast.png`. *Purpose: proves the `light-dark()` pairs
survived. The most likely implementation slip is a flat hex, which looks correct in light
and breaks here — and mutation M5 confirms an assertion catches it too.*

---

### G7R2-F01-TC04 — a tenant brand does not defeat it

The decisive case. Run against a tenant whose `tenant_settings.branding` was set to a
strong, unmistakable palette before this pass, so that branded and unbranded cannot be
confused.

| # | Action | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | High contrast **off**, load `/dashboard` | the tenant's brand is visibly in effect | shell root background `rgb(254, 249, 195)` — the tenant's own colour, not the stock `rgb(248, 250, 252)`; `--brand-primary` `#b91c1c` | PASS |
| 2 | Turn high contrast **on** and reload | text, canvas and surfaces go to the high-contrast palette, **not** the tenant's | `data-contrast="high"`; background `rgb(255, 255, 255)`; heading `rgb(0, 0, 0)`; `--brand-primary` **still** `#b91c1c` | PASS |

**Evidence:** `step-01-tenant-brand-in-effect.png` (establishes branding is real; without
it step 2 proves nothing) and `step-02-accessibility-beats-brand.png`.

**This is the finding the case existed to produce.** The cascade argument in
`ux-design.md` section 3 — a declaration on the element beats an inherited value from the
parent's inline style, whatever its specificity — is now tested rather than asserted. A
person's accommodation beats an organisation's decoration, and the brand hue survives
exactly where the design said it should.

---

### G7R2-F01-TC05 — 375px, keyboard and focus

| # | Action | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | High contrast on, viewport 375, open the navigation drawer | the drawer renders in the high-contrast palette and the close control is reachable | `data-contrast="high"`; drawer rendered; background `rgb(255, 255, 255)` | PASS |
| 2 | Tab to the first control | the focus ring is clearly visible against the changed surface | focused `A`, outline `rgb(37, 99, 235)` at `3px` — 5.17:1 against white | PASS |
| 3 | Press Escape | the drawer closes and focus returns to the toggle | unchanged from before this feature | PASS |

**Evidence:** `step-01-drawer-high-contrast.png`, `step-02-focus-ring-visible.png`.
*Purpose of the second: an accessibility condition that is visual. A focus ring that had
become invisible against a changed background is exactly the regression this mode could
introduce, and it is the one thing here a written result could not settle.*

---

## What these results do not establish

- **They do not establish the contrast ratios.** Those are measured from computed values
  by `accessibility-qa`, in `testing/runs/2026-09-21-05/`, not read off an image.
- **They say nothing about `accessibility.fontScale` or `accessibility.reducedMotion`**,
  which remain surfaced and honoured by nothing.
- **They do not prove the override reaches a component that hardcodes a colour.** The
  tokens changed; a component bypassing the token layer would be unaffected and none was
  looked for exhaustively. The plan predicted that anything failing to change would be
  such a component; nothing on the surfaces exercised failed to change.
- **They were not executed by a person.** See the build context above.
