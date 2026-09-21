# Run 2026-09-21-05 - accessibility measurement

| | |
|---|---|
| **Gate** | `accessibility_pass`, owner `accessibility-qa` |
| **Commit under test** | `e677b54` |
| **Method** | Colours read from the browser with `getComputedStyle` during the manual pass, then the WCAG 2.2 relative-luminance formula applied to those values. Measured, not read off an image. |
| **Result** | **PASS.** Every changed pair clears WCAG 2.2 AA. |

## Colours as the browser resolved them

Captured in-page during the manual pass (`testing/manual/manual-test-results.md`):

| State | shell root background | h1 colour | sidebar border |
|---|---|---|---|
| stock, light | `rgb(248, 250, 252)` | `rgb(15, 23, 42)` | - |
| high contrast, light | `rgb(255, 255, 255)` | `rgb(0, 0, 0)` | `rgb(43, 43, 43)` |
| high contrast, dark | `rgb(0, 0, 0)` | `rgb(255, 255, 255)` | - |
| focus ring, high contrast | - | - | `rgb(37, 99, 235)` at `3px` |

## Ratios

| Pair | Ratio | AA threshold | Verdict |
|---|---:|---:|---|
| light: body text `#000000` on `#ffffff` | 21.00:1 | 4.5 | PASS |
| dark: body text `#ffffff` on `#000000` | 21.00:1 | 4.5 | PASS |
| light: border `#2b2b2b` on `#ffffff` | 14.16:1 | 3.0 | PASS |
| dark: border `#d4d4d4` on `#000000` | 14.17:1 | 3.0 | PASS |
| light: muted text `#404040` on `#ffffff` | 10.37:1 | 4.5 | PASS |
| dark: muted text `#b3b3b3` on `#000000` | 10.02:1 | 4.5 | PASS |
| focus ring `#2563eb` on high-contrast white | 5.17:1 | 3.0 | PASS |
| focus ring `#2563eb` on high-contrast black | 4.06:1 | 3.0 | PASS |
| baseline for comparison: stock `#0f172a` on `#f8fafc` | 17.06:1 | 4.5 | PASS |

Body text improves from 17.06:1 to 21.00:1, which is the ceiling.

## Keyboard and focus

Executed at 375: the drawer opens, Tab reaches its first control with a 3px outline in
the brand colour, Escape closes it and focus returns to the toggle. Unchanged from
before this feature, which is the claim - the mode changes the palette and not the
interaction.

## Watch item, recorded rather than fixed

**The focus ring is the weakest number in the set, at 4.06:1 on high-contrast black.**
It clears the 3:1 threshold for a user-interface component and it is deliberately left
alone: it draws from `--brand-primary`, which is the tenant's to set and which this
feature does not touch. A tenant choosing a pale primary would weaken it further, in
high contrast as everywhere else.

`design/ux-design.md` section 4 named this risk **before** the measurement existed, and
proposed keying the ring off `--brand-foreground` in high-contrast mode as a future
enhancement. That is out of this feature's containment and is not done here.

## What this does not establish

That every component honours the tokens. These are the pairs the changed tokens
produce; a component writing a literal colour would be unaffected by the override and
would keep whatever contrast it already had. Finding such a component is a separate
sweep and none was run.
