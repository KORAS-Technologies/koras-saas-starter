# G7R2-F01 — user story

| | |
|---|---|
| **Feature ID** | `G7R2-F01` |
| **Status** | Approved 2026-09-21 by the repository owner (`start_planner_recommended_feature`) |
| **Mode** | FAST |
| **Written** | before implementation, per `documentation-policy.yaml` `timing.before_implementation` |

## Story

**As** a signed-in user of a KORAS product who has turned on the high-contrast
preference, **I want** the product to actually render in high contrast, **so that** I
can read it.

## The defect this closes

`accessibility.highContrast` has been offered to customers since the settings
framework shipped on 2026-09-19. It is declared in the catalogue
(`settings_catalogue/standard.py:514`) with `surfaced` at its default `True`, a
`TOGGLE` control and `Scope.GLOBAL_ORG_USER`; it is a known key
(`packages/ui/src/settings/types.ts:97`); it is translated into English, German and
Spanish; and it is drawn on `/dashboard/preferences`.

No code reads it. The toggle moves, the value is stored, resolved through the
member → organisation → global → default chain and returned by
`GET /settings/effective` — and the product looks exactly the same.

That is the PLAT-DEF-001 class, and it is the specific failure `surfaced=False` was
introduced on 2026-09-19 to prevent: *a control that changes nothing is worse than one
that is not offered.* Two sibling settings, `accessibility.reducedMotion` and
`accessibility.fontScale`, are in the same state and are **not** fixed here; they are
named in the register row this feature opens, so the remaining two-thirds of the defect
is recorded rather than left to be rediscovered.

## Acceptance criteria

Each is testable, and each names how it is verified.

| # | Criterion | Verified by |
|---|---|---|
| AC1 | When the effective value of `accessibility.highContrast` is `true`, the authenticated product shell's root element carries `data-contrast="high"`. | unit (template assertion), e2e (DOM), manual (DevTools) |
| AC2 | When it is `false` — including when the settings API could not be reached and the provider holds `null` — **no** `data-contrast` attribute is emitted, and the rendered DOM is unchanged from before this feature. | unit, e2e, manual |
| AC3 | With the marker present, the readability tokens `--brand-background`, `--brand-foreground`, `--brand-surface`, `--brand-surface-muted`, `--brand-border` and `--brand-muted-foreground` resolve to the high-contrast palette across the whole signed-in subtree, in both the light and the dark appearance. | unit (CSS assertion), manual at both appearances |
| AC4 | A per-tenant brand does **not** defeat the user's high-contrast setting. Text, canvas and surfaces go to the high-contrast palette even on a tenant with a strong brand. | manual (decisive case, TC04) |
| AC5 | Every changed foreground/background pair meets WCAG 2.2 AA — 4.5:1 for normal text, 3:1 for borders and UI components — measured against computed values, not asserted. | `accessibility-qa`, against computed colours |
| AC6 | No new custom property is invented, no class-based palette is introduced, and `--brand-primary`, `--brand-secondary`, `--brand-accent`, the focus ring, the shadows, the radius and the fonts are unchanged. | independent code review |
| AC7 | Keyboard operation of the shell — skip link, sidebar, mobile drawer, Escape-to-close, focus return — is unchanged, and focus remains visible against the high-contrast surfaces. | `accessibility-qa`, manual at 375px |
| AC8 | Nothing outside `profiles/product/template/packages/ui/` changes in production code. | independent code review, `git diff` |

## Out of scope, stated so that it cannot drift in

`accessibility.fontScale`; `accessibility.reducedMotion`; any change to the settings
catalogue, `types.ts`, `packages/i18n` or the preferences page; `apps/**`;
`services/**`; `profiles/_shared/**`; any migration; the `forced-colors` OS mode, which
correctly outranks this preference and is deliberately not fought; GR-248, GR-250,
PLAT-DEF-013, E18-F01, E18-F02; `koras-control-plane`; `docoris`.

## Non-goals worth naming

This does not make the product *conform* to WCAG 2.2 AAA, and it does not claim to.
It makes one offered control do what it says. A component that hardcodes a colour
instead of using a semantic token will not respond to it — finding such a component is
a result of this work, not a failure of it, and any found are recorded rather than
silently fixed inside a FAST change.
