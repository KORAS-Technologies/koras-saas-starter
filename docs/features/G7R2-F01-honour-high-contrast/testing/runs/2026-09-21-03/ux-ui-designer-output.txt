# G7R2-F01 - UX design

| Field | Value |
|---|---|
| Feature | `accessibility.highContrast` (boolean, default `false`, `Scope.GLOBAL_ORG_USER`) |
| Surface today | Shown on `/dashboard/preferences`, read by nothing |
| This change | The signed-in shell reads the value and paints a high-contrast palette over the token layer |
| Marker | `data-contrast="high"` on the shell root; **attribute absent** when the setting is false |
| Marker site | `AuthenticatedProductShell` root `<div>` — `packages/ui/src/shell/product-shell.tsx.hbs:167` |
| Read site | `useSettingValue('accessibility.highContrast', false)` inside that component (state block `packages/ui/src/shell/product-shell.tsx.hbs:81-87`) |
| Override site | New `[data-contrast="high"]` rule in `packages/ui/src/styles/tokens.css`, after the `:root` block (i.e. after line 71) |
| Contrast target | **21:1** for text where achievable (pure black/white), never below **10:1**; borders **≥14:1**. All AAA-and-beyond, on purpose |
| Wins over tenant brand? | **Yes**, structurally — and it must |
| Blast radius | `packages/ui` only. No app, service, schema or contract changes |
| Mode | FAST, human-approved. Design document only; no code is written here |

---

## 1. The marker

**Decision: a `data-*` attribute, `data-contrast="high"`, emitted only when the setting is true. When the setting is false, no `data-contrast` attribute is emitted at all.**

On the shell root (`product-shell.tsx.hbs:167`), which today reads:

```tsx
<div className="flex min-h-screen flex-col bg-surface-muted">
```

the implementer adds one attribute, driven by the value the component already has in scope:

```tsx
const highContrast = useSettingValue('accessibility.highContrast', false)
...
<div
  className="flex min-h-screen flex-col bg-surface-muted"
  data-contrast={highContrast ? 'high' : undefined}
>
```

Returning `undefined` for the false case makes React omit the attribute entirely rather than render `data-contrast=""`.

**Attribute vs class.** Both an attribute selector `[data-contrast="high"]` and a class `.contrast-high` carry identical specificity `(0,1,0)`, so either would win the cascade contest described in §3. The attribute is chosen because this is a *state marker*, not a styling class:

- `className` on this element is already a bundle of layout/brand utilities (`flex min-h-screen flex-col bg-surface-muted`). A state flag does not belong mixed into that list, where a future Tailwind utility could collide with it or a `cn()` merge could drop it.
- `data-contrast` reads unambiguously as on/off state in DevTools and in the DOM, which is what a reviewer and a manual tester need to see.
- It keeps the token override a pure CSS concern (an attribute selector in `tokens.css`), matching how the rest of this file already works — nothing here is a Tailwind class-palette.

**Why emit nothing when false (rather than `data-contrast="normal"`).**

- *Absence is the literal truth.* High contrast off means "apply no override." The correct expression of "no behaviour" is no selector match, not a second value that a second rule must then neutralise.
- *It cannot be depended on as a hook.* If we emitted `data-contrast="normal"`, someone will eventually write `[data-contrast="normal"] { … }` and create a second, undocumented palette state to maintain. An absent attribute offers nothing to hang code on.
- *It composes cleanly with the tenant brand.* When the attribute is absent, the shell root declares none of the `--brand-*` overrides, so the tenant's inherited values (from the `BrandScope` parent, §3) pass through untouched. High contrast is purely additive: present → override, absent → the product behaves exactly as it does today.

---

## 2. The token overrides

The palette in `tokens.css` is expressed as `--brand-*` custom properties, six of them written as `light-dark()` pairs (`tokens.css:49-54`) plus three brand colours (`tokens.css:37-39`). The Tailwind theme is declared `@theme inline` (`tokens.css:73-92`), so every utility — including `bg-surface-muted` on the shell root — resolves *through* these properties at runtime. Re-declaring a property on the shell root therefore re-skins the shell root and everything under it, touching no component.

We re-declare **only the six surface/text pairs that already exist**. No new custom property is invented. No class-based palette is introduced.

**Exact block** (to be inserted after the `:root` block, after `tokens.css:71`):

