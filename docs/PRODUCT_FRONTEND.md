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
/#pricing         what it costs        every active plan from the platform's
                                       catalogue, prices from the provider's
                                       price preview in the browser; a plan
                                       the team sells gets a card with no
                                       trial and the contact address
/signup           get started          self-serve form, request access,
                                       or invitation only; ?plan= and
                                       ?interval= preselect what a pricing
                                       card chose
/signup/verify    confirm an address   three outcomes, unchanged wording,
                                       plus a checkout where a card is taken
/activate         first password       where the welcome email lands; the
                                       owner sets a password on this page and
                                       never on ZITADEL's (Control Plane R-107)
/dashboard        signed-in landing    behind the session gate, inside the shell
/dashboard/settings       product settings   general; requires settings.read
/dashboard/settings/team  Team & Access      product roles; requires team.read
/dashboard/files          Files              upload, list, download, delete; requires
                                             files.read and the storage.files plan capability
```

Everything from `/dashboard` down renders inside the **authenticated product
shell** — header, sidebar, profile menu, workspace badge — and its navigation is
resolved from a registry rather than written into a component. That half of the
frontend has its own document: `docs/PRODUCT_APP_SHELL.md`, which is
authoritative for the navigation registry, the permission and entitlement model,
product settings and the route gate. This document stays authoritative for the
public surface and for the design tokens both surfaces share.

`apps/marketing`, when generated, serves the same homepage from the same
components. It is a separate deployment with no session, and — unlike
`apps/web` — its language is in the URL, so every page of it is a static
document; see **The marketing site: the language is in the URL** below.

Every one of those pages is served in the visitor's language. A generated
product offers English, German and Spanish, complete in all three, with a
switcher in the footer of every public page, on the sign-in frame, and in
the signed-in Settings beside the appearance control; see **Languages** below.

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
| `i18n`      | the languages offered, and the one a visitor starts in            |
| `marketing` | navigation, every homepage section's copy, footer, access mode    |
| `translations` | the same copy, tagline and navigation labels in each other language |

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

1. the customer's logo set in the Control Plane's portal, when a `tenant` is
   passed and holds one (signed-in surfaces only) — asked for at
   `/api/branding/logo` or `/api/branding/logo-dark`, never at the platform's
   own URL; see *The platform's logos* below
2. a customer's logo from this product's own column, when `tenant` carries one
3. `brand.logoDarkUrl` on a dark surface, when the product has supplied one
4. `brand.logoUrl`
5. the built-in mark

**Step 5 is a finished state, not a placeholder to be embarrassed about.** It
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

`packages/branding/src/branding.test.ts` is that argument, in twenty-two
tests that run as part of the generated project's own `pnpm test`.

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

### The platform's logos

**Decided 2026-09-15: the product serves the platform's images from its own
origin, and the Content-Security-Policy stays `img-src 'self'`.** The portal
stores a customer's `logo_light`, `logo_dark` and `favicon` as `https` URLs on
the platform's storage, and from 2026-09-04 until this decision the parser
dropped all three, deliberately and testably, because a remote URL in a `src`
was a broken image in every header. FOLLOW_UPS F19 left the box open with two
ways to close it, and the one not taken is worth recording: a policy exception
naming the storage origin. That is a decision about *where a customer's logo
may load from*, made by editing a header nobody reads and widened every time
the platform's storage moves — R-042 territory, a claim about the system
living in a line nothing checks. Serving the bytes from here keeps the policy
saying one thing and keeps every image on the page subject to it.

`parsePlatformBranding` now keeps the three URLs in `assets`, apart from the
tokens, under this product's names — `logo`, `logo-dark`, `icon` — and
`isPlatformAssetUrl` decides what is worth keeping: `https` only, which the
platform validates too; no credentials in the URL; no raw addresses and no
`localhost`, `.local` or `.internal` hosts, because the fetch is made from this
product's network on a value a customer typed into a form, and a customer's
logo is not a way to make this product's server read its neighbours.

`apps/web/src/app/api/branding/[asset]/route.ts` is the route. The only input
it takes from the browser is the asset's name, one of three. It resolves the
caller's branding the way every signed-in page does — session, `tenantBranding`,
parser, cached per request — and only then fetches the URL the platform
answered for that caller's own organization, through `fetchPlatformAsset` in
`packages/api-client`: five seconds, two megabytes, image content types only,
no redirects followed, `https` checked again. The bytes come back with the
upstream content type and ETag, `Cache-Control: private, max-age=3600` and
`nosniff`; a customer who set no such image is a 404, and an upstream that
fails is a 502 with the reason in the server log. `ProductLogo` renders
`/api/branding/logo` where the parser kept one and the product's own mark
where it did not, so nothing asks for an image it was not told exists.

The middleware needs no exemption: the route requires a signed-in session, and
a stranger asking for a logo is sent to sign in like a stranger asking for
anything else. `e2e/branding.spec.ts` checks that in a browser;
`packages/api-client/src/assets.test.ts` hands the fetch a server that lies.

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

## Languages

A generated product speaks English, German and Spanish, and every string a
person can read is in a catalogue rather than a component.

```
packages/i18n/src/messages/en.ts     the source of truth: every key, in English
packages/i18n/src/messages/de.ts     typed against it; a missing key fails tsc
packages/i18n/src/messages/es.ts     the same, neutral Spanish for Spain and Latin America
packages/i18n/src/index.ts           Locale, negotiation, createTranslator, the cookie name
packages/branding  productConfig.i18n           which locales this product offers
                   productConfig.translations   the homepage copy, tagline and nav labels per locale
