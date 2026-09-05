# Product Frontend

What a generated KORAS product looks like out of the box, how a product changes
it, and which parts must not be changed without an architecture review.

This describes the **`product` profile only**. The Control Plane keeps its own
minimal admin and portal shells; `packages/ui` in that profile is still the
two-line stub, deliberately.

---

## What a generated product receives

```
/                 public homepage      hero, values, features, outcomes,
                                       process, preview, security, CTA
/login            sign-in              two-panel, brand panel + auth card
/signin           alias of /login      redirect, forwards ?next
/signup           get started          self-serve form, request access,
                                       or invitation only
/signup/verify    confirm an address   three outcomes, unchanged wording
/dashboard        signed-in landing    behind the session gate, inside the shell
/dashboard/settings       product settings   general; requires settings.read
/dashboard/settings/team  Team & Access      product roles; requires team.read
```

Everything from `/dashboard` down renders inside the **authenticated product
shell** — header, sidebar, profile menu, workspace badge — and its navigation is
resolved from a registry rather than written into a component. That half of the
frontend has its own document: `docs/PRODUCT_APP_SHELL.md`, which is
authoritative for the navigation registry, the permission and entitlement model,
product settings and the route gate. This document stays authoritative for the
public surface and for the design tokens both surfaces share.

`apps/marketing`, when generated, serves the same homepage from the same
components. It is a separate deployment with no session.

Nothing above needs an image, a font download, an icon library or a CMS. A
freshly generated product is publishable as it stands, and improves when
somebody who knows the product edits **one file**.

---

## The one configuration file

```
packages/branding/src/index.ts        <- everything the frontend says and shows
```

There is no second product-metadata source. `productConfig` carries three
sections:

| Section     | What it holds                                                    |
|-------------|------------------------------------------------------------------|
| `product`   | name, slug, tagline, description, contact address, origins        |
| `brand`     | colours light and dark, radius, logos, favicon, fonts, social     |
| `marketing` | navigation, every homepage section's copy, footer, access mode    |

`name` and `slug` are written by the generator from the project name. Everything
else is yours.

### Architecture

```
packages/branding      configuration and types. No React, no JSX.
        |
packages/ui            the design system: primitives, brand, marketing, auth
        |
apps/web  apps/marketing
```

`packages/ui` imports `packages/branding`, never the reverse — which is why
`IconName` is a union of names declared in the configuration and the drawings
live in the UI package. Applications import from `@<slug>/ui` and never from a
path inside it.

`packages/ui` ships **TypeScript sources**, not built output: `main` points at
`src/index.ts` and each application lists the package in `transpilePackages`. A
`tsc` build would have to decide, once, whether a component is a client
component; shipping sources lets each application decide.

---

## Design tokens

Two layers, in `packages/ui/src/styles/tokens.css`:

```css
:root         { --brand-primary: #2563eb; ... }              /* defaults */
@theme inline { --color-brand: var(--brand-primary); ... }   /* Tailwind */
```

`inline` is what makes per-product and per-customer branding possible. Without
it Tailwind copies the value into every utility at build time and a colour
changed at runtime changes nothing. With it, `bg-brand` compiles to
`background-color: var(--brand-primary)` — so setting that property re-skins
everything below it.

`brandStyle(brand)` turns the configured tokens into those properties, and each
root layout applies it once to `<body>`.

**Never write a colour into a component.** `bg-blue-600` is a colour that cannot
be re-branded; a test in the starter fails on any hex literal in `packages/ui`
outside the one documented exception.

The token names components may use:

| Utility                         | Token                   |
|---------------------------------|-------------------------|
| `bg-brand` `text-brand`         | `--brand-primary`       |
| `bg-brand-ink`                  | `--brand-secondary`     |
| `text-brand-accent`             | `--brand-accent`        |
| `bg-surface` `bg-surface-muted` | surfaces                |
| `text-ink` `text-ink-muted`     | body and secondary text |
| `border-line`                   | hairline borders        |
| `rounded-brand`                 | `--brand-radius`        |
| `font-sans` `font-display`      | the two stacks          |
| `shadow-card` `shadow-lifted`   | the two elevations      |

