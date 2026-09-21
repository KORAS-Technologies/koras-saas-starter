# G7R2-F01 — technical design

| | |
|---|---|
| **Feature ID** | `G7R2-F01` |
| **Mode** | FAST |
| **Written** | before implementation |
| **Companion** | `ux-design.md` decides the marker, the palette and the cascade; this decides where the code goes and what proves it |

## The shape of the change

Two production files, both inside `profiles/product/template/packages/ui/`.

### 1. Read the setting where it already arrives

`AuthenticatedProductShell` (`packages/ui/src/shell/product-shell.tsx.hbs`) is a
`'use client'` component. The dashboard layout renders it **inside**
`<SettingsProvider>` (`apps/web/src/app/dashboard/layout.tsx.hbs:216-217`), which the
layout already populates once per request on the server from `effectiveSettings()`.

So the shell calls the existing hook:

```
const highContrast = useSettingValue('accessibility.highContrast', false)
```

and stamps its own root `<div>` (line 167) with `data-contrast={highContrast ? 'high' : undefined}`.

**Why this seam and not another.** Three alternatives were considered and rejected:

- **`BrandScope`'s div** (`packages/ui/src/brand/brand-scope.tsx.hbs:47`) is the visually
  natural root, but it is the provider's **parent** and a server component. Using it
  would mean threading a prop down from `apps/web`'s layout — an edit outside
  `packages/ui`, which would take the change out of FAST for no benefit.
- **`<html>` or `<body>`**, set by a script like the theme toggle does. That would put
  the marker outside the authenticated area, apply it to the marketing pages, and
  require a new inline script under a nonce-bearing CSP. Three new problems to solve a
  problem that does not exist.
- **A new context or a new fetch.** There is already exactly one settings load per
  request and one provider. A second would let two components disagree about the same
  value — the failure the provider's own documentation calls out.

**No new prop, no prop threading, no new fetch.** The value is already in the tree; one
component starts reading it.

### 2. Override the tokens where they are already declared

`packages/ui/src/styles/tokens.css` declares the palette as `--brand-*` custom
properties, six of them as `light-dark()` pairs, and declares the Tailwind theme
`@theme inline` so that every utility compiles to `var(--brand-*)` rather than to a
baked colour. Re-declaring those properties on an element re-skins that element and
everything under it, with no component change at all.

A single `[data-contrast="high"]` rule is added after the `:root` block, re-declaring
only the six pairs that already exist, each as a `light-dark()` pair so that the theme
toggle keeps working for exactly the users who most need it. The exact values and their
measured ratios are in `ux-design.md` section 2.

**This is the file's existing mechanism, not a second one.** Per-tenant branding
already re-declares the same properties on a nested element; high contrast does the
same thing one level further in. Nothing new is invented, and the file's own rule —
that a component writing `bg-blue-600` cannot be re-branded — is what makes the
override reach the whole subtree.

### 3. The cascade, which is the load-bearing part

The tenant brand is an **inline style on the parent**; the high-contrast rule is a
**declaration on the element itself**. A cascaded declaration on an element always beats
an inherited value, whatever the ancestor's specificity or importance — so high contrast
wins over a tenant brand **by construction**, with no `!important` and no ordering
dependency. `ux-design.md` section 3 has the full argument and the reason it *must* win:
an organisation's decoration may not defeat a person's accommodation.

## What proves it

| Claim | Proof | Why that proof and not another |
|---|---|---|
| The shell reads the setting and emits the marker | a Node assertion in `generators/create-koras-app/tests/product-shell.test.ts` over the generated file | `packages/ui` has no runner of its own; the generator's suites are how this package is asserted today |
| The override block exists, re-declares only existing properties, and uses `light-dark()` | a Node assertion in the same file | catches the two ways this is most likely to be got wrong later: a new custom property, or a flat colour that breaks dark mode |
| A surfaced setting is honoured | an assertion in `product-settings.test.ts` | that suite already asserts the *hidden* settings are unread; it has never asserted the converse, which is how this defect survived |
| It renders | a Playwright assertion at 1440 and 375 | a template-text assertion proves the rule was written, not that anything rendered |
| It is readable | `accessibility-qa` against **computed** colours | a screenshot cannot establish a contrast ratio |
| A tenant brand does not defeat it | a manual case on a branded tenant | the cascade argument is sound and untested until somebody looks |

## Guard discipline

`quality-gates.yaml` requires a new protective guard to be shown failing against a
deliberate counter-example before its passing run counts as evidence — because this
estate has shipped four guards that could not fail. The assertions added here are
protective (they exist so that a future edit cannot silently kill the marker or the
override), so each is mutated and required to fail before it is believed. The mutations
and their results are recorded in `testing/automated-test-results.md`.

## Rejected: doing more

`accessibility.fontScale` would reuse this exact seam and is a four-line addition. It is
**not** done here. A FAST change that quietly grows to cover its neighbours is the
scope creep the mode's containment requirement exists to refuse, and the second setting
deserves its own acceptance criteria — reflow, clipping and zoom interaction are not the
same question as contrast.

## Reversibility

The setting defaults to `false`, so the feature is dark until a user opts in. Reverting
is the two files; there is no data to unwind, no migration to reverse and no contract to
renegotiate.