```

**Two lists, on purpose.** `SUPPORTED_LOCALES` in `packages/i18n` is what the
package can *speak* — the catalogues that exist. `productConfig.i18n.locales`
is what the product *offers*. A catalogue can be shipped and reviewed before it
is switched on; a locale cannot be offered without a catalogue, because the
type refuses it. A product that wants English only removes `'de'` from the
offered list and every switcher disappears.

### How a request gets its language

```
stored choice  ->  cookie `koras-locale`  ->  tenant default  ->  Accept-Language  ->  productConfig.i18n.defaultLocale
 the member's,        set by the switcher      the organisation's,   the browser's own     the product's choice
 signed in only                                signed in only
```

Never the URL, in `apps/web` and `apps/admin`: a locale in a query string is
a locale somebody can put in a link, and these are signed-in surfaces. (The
marketing site is a public document and follows a different rule for a
different reason; its section below says why.) `apps/web/src/lib/locale.ts`
resolves it once per request, through
React's `cache`, and the layout, every page and every server component read
that one answer — which is what stops a heading rendering in one language and
the footer in another. Every value is validated against the offered list
before it reaches `lang` or a catalogue lookup — the cookie because a browser
sent it, the stored values because the API holds them to the longer list of
catalogues that *exist*, and a product can stop offering one.

**The two stored sources (F20 phase 2, 2026-09-15).** A signed-in member's
choice is kept with their account, in `member_preferences` — one row per
tenant and subject, written by `PUT /api/v1/me/locale` under the member's own
token and read under a policy keyed to `current_user_id()` as well as the
tenant, so a colleague in the same tenant cannot read it. The organisation's
default is `tenant_settings.locale`, written by `PUT /api/v1/tenant/settings/locale`
by whoever holds `settings.manage`.

> **Where those two live now (2026-09-17).** The settings framework took the
> job. Migration `00031` moved both values to `general.language` in
> `member_setting_values` and `tenant_setting_values`, dropped
> `tenant_settings.locale` and dropped `member_preferences` altogether. The
> paragraph above describes what was true when it was written, and the two
> routes, the policies keyed to the subject and this response are all unchanged
> — the only visible difference is that "follow my browser" is now a value a
> person can choose (`auto`) rather than an absence they could not see. Both ride on the `GET /api/v1/tenant/settings`
response the shell already reads for branding and features, so a signed-in
page pays no extra request for its language; a visitor with no session reads
neither and gets the public order. The stored choice outranks the cookie
because it is the more deliberate of the two — it follows the person to every
device, and a cookie set on a shared machine last month should not win. The
tenant default sits below the cookie because it is a default: what a member
sees before they choose, and a visitor who has chosen, even only on this
device, has chosen. `apps/admin` calls the product's API for nothing, so it
keeps the three-source order; `apps/marketing` has no session either, reads
the language from its URL, and keeps the three-source order only for deciding
where the bare path sends a visitor.

The switcher is a form, and on the public pages it sits in the footer rather
than the header -- the header is the product's name and its links, and the
footer is where a visitor already looks for a site's own settings. The sign-in
frame carries its own, because it renders no footer. Each offered language is
a submit button labelled in
itself — the German button says "Deutsch", and carries `lang="de"` — posting
to `POST /api/locale`, which sets the cookie and redirects back. No script is
needed, which matters most for the visitor who cannot read the current
language. All three applications serve the route, because each is its own
origin. The route refuses a cross-origin post, ignores a locale the product
does not offer, and sends an unsafe return path to `/`.

In `apps/web` the same route also keeps a signed-in member's choice with their
account (`lib/locale-preference.ts`), after the cookie is set and inside the
validated branch — so a value that failed the offered list is never sent to
the API, and the cookie is set whatever the API answers. That is done in the
route handler rather than a server action on purpose: the switcher is a plain
form so it works with no script attached, and the handler is the one place
every form that changes the language arrives at. A failed write is logged
server-side and never shown; the next request that can read the stored value
will, and until then the cookie says the same thing.

The organisation's default is a different write with a different authority,
and it is a server action (`dashboard/settings/actions.ts`) behind a client
form, because it changes nothing the person saving it can see — their own
choice outranks it — so the form has to say that it worked. The page shows it
to `settings.manage`, the action checks the same permission, and the API
refuses the write for anyone else with the same token.

### The marketing site: the language is in the URL

```
/          the default language (productConfig.i18n.defaultLocale), bare
/de  /es   every other offered language, prefixed
/en        redirected to / permanently — one document, one address
/fr        404 — not a fallback; the product does not offer French
```

`apps/marketing` is a public document that search engines and shared links
address by language, and a document whose language depends on a cookie
cannot be cached as one. So the site lives under `src/app/[locale]/`:
`generateStaticParams` names the offered locales, `dynamicParams = false`
refuses every other value at the router, and the layout validates the
segment again against `productConfig.i18n.locales` — the *offered* list, not
everything `packages/i18n` can speak — before it reaches `lang`. Each page is
built once per language at deploy time and served from the edge. The plans
the pricing section shows are fetched with `next: { revalidate: 600 }` rather
than as a no-store fetch, because a no-store fetch would make the page render
per request again; a price ten minutes stale on a marketing page is not a
defect.

**The default language is bare** (`/`, not `/en`) because the address a
product prints is the address its page should have, and because a site that
redirects `/` to `/en` on every visit pays a round trip for its most common
request. `/en` is redirected to `/` with a 308 so no document has two
addresses. `<link rel="canonical">` and one `hreflang` link per offered
language (plus `x-default` at `/`) come from `generateMetadata`, resolved
against `product.url` when the product has one.

**What still varies per request is where the bare path sends a visitor**, and
that lives in `src/middleware.ts`, the one part of the site that runs per
request. The order is the public one: the cookie the switcher set, then
`Accept-Language`, then the default. The default is a *rewrite* (the visitor
stays on `/` and is served the default document); any other language is a 307
redirect to its address, with `Vary: Cookie, Accept-Language` so a cache in
front never hands one visitor's redirect to the next. A language spelled out
in the URL wins over both, and is written to the cookie: the logo and the
in-page anchors link to `/`, and a visitor reading `/es` should come back to
Spanish rather than to their browser's language.

The footer switcher posts to this site's own `/api/locale`, which sets the
cookie exactly as the web route does and then sends the visitor to the chosen
language's copy of the page they were on — `/` becomes `/de`, `/de` becomes
`/` for English — because on this site "German" is an address, not only a
cookie. `apps/web` still learns the choice through `Accept-Language`, as it
did before: the two sites are two origins and the cookie is scoped to one.

`e2e/language.spec.ts` starts the marketing site as a second Playwright
server (when the product has one) and proves the four rows of the table
above in a browser, plus the switcher and the alternates.

### How a component gets its language

As a prop. `locale` is a two-letter string, so it crosses the server/client
boundary like every other prop the shell takes, and `createTranslator(locale)`
is a plain function that works in a server component, a client component and a
route handler alike. There is no provider and no context. A server component
calls `translator()` from `lib/locale.ts`; a client component is handed
`locale` and builds its own.

```tsx
const t = createTranslator(locale)
t('login.heading', { product: product.name })          // "Sign in to Acme"
rich(t('dashboard.start.build'), { code: codeTag })    // <code>…</code> inside a sentence
```

Placeholders are `{name}`, single-braced, because these files are also
Handlebars templates and a doubled brace is the generator's delimiter. A
message may carry `<code>`, `<a>` or `<strong>`; `rich()` in `packages/ui`
maps each tag to an element and never sets `innerHTML`.

### What is translated where

| Kind of string                       | Lives in                                   |
|--------------------------------------|--------------------------------------------|
| Interface chrome, errors, legal pages | `packages/i18n/src/messages/<locale>.ts`   |
| An API refusal (`errors.<code>`)     | `packages/i18n`, mapped by `apps/web/src/lib/api-errors.ts` |
| Mail the API and the worker send     | `python-packages/koras-email/src/koras_email/i18n.py` |
| Homepage copy, tagline, description  | `productConfig.translations.<locale>`      |
| Sidebar module and group labels      | `productConfig.translations.<locale>.navigation` |
| The product's name, slug, addresses  | not translated; a product has one name     |
| Role and permission identifiers      | not translated; they are code, not copy    |

`marketingFor`, `productFor` and `navigationFor` merge a translation over the
default field by field, so a product that has translated its hero and nothing
else gets a German hero and an English feature grid rather than a page of keys.
The navigation is translated by module id, so reordering the registry cannot
put the wrong word on the wrong entry — and the middleware still reads
`productConfig.navigation` directly, so the route gate and the translated
sidebar describe one registry.

### API refusals and mail

Every route of the product API answers a refusal as `{ code, message }`
(`services/api/koras_api/core/errors.py`, `ApiErrorCode`). The `code` is the
contract and the only part a person's screen is built from; `message` is
English, for the log, and may change. The web tier maps each code to
`errors.<code>` (camelCase) in `apps/web/src/lib/api-errors.ts`, falling back
to the status-based sentences it already had for a refusal without a code,
and the structural test in the starter asserts that every person-facing code
has a sentence in every catalogue and a branch in the mapping.

Mail is composed in Python, so it has a catalogue of its own:
`koras_email.i18n`, the same three languages, typed as a `TypedDict` so a
line missing from one language fails `mypy --strict`. The assistant's
approval notice is written in the language of the request that produced it
(`Accept-Language`, `core/locale.py`); a scheduled report's delivery in the
language the schedule names (`locale` on the schedule, migration 00016),
defaulting to the request's. The web tier's API client does not yet send
`Accept-Language`, so today both default to English until it does.

### What it costs, and what is not done

The marketing homepage is a cached static document again, one per language
(above); what it cost is the `[locale]` segment and a middleware that runs
per request to decide where `/` goes. `docs/FOLLOW_UPS.md` F20 has the
reasoning, and records which of its boxes are closed: the stored preference
and the tenant default, the admin application, the marketing URL, and the
email and API-error text, closed on 2026-09-15. What remains English is the
description of each proposed action inside the approval notice ("Delete the
file X"), which `summarize` composes because a per-tool catalogue is the
assistant's to grow, and the report names and column headings inside a
delivered report, which are the definition's.

**`apps/admin` speaks the same languages.** It depends on `packages/i18n` and
`packages/branding` (apps may depend on packages; `i18n` stays a leaf), resolves
the locale the public way in its own `lib/locale.ts`, serves its own
`/api/locale` named in its middleware's `PUBLIC_PATHS`, sets `lang` and `dir`
from the resolved locale, carries the switcher in a footer on every page
including sign-in, and reads every sentence — the two middleware refusals
included, resolved from the same cookie and header at the edge — from the
catalogues under the `admin.*` keys. This profile ships its own
`apps/admin/src/app/globals.css`, overriding the shared one, because the
switcher is drawn in the brand tokens and the shared stylesheet imported
Tailwind alone. `product-i18n.test.ts` holds it to the same rules as
`apps/web`.

The tests worth knowing: `packages/i18n` asserts every translation keeps its
placeholders and tags, and that the resolver ranks the stored choice, the
cookie and the tenant default in that order; `packages/branding` asserts a
translated list keeps its shape and its links; `product-i18n.test.ts` in the
starter asserts no layout in any of the three applications hardcodes
`lang="en"`, every page resolves the locale, every catalogue key is used and
every used key exists, no component carries a sentence of English prose, the
web resolver reads its five sources in the documented order and the other two
read only three, the tenant default is gated on `settings.manage` at the page,
the action and the router, and the router's `SUPPORTED_LOCALES` is the same
list as the package's; `tests/unit/test_tenant_locale.py` asserts the two
writes refuse a language outside the catalogues before anything is written
and key on the verified subject; `supabase/tests/160_member_preferences_isolation.sql`
asserts a preference is readable and writable by its own subject in its own
tenant and by nobody else, including a colleague and a request with no subject;
every person-facing API error code has a sentence in every catalogue and a
branch in the web mapping; and `e2e/language.spec.ts` presses the button in a
browser and reads `html[lang]` back, on both sites.

---

## Homepage content

Every section reads `productConfig.marketing` through `marketingFor(locale)`
and renders nothing when its list is empty. Reordering or removing a section is an edit to
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
- the fourth outcome, `awaiting-payment`, sends the browser to the payment
  provider's hosted checkout from `Checkout.tsx`, at a URL the Control Plane
  minted, and the provider sends it back to `/signup/verify` with the
  registration id; the product holds no provider credential and loads no
  provider script, and the run starts from the provider's webhook, never
  from the browser — see `BILLING_DESIGN.md`

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
  packages/api-client/src/index.ts          the JSON client, and fetchPlatformAsset for the platform's images
  packages/branding/src/i18n-config.test.ts the translation-merge tests
  packages/i18n/src/index.ts                Locale, negotiation, createTranslator
  packages/i18n/src/messages/               en.ts (source of truth), de.ts, es.ts
  packages/ui/src/
    lib/            cn, appHref
    i18n/           LanguageSwitcher, rich, codeTag, strongTag
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
                        signup, not-found, api/locale, api/branding/[asset]
  apps/web/src/lib/locale.ts.hbs            currentLocale, translator -- once per request
  apps/marketing/src/app/                   the same homepage, api/locale
  apps/marketing/src/lib/locale.ts.hbs
  e2e/language.spec.ts.hbs                  the switcher, in a browser
```

The design language is adapted from `korastech-enterprise` — its content width,
section rhythm, header proportions, card treatment, ink hero and footer
organisation. That repository is a **read-only visual reference**. Nothing here
imports from it, depends on it, or requires it to exist.