### Changing a product's colours

```ts
brand: mergeBranding(defaultBranding, {
  primaryColor: '#047857',
  secondaryColor: '#052e2b',
  accentColor: '#b45309',
  radius: '0.25rem',
}),
```

That is the whole change. The header, hero, cards, buttons, focus rings, sign-in
panel and footer all follow.

### Fonts

System stacks by default, and not for want of ambition: the application's
Content-Security-Policy sets `font-src 'self'`, so a webfont must be
self-hosted, and `next/font` fetches at build time — which turns every build
into a network call. To use a real face, self-host it, add an `@font-face` rule,
and point `brand.fontFamily` / `brand.displayFontFamily` at it.

---

## The logo

One component, `<ProductLogo />`. Resolution order:

1. a customer's logo, when a `tenant` is passed (signed-in surfaces only)
2. `brand.logoDarkUrl` on a dark surface, when the product has supplied one
3. `brand.logoUrl`
4. the built-in mark

**Step 4 is a finished state, not a placeholder to be embarrassed about.** It
draws a neutral geometric mark in the product's own primary colour beside the
product's own name. It is drawn rather than fetched, so it needs no asset, makes
no request, and cannot render broken.

### Why there is no Koras logo file

Koras Technologies has no logo asset. Its identity in `korastech-enterprise` is
a **wordmark**: the name set in the display face with the second word in the
brand colour. `KorasWordmark` reproduces that treatment in code rather than
importing a file, which is also why a generated product carries no dependency of
any kind on that repository. It appears in exactly one place — the footer
platform credit — and `marketing.showPlatformCredit: false` removes it.

### Supplying a product logo

Put the files in `apps/web/public/brand/` (and `apps/marketing/public/brand/`,
if that application is generated — they are separate deployments and do not
share a public directory), then:

```ts
brand: mergeBranding(defaultBranding, {
  logoUrl: '/brand/logo.svg',
  logoDarkUrl: '/brand/logo-dark.svg',
  faviconUrl: '/brand/icon.svg',
}),
```

`brand/` and `icon.svg` are excluded from the middleware matcher. Without that
exclusion an anonymous browser asking for the logo is answered with a redirect
to `/login`, and the public homepage shows a broken image.

---

## Customer branding

A KORAS product is multi-tenant, and `customer_branding` is a declared
capability of the profile. Tenant branding is applied **through design tokens,
never by forking components per tenant**.

```
Control Plane portal branding          tenant_settings.branding (jsonb, RLS-scoped)
        |                                        |
parsePlatformBranding()                parseTenantBranding()      each decides what is safe to render
        \                                      /
             mergeTenantBranding()             the platform wins where both speak
                        |
            <BrandScope tenant={...}>          re-declares the CSS custom properties
                        |
            every component below it, unchanged
```

`apps/web/src/app/dashboard/layout.tsx` wraps the whole signed-in area. Any
route added beside `dashboard/page.tsx` inherits the customer's palette with no
plumbing. Colours cascade; an image cannot, so `ProductLogo` takes the
customer's mark explicitly.

Since the authenticated shell renders inside that scope, the header, the
sidebar, the active navigation state and the profile menu are all the customer's
colours without a single shell component knowing a tenant exists. That is the
same mechanism doing more work, not a second one.

The public pages are deliberately **outside** the scope. `/`, `/login` and
`/signup` belong to the product and are served to people who have no tenant.

### Light and dark

Every surface is a pair. `brandStyle` emits `light-dark(light, dark)` for the
six semantic colours — background, foreground, surface, muted surface, border,
muted foreground — and the browser resolves them from `color-scheme`. The three
brand colours are **not** duplicated: a customer's brand colour is their brand
colour in both appearances, and a second one invites a pair whose contrast
nobody checks.