```css
/*
 * High-contrast mode. The signed-in shell marks its own root with
 * data-contrast="high" when the user's accessibility.highContrast setting is on;
 * this re-declares the readability-critical brand tokens on that element, so the
 * whole authenticated subtree inherits a maximal-contrast palette. Only tokens
 * that already exist in :root are redeclared; --brand-primary/secondary/accent,
 * the focus ring, shadows and radius are deliberately left alone (see design §4).
 */
[data-contrast="high"] {
  --brand-background:       light-dark(#ffffff, #000000);
  --brand-foreground:       light-dark(#000000, #ffffff);
  --brand-surface:          light-dark(#ffffff, #000000);
  --brand-surface-muted:    light-dark(#ffffff, #000000);
  --brand-border:           light-dark(#2b2b2b, #d4d4d4);
  --brand-muted-foreground: light-dark(#404040, #b3b3b3);
}
```

Because each value is itself a `light-dark()` pair, the subtree keeps *both* appearances — the OS/theme switch still chooses light or dark, exactly as the stock tokens do (`tokens.css:34`, and the rationale at `brand-style.ts.hbs:33-35`). High contrast does not pin an appearance; it maximises contrast *within* whichever appearance is active.

### Target and why

The whole point of the feature is *high* contrast, so we aim far past AA. Text lands on **21:1** wherever a surface and the foreground meet (pure black on pure white, pure white on pure black — AAA is 7:1, so this is 3× past it). Secondary text sits at **~10:1**, borders at **~14:1**. Hierarchy that the stock palette carries with mid-grey tints is instead carried by weight, size and border in this mode — a deliberate trade, because low-contrast grey is exactly what this mode exists to remove.

### Computed ratios, against the surface each token is actually used with

Relative luminance uses the WCAG sRGB formula. For a channel value `c` (0–255): `cs = c/255`; `Lc = cs/12.92` if `cs ≤ 0.03928`, else `Lc = ((cs+0.055)/1.055)^2.4`. Then `L = 0.2126·R + 0.7152·G + 0.0722·B`. Contrast `= (L_light+0.05)/(L_dark+0.05)`.

**Foreground vs background — arithmetic, both modes (the required pair):**

*Light:* foreground `#000000` → every channel `0 ≤ 0.03928` → `Lc = 0/12.92 = 0` → `L = 0`. Background `#ffffff` → `cs = 1.0`, `Lc = ((1.0+0.055)/1.055)^2.4 = (1.0)^2.4 = 1.0` → `L = 1.0`. Contrast `= (1.0 + 0.05)/(0 + 0.05) = 1.05/0.05 = ` **21.00:1**.

*Dark:* foreground `#ffffff` → `L = 1.0`; background `#000000` → `L = 0`. Contrast `= (1.0 + 0.05)/(0 + 0.05) = ` **21.00:1**.

Threshold to clear: 4.5:1 (normal text). Cleared by a factor of ~4.7.

**Border vs background/surface — arithmetic (the interesting non-text pair):**

*Light border `#2b2b2b`:* `cs = 43/255 = 0.16863`; `Lc = ((0.16863+0.055)/1.055)^2.4 = (0.21197)^2.4 = 0.02417`; grey so `L = 0.02417`. Against `#ffffff` (`L=1.0`): `(1.0+0.05)/(0.02417+0.05) = 1.05/0.07417 = ` **14.16:1**.

*Dark border `#d4d4d4`:* `cs = 212/255 = 0.83137`; `Lc = ((0.83137+0.055)/1.055)^2.4 = (0.84016)^2.4 = 0.6583`; `L = 0.6583`. Against `#000000`: `(0.6583+0.05)/(0+0.05) = 0.7083/0.05 = ` **14.17:1**.

Threshold to clear: 3:1 (UI components / borders). Cleared by ~4.7×.

**Full table:**

