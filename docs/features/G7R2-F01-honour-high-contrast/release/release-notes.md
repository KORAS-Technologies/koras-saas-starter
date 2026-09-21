# G7R2-F01 — release notes

| | |
|---|---|
| **Feature** | Honour the surfaced `accessibility.highContrast` setting |
| **Commit** | `e677b54` on `feature/G7R2-F01-honour-high-contrast` |
| **Mode** | FAST |
| **Shipped** | 2026-09-21 |
| **Applies to** | every generated product; the setting is foundation, not a capability |

## What changed for a customer

The **High contrast** switch on `/dashboard/preferences` now does something. Turn it on
and the signed-in product renders in a maximal-contrast palette — black on white in the
light appearance, white on black in the dark one — across the header, the sidebar, the
page and every card. Turn it off and the product returns to exactly what it was.

It is off by default, and it is a personal preference: a colleague's screen is unaffected.

**An organisation's branding cannot override it.** A tenant with a strong brand palette
still gets the high-contrast palette for text, canvas and surfaces when a person turns
the setting on; the brand colour survives where it does no harm, on primary actions and
the focus ring.

## What changed for an operator

Nothing. No configuration, no migration, no new service, no new dependency, no new
environment variable.

## What changed in the code

Two production files, both in `packages/ui`:

- the shell reads `accessibility.highContrast` through `useSettingValue` — the hook the
  shared data table already uses — and stamps `data-contrast="high"` on its own root. When
  the setting is off, or when the settings API could not be reached, **no attribute is
  emitted at all** and the DOM is what it was before.
- `tokens.css` gains one `[data-contrast="high"]` rule re-declaring the six readability
  tokens that already exist, each as a `light-dark()` pair so the appearance toggle keeps
  working for the people who most need it.

No new custom property, no class-based palette, no `!important`, no second mechanism.

## Why it was worth doing

The setting has been offered to customers since the settings framework shipped on
2026-09-19 — declared, translated into three languages, drawn on a page, stored,
resolved through member → organisation → global → default, and returned by the API. Nothing
read it. A customer could turn on an accessibility accommodation and the product would
look identical.

That is the PLAT-DEF-001 class, and it is the exact failure `surfaced=False` was
introduced four days earlier to prevent: a control that changes nothing is worse than one
that is not offered.

## What is still wrong, and named rather than left

`accessibility.reducedMotion` and `accessibility.fontScale` are in the same state today:
surfaced, translated, drawn, and honoured by nothing. This feature closes one third of
the defect. The other two are recorded in `docs/platform/gap-defect-register.md` and a
test assertion records them as still dead, so honouring one later forces the record to be
updated in the same commit.

Two further limitations, stated plainly:

- **The focus ring is the weakest pair in the palette**, at 4.06:1 against high-contrast
  black. It clears the 3:1 threshold for a user-interface component, and it is left alone
  deliberately because it draws from the tenant's own `--brand-primary`. A tenant choosing
  a pale primary weakens it — in high contrast as everywhere else. Keying the ring off
  `--brand-foreground` in this mode is a sensible future change and is outside this one.
- **A component that hardcodes a colour instead of using a semantic token will not
  respond to the override.** None was found on the surfaces exercised; no exhaustive
  sweep was run.

## How it was verified

| | |
|---|---|
| Automated | 2,191 Node assertions in the generator suites, 400 documentation checks, 120 CLI, 21 e2e-config, 7 Python. Exit 0 on the frozen commit `e677b54`. Re-established after the post-audit corrections at `dc4a946`, where the documentation suite is 409 checks because this feature's own evidence is in it. |
| New assertions | Seven. **Six** were shown to **fail** against a deliberate counter-example before their passing runs were believed. The seventh — the guard recording that the two sibling settings are still dead — was **not** mutation-tested, and the independent review named its blind spot: it inspects only the shell file, so a sibling honoured in `tokens.css` would leave it green. Recorded rather than claimed. |
| Browser | 147 passed against a real Postgres, a real identity provider and this product's own API — including a round-trip case that turns the setting on through the control a person uses and asserts the computed background actually changed. |
| Manual | 5 cases, 5 executed, 5 PASS, 0 FAIL, 0 BLOCKED, 9 genuine screenshots. |
| Accessibility | Measured from computed colours: 21.00:1 body text in both appearances, 14.16 and 14.17:1 borders, 10.37 and 10.02:1 muted text. |
| Independent review | PASS. 0 CRITICAL, 0 HIGH, 2 LOW recorded and not fixed. |

## Telemetry

See `telemetry-summary.md`, derived from the event log after the last applicable event.

## Downstream

`koras-e2e-shop` and `docoris` do **not** have this. A generated project has no upstream
and the factory pushes to nothing; both are kept level by a hand-carried sync, which is a
separate decision and was not part of this work.