That choice of mechanism is what keeps the feature small. The switch sets one
property on `<html>` and the whole product repaints, including a customer's own
tokens under `BrandScope` — because each of those is a pair too. Nothing has a
class to toggle, no component knows an appearance exists, and the controls the
product does not draw (form fields, scrollbars, the overscroll canvas) follow
`color-scheme` on their own, which is exactly what gives a hand-rolled dark mode
away.

The control has three positions, and the third is the default: **System**. A
two-state toggle has to guess on first load and guesses wrong for everybody
whose machine is already set the other way.

A small script in the root layout applies a stored choice before the first
paint, carrying the request nonce because the policy is nonce-based. Without it
a reader who chose dark gets a light flash on every fresh document — the one bug
every dark mode ships with, and the reason the browser test navigates to a
second page rather than only clicking the control.

The dark values are chosen and checked rather than derived: `#e2e8f0` on
`#0b1220` is 15.1:1 and the muted pair is 7.4:1. Inverting the light palette
produces muddy greys and destroys ratios somebody picked deliberately — it looks
automatic because it is.

### What a customer may set

`TENANT_OVERRIDABLE` is a short list on purpose: the three brand colours, the
muted surface, the border, and the two logos — plus a white-label `name` and a
**corner style**. The semantic text colours and the font stacks are **not** on
it, because a customer who picks an unreadable pair of them breaks the product
for their own staff and calls it a bug.

The corner style is a choice of two names, `flat` or `rounded`, and not a
length. It was a length until 2026-09-01, guarded by a regular expression that
had to be right about `9999vmax; }`. A customer choosing a *look* is both the
kinder question and the smaller attack surface: two names cannot be malformed,
so the guard is the type rather than a pattern. `CORNER_RADIUS` is where a look
becomes a length, and `brandingFor` applies it after the merge — nothing
downstream of that knows the choice existed. The product still sets any length
it likes in `productConfig.brand.radius`; this is deliberately coarser than what
the product author controls.

The tenant is read from the session cookie's organization, never from a URL or a
header.

### Why the parser exists

`tenant_settings.branding` is customer-controlled data that ends up as CSS
custom property values in a style attribute. A custom property value is not
escaped the way text content is. A tenant storing

```
red; } html { display: none } :root { --x: 1
```

as `primaryColor` would be writing CSS into every page their staff load.

`parseTenantBranding` accepts hex colours only, one of two names for the corner
style, and same-origin absolute paths only for images — no `data:` (an SVG data URL is a
document with script in it), no `//host` (a protocol-relative URL that begins
with a slash), no remote origins (a logo fetched from somewhere a tenant
controls is a beacon on every page). Unknown keys are dropped, and one bad value
costs one token rather than the whole brand.

`packages/branding/src/branding.test.ts` is that argument, in eighteen tests that
run as part of the generated project's own `pnpm test`.

### Where it is read from

Two places, since 2026-09-04, and they are different documents.

**The Control Plane's portal** is where a customer actually edits their
branding: the portal has the form, and the platform stores what they save. A
product reads it back from
`GET /api/portal/v1/products/{product_code}/branding` — the customer's own
surface, with the customer's own token, exactly as `tenantEntitlements` reads
their plan. The product code is in the path and the organization is not, so a
customer can only ever read their own branding; the platform's project is
already in the token's audience from sign-in (F17). No machine credential is
held for this and none is needed. The platform also offers a machine-only
tenant endpoint for the same values (its contract §6a), and a product does not
call it: a product holds no machine identity at runtime, by the argument that
keeps deploy-time registration off (F2b), and that route is unscoped across
products until the platform's R-104 closes.

Until this read existed, branding had exactly two readers — platform staff and
the customer's own portal — so a customer could set their colours, be told the
product would use them, and have nothing ever do so.

**This product's own column** is `tenant_settings.branding`, for a product that
offers its own branding surface. Nothing writes it today.