| Token | Light value | Dark value | Used against | Light ratio | Dark ratio | WCAG 2.2 AA threshold |
|---|---|---|---|---|---|---|
| `--brand-foreground` | `#000000` | `#ffffff` | background / surface / surface-muted | **21.00:1** | **21.00:1** | 4.5:1 (normal text) |
| `--brand-muted-foreground` | `#404040` | `#b3b3b3` | background / surface (#fff / #000) | **10.37:1** | **10.00:1** | 4.5:1 (normal text) |
| `--brand-border` | `#2b2b2b` | `#d4d4d4` | background / surface (#fff / #000) | **14.16:1** | **14.17:1** | 3:1 (UI / borders) |
| `--brand-background` | `#ffffff` | `#000000` | (canvas — target of the above) | — | — | — |
| `--brand-surface` | `#ffffff` | `#000000` | (card surface — target of the above) | — | — | — |
| `--brand-surface-muted` | `#ffffff` | `#000000` | (shell root bg — target of the above) | — | — | — |

`--brand-surface`, `--brand-surface-muted` and `--brand-background` are set equal so that text on any of them is the full 21:1. With surfaces no longer distinguished by tint, panels and cards are distinguished by the strong border (`--brand-border`, ~14:1) — which is why the border is redeclared and made heavy rather than left at the stock hairline.

---

## 3. Interaction with per-tenant branding — the load-bearing judgement

**Layout of the cascade.** `BrandScope` (`brand-scope.tsx.hbs:47`) wraps the authenticated area in `<div style={brandStyle(brand)}>`, and `brandStyle()` (`brand-style.ts.hbs:20-54`) sets the same `--brand-*` custom properties as an **inline style** on that div. That div is the **parent** of the shell root. The shell root (`product-shell.tsx.hbs:167`) is the element that now carries `data-contrast="high"` and matches our new **CSS rule**.

**What the cascade does, precisely.** For a custom property on a given element, the CSS cascade first looks for a declaration that *applies to that element*. An **inherited** value is used **only as a fallback, when the element itself has no cascaded declaration** for that property (CSS Cascade, "inherited values" / "defaulting"). On the shell root:

- The tenant's inline style lives on the **parent**, so for the shell root it is only an *inherited* value — the lowest-priority source.
- Our `[data-contrast="high"]` rule declares `--brand-foreground` (and the other five) **directly on the shell root**. That is a cascaded declaration on the element itself.
- A cascaded declaration on the element **always beats inheritance.** So on the shell root, `--brand-foreground` = `#000000`/`#fff`, not the tenant's colour — and that overridden value then inherits down through the entire authenticated subtree.

**Therefore high contrast wins over the tenant brand.** And it wins *robustly*: the specificity of the tenant's inline style is irrelevant, because inline-vs-rule specificity only decides contests **on the same element** — here the two declarations are on different elements, and inheritance loses to any own-declaration regardless of specificity. Even `!important` on the parent's inline style would not change this: importance orders declarations *on the same element*; it does not promote an inherited value above an element's own declaration. No `!important` is needed in our rule, and none should be added.

The tenant's other properties that we do **not** redeclare — `--brand-primary`, `--brand-secondary`, `--brand-accent` — are not shadowed on the shell root, so they continue to inherit past it: the tenant's brand hue still tints buttons and the focus ring, while text, surfaces and borders go maximal-contrast.

**Should it win? Yes — unconditionally, and this is the most important line in the document.** `accessibility.highContrast` is a `GLOBAL_ORG_USER`-scoped setting the *user* set for *themselves*. A tenant brand is content the *organisation* chose for its look. A palette a customer picked for style must never be able to defeat an accessibility accommodation the end user turned on to be able to read the product at all. A design in which a tenant brand could suppress a user's high-contrast setting would be a defect, not a trade-off. The containment here produces the correct precedence *by construction* — the accommodation is declared on the descendant, the brand on the ancestor — so it cannot be got wrong by a future brand colour choice. A reviewer should confirm this precedence with the manual test in §6.4, on a tenant with an aggressive brand palette.

---

## 4. What must not change, and why

- **`--brand-primary`, `--brand-secondary`, `--brand-accent` (`tokens.css:37-39`) — left alone.** These are brand identity, not readability tokens, and they are the tenant's to set. High contrast is about legibility of text, surfaces and structure, not about repainting the brand. Redeclaring them would erase the tenant's mark for no accessibility gain and would exceed the agreed containment.
- **The `:focus-visible` outline (`tokens.css:110-114`) — left alone.** It is defined today as `outline: 3px solid var(--brand-primary); outline-offset: 2px; border-radius: 2px`. It stays. The stock primary `#2563eb` on white computes to **5.17:1**, already past the 3:1 UI threshold, and keeping the brand-coloured ring preserves the product's "visible focus everywhere, on the brand colour, never removed" contract. *Known limitation to record, not fix here:* a tenant that sets a very pale `--brand-primary` would produce a weaker ring even in high-contrast mode, because we deliberately do not touch `--brand-primary`. Strengthening the ring in high contrast (e.g. keying it off `--brand-foreground`) is a reasonable future enhancement but is out of this feature's containment; flag it for the accessibility reviewer as a watch item, not a blocker.
- **Shadows `--shadow-card` / `--shadow-lifted` (`tokens.css:90-91`) — left alone.** Elevation is communicated by borders in this mode; the shadows are harmless and re-tinting them buys nothing.
- **`--brand-radius` (`tokens.css:61`) and the font tokens (`tokens.css:57-60`) — left alone.** Shape and typeface are not contrast concerns.
- **`.brand-grid`, `.skip-link`, anchor scroll-margin, reduced-motion block — left alone.** None is authenticated-shell palette; the skip link already draws from `--brand-surface`/`--brand-foreground`, so it inherits the improvement for free.

---

## 5. Failure modes a reviewer must look for

1. **Hardcoded colours that bypass the tokens.** Any component under `packages/ui` that writes a literal (`bg-blue-600`, `text-slate-900`, `#…`, `rgb(…)`) instead of a semantic token (`bg-surface`, `text-ink`, `border-line`, …) will *not* respond to the override and will float at its own fixed contrast. Grep the shell/nav/header subtree for Tailwind palette classes and raw hex/rgb; each hit is a component that ignores high contrast. This is the single most likely defect.
2. **The marketing/public app importing the same stylesheet.** `tokens.css` is shared, so the `[data-contrast="high"]` rule ships to the marketing app too. It is **inert there** — nothing outside the authenticated area emits `data-contrast` (the marker lives only on the shell root, and public pages are outside both `BrandScope` and `SettingsProvider`, per `brand-scope.tsx.hbs:20-27` and `provider.tsx:8-13`). Reviewer must confirm no public/marketing surface sets `data-contrast` and that no public page reads `accessibility.highContrast`; if either is true, the rule would fire outside its intended scope.
3. **Print styles.** No `@media print` rule exists in `tokens.css` today, so nothing conflicts. Note the honest edge: in dark + high-contrast, `--brand-background`/surfaces are `#000000`; browsers drop backgrounds when printing by default, so a print would render black text on the paper's white without the black fill — acceptable, but the reviewer should confirm no one later adds `print-color-adjust: exact` that would dump a full black page.
4. **`@media (forced-colors: active)` (Windows High Contrast / forced-colors).** When the OS forces colours, the user agent replaces author colours with the system palette and our custom-property overrides are moot — which is **correct**, not a bug: the OS accommodation outranks ours and the two must not fight. The reviewer must confirm we do **not** introduce `forced-color-adjust: none` anywhere (which would override the user's OS setting), and that the preference copy does not claim to control OS forced-colors. Our toggle is an in-app preference that coexists with, and yields to, forced-colors mode.

---

## 6. Manual test intent — what a person must actually see

To be believable, a tester must *see* these, at **1440px** and **375px** width. (Note on timing: the value is read from `SettingsProvider`, which the dashboard layout resolves **once per request on the server** — `provider.tsx:8-13`. So after toggling the preference, the shell reflects it on the next server render of the dashboard — a navigation or reload — not necessarily the instant the toggle flips, unless the preferences page refreshes. Test the *persisted* state, and record exactly when the flip appears.)

1. **The flip.** Enable high contrast on `/dashboard/preferences`, then land on any dashboard page: the shell root (`bg-surface-muted`) and page canvas become pure white with black body text (light) — a full-viewport change, not a patch. Disable it: the page returns exactly to its prior brand appearance, with **no `data-contrast` attribute** in the DOM.
2. **Structure via borders.** With surfaces now uniform white, the sidebar (`border-r border-line`, `product-shell.tsx.hbs:190`) and any cards read as crisply bordered boxes — the heavy `--brand-border` is visibly present, not a faint hairline.
3. **Dark appearance.** Switch OS/theme to dark: high contrast becomes pure white on pure black, still maximal — confirming the `light-dark()` pairs, not a single pinned appearance.
4. **Accessibility beats brand (the decisive test).** On a tenant with a strong, distinctive brand palette, enable high contrast: text, canvas and surfaces must go black/white — **not** the tenant's colours — while the brand hue may still tint the focus ring/buttons. If the tenant's colours survive on text or background, §3 has failed and it is a CRITICAL defect.
5. **Mobile drawer and focus, at 375px.** Open the small-screen navigation drawer (`product-shell.tsx.hbs:227-260`): its `bg-surface` panel is white/black with a visible border and a visibly focus-ringed close button. Tab through interactive controls and confirm the focus ring is clearly visible against the high-contrast surfaces, and that keyboard operation (Escape to close, focus return to the toggle) is unchanged.