The portal answer speaks the platform's names — `primary_color`,
`company_name`, `corner_style` — and the column speaks this package's, so each
has its own parser and each ignores the other's spelling. Fed to the wrong
parser, a response yields nothing rather than something wrong, and the tests
assert both directions: a rename on either side is otherwise a silent no-op in
which the customer simply appears to have set nothing. `mergeTenantBranding`
layers the platform's answer over the column's, because the platform's is the
one the customer can see and change.

**The platform's logos are not rendered.** The portal stores them as `https`
URLs on the platform's storage, and this product's Content-Security-Policy is
`img-src 'self'`; a remote logo would be a broken image in every header. Until
a product serves the platform's assets itself, a logo set in the portal is
dropped by the parser, deliberately and testably, rather than left to the
browser to refuse. FOLLOW_UPS F19 holds the decision.

### How the column is read

`GET /api/v1/tenant/settings` on `services/api`, added 2026-09-01 and the first
route in this API a browser reaches. It answers with the tenant's name, its
slug, its stored branding and its feature switches — one row, one call, because
the shell paints itself from the branding and resolves its navigation from the
features on the same page load, and two endpoints could disagree about which
version of that row a page was rendered from.

```
apps/web/src/lib/tenant-settings.ts    the read, cached per render
        |
tenant-branding.ts     parseTenantBranding   -> mergeTenantBranding -> BrandScope
                       (with the platform read beside it, cached the same way)
tenant-features.ts     parseTenantFeatures   -> resolveNavigation
        |
the organisation's name                      -> the workspace badge
```

`tenant-settings.ts` wraps the call in React's `cache`, so the three readers
stay separate functions with separate reasons while the API sees one request per
render. Without it the shell would make three identical authenticated calls per
navigation.

**There is no tenant identifier anywhere in that path.** The route takes no
parameter for one; `require_tenant` resolves the tenant from a token the API
verified against ZITADEL, and row-level security scopes the read to it. A client
that could name a tenant would be a client somebody could point at another one.

### What resolving a tenant needed first

Worth knowing, because it is the reason this route did not exist for so long.

Every policy in `00002_rls_policies.sql` is written as
`<column> = public.current_tenant_id()`, and that setting is a tenant's primary
key. A request from a customer's browser has no such thing: a verified token
names a ZITADEL *organization*, and the mapping from organization to tenant row
lives in the very table the policies protect. So the first read of any customer
request was the one read no policy admitted — and `resolve_tenant` papered over
it by fabricating a context from the organization id, which would have tried to
cast a numeric organization id to a `uuid` the moment any route used it.

`00004_tenant_settings_read.sql` gives the policies a second key the request
genuinely has. `public.current_organization_id()` reads a transaction-local
setting, and one permissive select policy on `tenants` admits the single row
whose `zitadel_org_id` matches. Nothing new is trusted: that value comes from
the same verified token the tenant id already did, and it is set by one
function, in one place, for one query.

The alternative was a `security definer` function that looks the tenant up with
the policies suspended. It would have worked, and it is a privilege escalation
kept narrow by convention — nothing stops the next function added beside it from
returning more. `supabase/tests/040_organization_lookup.sql` is what makes the
narrowness of the chosen route checkable: the lookup opens for exactly one row,
reaches no settings without tenant context, and grants no write.

---

## Homepage content

Every section reads `productConfig.marketing` and renders nothing when its list
is empty. Reordering or removing a section is an edit to
`apps/web/src/app/page.tsx`; changing what it says is an edit to the
configuration.

| Section          | Configuration                                          |
|------------------|--------------------------------------------------------|
| `HeroSection`    | `eyebrow` `heroTitle` `heroDescription` `heroNote` CTAs |
| `ValueStrip`     | `values[]`                                             |
| `FeatureGrid`    | `featuresEyebrow` `featuresTitle` `features[]`         |
| `OutcomeSection` | `outcomesEyebrow` `outcomesTitle` `outcomes[]`         |
| `HowItWorks`     | `processEyebrow` `processTitle` `steps[]`              |
| `ProductPreview` | `previewTitle` `previewDescription` `previewImage`     |
| `TrustSection`   | `trustEyebrow` `trustTitle` `trust[]` `trustNote`      |
| `CtaSection`     | `ctaTitle` `ctaDescription` CTAs                       |

### Navigation and footer

`marketing.nav`, `marketing.headerCta` and `marketing.footerGroups`. A group
with no links is not rendered, and neither is the contact address when
`product.contactEmail` is empty — **an empty heading and a mailto nobody reads
are worse than a shorter footer, because they look like a way in and are not.**

The defaults are in-page anchors (`/#features`, `/#security`) plus the two
account routes, because those are the links a generated product can actually
honour. A starter test resolves every default href: an anchor must match an `id`
a section really sets, and a path must have a route directory under
`apps/web/src/app`.

### Product screenshots

```ts
heroImage: { src: '/brand/hero.png', alt: 'The ...', width: 1200, height: 800 },
previewImage: { ... },
```

Both default to `null`, which draws `AppFrame` — an abstraction of the
application's own interface, in the product's brand tokens, with the product's
own name in it. It is decorative and hidden from assistive technology; a real
screenshot is content and takes a real `alt`, which the type requires.

### Trust claims

`trust[]` describes what this repository actually implements: OIDC with PKCE,
row-level tenant isolation, server-side permission checks, WCAG 2.2 AA, request
attribution. **Do not add SOC 2, ISO 27001, HIPAA, FedRAMP or PCI DSS until the
certificate exists.** A starter test fails if any of those names appears in the
default configuration, and `trustNote` says out loud, in the page, that no
certification is claimed.

---

## The marketing site

`apps/marketing` is optional and off by default. When it is generated it renders
the same components from the same configuration, so the two sites cannot say
different things about the product.

It does **not** serve `/login`, `/signup` or `/dashboard` — those are routes of
`apps/web`, on another hostname. Set `product.appUrl` to the web application's
origin as soon as the marketing site is generated; `appHref()` resolves every
account link through it, and setting it in a product without a marketing site is
harmless.

---

## Sign-in and sign-up

### What must not change without an architecture review

- `/api/auth/start`, `/api/auth/callback`, `/api/auth/signout`
- `packages/auth` — session minting, verification, the OAuth helpers
- `src/middleware.ts` — the session gate, `PUBLIC_PATHS`, `PUBLIC_EXACT_PATHS`,
  the CSP and its nonce
- the `href` and `data-testid="sign-in"` on the sign-in control
- the wording of the three outcomes on `/signup/verify`

The last one is not style. Unknown, expired and already-used tokens answer
identically on purpose: telling somebody their link "has expired" tells whoever
is holding a guessed token that it was once real. Rate limiting is the one case
that is distinguished, because it is a fact about the caller rather than about
whether a token exists.

The sign-in redesign changed the layout around the button and nothing else.

One behavioural note that is easy to undo: the sign-in control must not be a
`next/link`. `ButtonLink` renders a plain anchor for any `/api/...` href
because Next prefetches what a link points at, and `/api/auth/start` begins an
OAuth authorization — it mints a state token and a PKCE verifier and sets them
as cookies. Prefetching it starts a sign-in nobody asked for, on hover.

### Why `/` is public and `/dashboard` is not

The middleware protects everything by default, which is the right shape — a new
page is gated unless somebody says otherwise. The public homepage needs one
exemption, and `PUBLIC_PATHS` cannot express it: that list is a prefix match, so
`'/'` in it would open every route in the application. `PUBLIC_EXACT_PATHS` is
matched with `includes` on the whole pathname and cannot widen. The signed-in
landing page moved to `/dashboard` to make room.

A consequence worth knowing: an anonymous request for an unknown path is still
redirected to `/login`, so `not-found.tsx` is reached by signed-in callers and
by `notFound()`, not by strangers. An exemption wide enough to change that is an
exemption wide enough to serve every page.

### The three sign-up states

| State      | When                                        | Rendered             |
|------------|---------------------------------------------|----------------------|
| invitation | `marketing.access.mode === 'invitation'`    | `InvitationOnlyCard` |
| request    | the Control Plane offers no self-serve plan | `RequestAccessCard`  |
| self-serve | it offers at least one                      | `SignupForm`         |

Each is a real business state. **The business rules did not change when this
page was redesigned** — `availablePlans()` and `startSignup()` are untouched.
What changed is that the second state is now a card with something to do in it,
instead of one unstyled sentence saying to get in touch with no way to.

`invitation` is configured rather than detected, because no plan catalogue can
tell you a product is closed on purpose rather than closed by accident.

Both cards render only actions the product can actually perform. With
`product.contactEmail` set there is a "Request access" mailto; without it the
card says plainly that access is arranged by the customer's administrator and
offers Sign in. **Setting `contactEmail` is the first thing worth configuring in
a new product.**

---

## Accessibility

Target WCAG 2.2 AA. What the foundation provides, so pages inherit it:

- a skip link, first in the tab order
- one `<h1>` per page; `Section` owns the eyebrow/heading pattern and keeps the
  outline to real headings
- a visible 3px focus ring on the brand colour, never removed
- every button and link at least 44px tall
- the small-screen menu is a disclosure with `aria-expanded` and `aria-controls`
  pointing at an element that exists in both states, closes on Escape, and
  returns focus to its toggle
- `TextField` / `SelectField` derive `aria-invalid`, `aria-describedby` and
  `role="alert"` from one `error` prop, so they cannot disagree
- `prefers-reduced-motion` disables transitions and smooth scrolling
- anchor targets clear the sticky header via `scroll-margin-top`

Verified at 375, 390, 768, 1024, 1440 with no horizontal scrolling.

---

## Adding to the design system

1. Look in `packages/ui/src/primitives` first.
2. Put the component in the right folder: `primitives`, `brand`, `marketing`,
   `auth`.
3. **Export it from `src/index.ts`.** A starter test fails otherwise — a
   component nobody can import is a component that does not exist.
4. If it imports `@<slug>/branding`, the file must end in **`.hbs`**, because
   the import is written with a template variable and only `.hbs` files are
   rendered.
5. In a `.hbs` file, **never write an inline `style` object literal**. Its two
   braces are a Handlebars expression: the generator refuses to parse the file
   and generation of the whole project stops. Build the object in a function.
6. Use tokens, not colours.

Rules 3 to 6 are asserted by `tests/product-frontend.test.ts` in the generator.

---

## Where things live

```
profiles/product/template/
  packages/branding/src/index.ts.hbs        the configuration
  packages/branding/src/branding.test.ts    the customer-branding parser tests
  packages/ui/src/
    lib/            cn, appHref
    primitives/     Button, Card, Container, Section, Icon, TextField, SelectField
    brand/          ProductLogo, KorasWordmark, brandStyle, BrandScope
    marketing/      PublicHeader, HeroSection, ValueStrip, FeatureGrid,
                    OutcomeSection, HowItWorks, ProductPreview, AppFrame,
                    TrustSection, CtaSection, PublicFooter
    auth/           AuthLayout, AuthBrandPanel, AuthCard, RequestAccessCard,
                    InvitationOnlyCard
    styles/tokens.css
    shell/          AuthenticatedProductShell, ProductHeader,
                    ProductNavigation, ProductProfileMenu, WorkspaceBadge,
                    AccessDenied  -- see docs/PRODUCT_APP_SHELL.md
  apps/web/src/app/     page, dashboard, dashboard/settings, login, signin,
                        signup, not-found
  apps/marketing/src/app/
```

The design language is adapted from `korastech-enterprise` — its content width,
section rhythm, header proportions, card treatment, ink hero and footer
organisation. That repository is a **read-only visual reference**. Nothing here
imports from it, depends on it, or requires it to exist.
