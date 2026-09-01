# Authenticated Product Shell — Audit

What a generated KORAS product has today for its **signed-in** surface, what it
does not have, and which existing mechanism each missing piece should extend
rather than replace.

This is the Phase 1 deliverable for the authenticated product shell work. The
target standard is `docs/PRODUCT_APP_SHELL.md`; this document is the survey it
rests on. `docs/PRODUCT_FRONTEND.md` remains authoritative for the **public**
surface — homepage, sign-in, sign-up — and for the design-token rules that both
surfaces share.

**Scope, stated once and enforced throughout.** This covers the `product`
profile of `koras-saas-starter` only. The KORAS Control Plane repository is
**out of scope and must not be modified**; so are the Control Plane admin UI and
the Customer Portal, including the copies of them under
`profiles/control-plane/template/`. Section 15 records how that was verified.

---

## 1. Current architecture

A generated product is a pnpm/Turborepo monorepo. The frontend half:

```
packages/branding      productConfig: identity, brand tokens, marketing copy.
                       No React, no JSX — it is the leaf.
        |
packages/ui            the design system. Ships TypeScript sources, not built
                       output, so each app decides client vs server per file.
        |
apps/web               the customer-facing application  (required)
apps/marketing         the same components, no session   (optional, off)
apps/admin             internal operations UI            (optional, on)
```

Routes `apps/web` ships today:

| Route            | Gate        | What it is                                    |
|------------------|-------------|-----------------------------------------------|
| `/`              | public      | marketing homepage                            |
| `/login`         | public      | two-panel sign-in                             |
| `/signin`        | public      | redirect to `/login`, forwards `?next`        |
| `/signup`        | public      | three states: self-serve, request, invitation |
| `/signup/verify` | public      | address confirmation                          |
| `/api/auth/*`    | public      | start, callback, signout                      |
| `/dashboard`     | **session** | the entire signed-in area — one page          |

**The signed-in area is one route and one layout.** `apps/web/src/app/dashboard/layout.tsx`
renders a `BrandScope`, a single-row header (logo, person's name, a sign-out
form) and its children. `apps/web/src/app/dashboard/page.tsx` is a welcome card
that says, in as many words, that the first screen a team builds replaces it.

There is **no sidebar, no navigation of any kind, no profile menu, no workspace
indicator and no settings area** on the authenticated side. That is the gap this
work fills. The page is deliberately close to empty — the template's own comment
argues that an invented dashboard of fake charts would have to be deleted before
the real one could be written — and the same argument applies to navigation: an
invented module list would have to be deleted. A *registry* with nothing in it
does not.

`apps/admin` is a different thing and is easy to mistake for the target. It is
the **internal operations** application: its middleware requires
`canAdminister()` and a second factor, and it exists for the team running the
product, not for a customer's administrators. Product-level administration —
Team & Access, Integrations, Settings — belongs in `apps/web` behind the same
session gate as the rest of the product. Its shell today is a bare heading.

---

## 2. Existing reusable components

`packages/ui` exports thirty symbols from one barrel, `packages/ui/src/index.ts`.
Nothing imports a path inside the package, and a starter test fails if a
component module is not re-exported.

| Folder        | What is there                                                                              |
|---------------|--------------------------------------------------------------------------------------------|
| `lib/`        | `cn`, `appHref`                                                                              |
| `primitives/` | `Button`, `ButtonLink`, `Card`, `Container`, `Section`, `Icon`, `TextField`, `SelectField`    |
| `brand/`      | `ProductLogo`, `KorasWordmark`, `brandStyle`, `BrandScope`                                    |
| `marketing/`  | eleven public-page sections, including `PublicHeader`                                         |
| `auth/`       | `AuthLayout`, `AuthBrandPanel`, `AuthCard`, `RequestAccessCard`, `InvitationOnlyCard`         |

Directly reusable by an authenticated shell:

- **`BrandScope`** — already wraps the whole signed-in subtree and re-declares
  the CSS custom properties for one tenant. The shell needs no new branding
  mechanism; it needs to be *inside* this one, which it already is.
- **`ProductLogo`** — the four-step logo resolution (tenant, dark variant,
  product, drawn mark) is finished and takes a tenant prop. A shell header must
  call this and must not reach for an image path.
- **`Button` / `ButtonLink`** — every variant is at least 44px tall, and
  `ButtonLink` already renders a plain anchor for API hrefs, which is what keeps
  `next/link` from prefetching an OAuth start.
- **`Icon`** — a closed `IconName` union declared in `packages/branding` and
  drawn in `packages/ui/src/primitives/icon.tsx`. A starter test asserts every
  declared name has a path. Navigation icons must go through this union; a
  free-string icon name would render a hole.
- **`Container`**, `Card`, `Section` — layout, already token-driven.

**`PublicHeader` is the closest prior art for responsive behaviour** and should
be read before writing the authenticated one: it is a disclosure rather than a
dialog, renders the panel in both states so its `aria-controls` points at a real
element, closes on Escape, returns focus to the toggle, and closes on route
change. Those five properties are the accessibility contract to reproduce — not
the component itself, which is bound to the marketing navigation.

---

## 3. Existing navigation mechanism

**For the public site only.** The marketing navigation is a flat list of label
and href, plus a header call to action and footer groups. It has no concept of a
group, an icon, an order, a permission or an entitlement, and a starter test
resolves every default href to a real anchor id or a real route directory.

There is **no authenticated navigation registry, no route metadata and no
resolver**. The signed-in header hardcodes its three elements.

Two properties of the public mechanism are worth carrying forward and one is
not. Carry forward: configuration lives in `packages/branding` (the leaf, no
React), and every link is asserted to resolve. Do not carry forward: a flat list
of label and href — the authenticated side needs grouping and access metadata,
so this is an extension of the same idea rather than a reuse of the same type.

---

## 4. Existing authorization model

Three enforcement points exist and are genuinely wired.

**Edge — `apps/web/src/middleware.ts`.** Closed by default: every path is gated
unless it matches the prefix list `PUBLIC_PATHS` or the exact list
`PUBLIC_EXACT_PATHS`, which holds only the homepage. It verifies the
application's own signed session cookie — a local HS256 check, no network — and
answers:

- anonymous → redirect to the login page with a `next` parameter
- MFA required → 403 with text
- session present but no recognised role → 403, "no access to this application"
- otherwise → continue, with a per-request CSP nonce

**Server components — `apps/web/src/lib/session.ts`.** `currentMember()` returns
a member session or null by verifying the same cookie. The file's own comment
records why there is exactly one reader: the Control Plane grew a second one
that decoded without verifying and silently found nothing.

**API — `services/api/koras_api/core/auth.py` and `core/tenant.py`.**
`require_auth` verifies a ZITADEL token against the JWKS (401 on failure);
`require_tenant` resolves tenant context (403 when absent). The API deliberately
does **not** trust the session cookie the browser tier signed — the two cookies
have separate jobs, and `providerToken()` forwards the provider's own token.

**The role model is a closed, deliberately unranked set** in
`packages/permissions/src/index.ts`:

```
organization_owner  organization_admin  billing_admin  security_admin  member
```

`ADMIN_ROLES` is owner and admin, listed explicitly rather than ordered — the
file argues that a hierarchy invites "at least admin" comparisons that widen the
moment a role is inserted mid-ordering. Helpers: `isOrganizationRole`,
`canAdminister`, `hasAnyRole`. Platform roles are **absent on purpose**; a
product that can name one is a product that can honour one arriving in a token.

**What does not exist: permissions.** There is no permission string anywhere —
no `reports.read`, no `team.manage`, no permission-to-role map, on either the
TypeScript or the Python side. Authorization today is role-shaped only. Any
navigation metadata naming required permissions needs that vocabulary created
first, or it is a field nothing can evaluate.

---

## 5. Existing tenant / workspace model

One tenant model, in the database, and it is not multi-workspace.

`supabase/migrations/00001_initial.sql` creates tenants, tenant members (tenant
id, user id = ZITADEL subject, role, unique per pair) and tenant settings
(branding jsonb, domains text array, features jsonb). All three have RLS
*forced*, not merely enabled — the migration explains that enabling alone
exempts the owner, which is the only connection that reads the data.
`supabase/migrations/00003_platform_provisioning.sql` adds a tenant key, a
lifecycle status and the Control Plane's organization id.

In the browser tier the tenant is **the session cookie's organization id** and
nothing else. `apps/web/src/app/dashboard/layout.tsx` reads it from the verified
session; the file states the rule plainly — never from a URL or a header, even
though branding is only decoration.

The organization id itself is hard-won: `packages/auth` derives it from the
ZITADEL organization claim when present, otherwise from the shape of the roles
claim, and **refuses when a token names two organizations** rather than picking
one.

Consequences for the shell:

- **A session carries exactly one organization.** There is no list of
  organizations a person may act for, no switcher, and no mechanism to switch —
  a switch would mean a new token from ZITADEL, not a client-side state change.
  A workspace *switcher* is therefore not a small addition; a workspace
  *indicator* is.
- `packages/tenant/src/index.ts` is a fifteen-line stub with an unused hostname
  helper. It is not wired to anything.

---

## 6. Existing entitlement model

**Authoritative in the Control Plane, absent in the product.**

The Control Plane owns subscriptions (organization by product, giving plan,
status and period) and entitlements (subscription, feature, limit value,
enabled). It exposes the resolved pair — a plan code and a list of effective
entitlements — on an organization-and-product route of its platform API.

A generated **product** has no client for that endpoint. `packages/billing`,
`packages/domains`, `packages/feature-flags`, `packages/api-client` and
`packages/types` are all empty stubs. `koras-e2e-shop` went further and removed
its control-plane client package outright.

The one existing product-to-Control-Plane call is the signup path:
`apps/web/src/app/signup/actions.ts` fetches the plan catalogue server-side, on
the argument that the platform's address is not the browser's business, and
treats failure and emptiness identically for the visitor while logging the
difference for the operator. **That is the shape any entitlement read should
copy**: server-side, address from the environment, failure degrades to a defined
state, and the log distinguishes what the UI does not.

`koras-profile-product` already states the rule this must satisfy —
"entitlements are enforced, not assumed", and "subscriptions and plans are
Control Plane state; do not create local plan tables".

---

## 7. Existing feature / capability model

Three different things share the word "feature", and keeping them apart is most
of the design work.

| Layer | Where | Decided by | Lifetime |
|-------|-------|-----------|----------|
| **Capability** | `profiles/product/manifest.yaml`, recorded in `.koras/project.yaml` under components | generation time (`--with` / `--without`) | fixed for the repository |
| **Entitlement** | Control Plane entitlements table | the customer's plan | changes with the subscription |
| **Feature** | the tenant settings features column | the tenant's own configuration | changes at will |

The capability layer is real and enforced: the profile manifest's
`template_map` includes or excludes whole subtrees, so a product generated
without the worker has no worker service at all, and `.koras/project.yaml`
records the selections — `koras-e2e-shop` lists twelve capabilities and two
applications.

The entitlement layer is described in section 6.

The feature layer is a **column with no reader**. The tenant settings features
column exists in the migration and nothing anywhere reads it.

---

## 8. Existing branding / theming system

This is the strongest part of the current architecture and needs extending, not
replacing. It is documented at length in `docs/PRODUCT_FRONTEND.md`; in summary:

```
:root                     defaults, plain CSS custom properties
@theme inline             Tailwind utilities that reference those properties
brandStyle(tokens)        object of --brand-* properties
body style                applied once per app, from the product configuration
BrandScope tenant         re-declares them for one customer's subtree
```

The `inline` keyword is load-bearing: without it Tailwind bakes the value into
every utility at build time and a runtime override changes nothing. With it,
`bg-brand` compiles to a reference to the custom property.

Customer overrides are already designed and already safe:

- The overridable list is eight keys — three brand colours, muted surface,
  border, radius, two logos — plus a white-label name capped at sixty
  characters. The semantic text colours and font stacks are **excluded on
  purpose**.
- `parseTenantBranding` validates hex-only colours, three length units for the
  radius, and same-origin absolute paths for images (no data URLs, no
  protocol-relative hosts, no remote origins). Unknown keys drop; one bad value
  costs one token, not the brand. Twelve tests in
  `packages/branding/src/branding.test.ts` run inside the generated project's
  own test task.
- `brandingFor(base, tenant)` merges; the no-op constant is what an unbranded
  tenant gets.

**The one unwired seam** is `apps/web/src/lib/tenant-branding.ts`. It returns the
no-op today and documents exactly what is missing: a customer-facing route on
`services/api` returning the calling tenant's stored branding, scoped by RLS
context and never by a browser-supplied tenant id. Everything downstream of that
function is finished.

Accessibility guarantees already in `packages/ui/src/styles/tokens.css`: a 3px
focus-visible outline on the brand colour that is never removed, a skip link,
reduced-motion handling, scroll margin for anchor targets.

A starter test fails on **any** six-digit hex literal in `packages/ui` outside
the logo component and the token stylesheet. Any new shell component inherits
that constraint.

---

## 9. Existing generator / sync flow

Rendering is two template layers plus verbatim assets:

```
profiles/_shared/template/     walked first
profiles/product/template/     walked second, wins on a shared path
        rendered through Handlebars, then filtered by the manifest template map
shared assets: the Terraform modules and .claude, copied verbatim
```

`shared-template-parity.test.ts` forbids a byte-identical path in both profile
templates. Files interpolating the project slug **must** end in `.hbs`, and a
`.hbs` file **must not** contain a JSX inline style object literal — its two
braces are a Handlebars expression and generation of the whole project stops.
Both rules are asserted by
`generators/create-koras-app/tests/product-frontend.test.ts`.

The **sync mechanism for an existing project** is the generator itself, run
against a project already on disk:

| Flag | What it does |
|------|--------------|
| `--check-drift` | read-only; reports where a project no longer matches the generator |
| `--check-drift --all` | widens that to every generator-owned file |
| `--refresh <path>` | overwrites **one named** rendered file from the generator's rendering |
| `--refresh-modules` | re-copies shared assets (Terraform modules, `.claude`) wholesale |
| `--dry-run` | with any of the above, writes nothing |

The split is deliberate and is the constraint that shapes migration: shared
assets belong to the starter and can be recopied wholesale; **everything
rendered from the template is lived in**, so naming the path is the operator's
consent. There is no "sync everything" command, and adding one would discard
real work.

`.koras/project.yaml` records a template digest, a sha256 over the profile's
manifest, defaults and every template file, normalised to LF. It moves on its
own, unlike the starter version, which has sat at 0.1.0 since the beginning.

---

## 10. Existing tests

| Suite | Where | What it covers |
|-------|-------|----------------|
| Generator structural | `generators/create-koras-app/tests/` (vitest) | forty files. `product-frontend.test.ts` guards the barrel, the template rules, the icon union, link resolution, no hex literals, no certification claims. `public-routes.test.ts` guards the middleware exemptions. |
| Generated-project build | `generators/create-koras-app/tests/generated-builds.test.ts` | generates and builds |
| Branding parser | `profiles/product/template/packages/branding/src/branding.test.ts` | ships into the product; runs in its own test task |
| Auth | the auth package's own tests in both layers | session, cookie session, OAuth, end to end |
| Docs | `tests/docs/file-references.test.ts` and its siblings | **every backticked path with an extension in the documentation must exist in `git ls-files`**; enumerations are compared against their real source |
| RLS | `supabase/tests/010_rls_structure.sql` and the product's own, run in CI against real Postgres and mutation-tested by removing `force` | tenant isolation |
| e2e | `tests/e2e/product-provision.test.ts` | generate, validate, register, against a Control Plane stub |
| Python | pytest | API surface, settings declared, no state artifacts |

**There is no Playwright and no browser-driven test anywhere in the starter.**
The `webapp-testing` skill is vendored but unused. A "sign in and click around"
verification therefore has no existing harness to extend, and building one is a
larger piece of work than the shell itself.

`local/scripts/smoke-signin.mjs` is the closest thing: a deployment smoke check
that resolves the sign-in test id and reads its href. That test id is named in
`docs/PRODUCT_FRONTEND.md` as something that must not change.

---

## 11. Gaps

Ordered by what blocks what.

| # | Gap | Consequence |
|---|-----|-------------|
| G1 | No authenticated shell beyond a one-row header | every product builds its own; nothing is inherited |
| G2 | No navigation registry, no metadata, no resolver | product modules cannot be declared |
| G3 | **No permission vocabulary at all** | required-permission metadata has nothing to name; role is the only axis evaluable today |
| G4 | No product-access concept | "which organization users may use this product" is not modelled anywhere |
| G5 | No entitlement client in the product | plan gating cannot be evaluated |
| G6 | The tenant settings features column has no reader | tenant feature flags cannot be evaluated |
| G7 | Tenant branding returns nothing; no customer-facing API route | customer branding never resolves at runtime, though every piece downstream is finished |
| G8 | No profile menu, no workspace indicator | sign-out is a bare form button; the organization is never shown |
| G9 | No product settings area, no Team & Access | product administration has nowhere to live |
| G10 | Session carries one organization and cannot switch | a switcher is a token problem, not a UI problem |
| G11 | No sidebar-collapse preference mechanism | no existing client preference store of any kind |
| G12 | No browser-level test harness | shell behaviour (drawer, focus, active state) cannot be asserted the way the rest of the repo asserts things |

---

## 12. Risks

**R-A — inventing a permission model.** G3 is the sharpest. Creating permission
strings in the product means creating an authority the Control Plane does not
know about, and `koras-profile-product` forbids a second billing or plan
lifecycle for exactly that reason. The safe move is a *product-local* permission
vocabulary derived from roles, declared in `packages/permissions`, with the
role-to-permission map in one place — not a new grant store.

**R-B — hidden navigation read as authorization.** The single largest failure
mode of any navigation registry. `koras-profile-product` rule 4 already says
client-side guards are UX; the shell must make the server check the easier thing
to write, or the registry becomes the de facto boundary.

**R-C — the template brace trap.** Any shell component importing the branding
package must be a `.hbs` file, and must not contain a JSX inline style object.
Getting this wrong does not fail the component; it stops generation of the
entire project. Already guarded by a test, which is why the test must keep
passing.

**R-D — Tailwind source visibility.** New utility classes used only inside
`packages/ui` are invisible unless the source directive covers them. It already
does, but a new package would need its own line, which is an argument for
putting the shell **inside `packages/ui`** rather than in a new package.

**R-E — R-042.** Documentation is the one part of this repository that can be
wrong without anything going red. Claims about *where* are checked by the docs
tests; claims about *why* are not. Both new documents are subject to it, and
every path they name must be tracked by git.

**R-F — R-030, products.** A generated product's repository is private, private
repositories consume paid Actions minutes, and this account's billing is
failing. `koras-e2e-shop` therefore has no working CI. Any verification of the
synced product has to be local.

**R-G — drift between the starter and `koras-e2e-shop`.** The product was
generated before several template changes and is missing files the template now
has. The refresh flag is per path by design, so a shell spanning a dozen new
files means a dozen named paths, and any of them that the project has edited
would be overwritten.

---

## 13. Technical constraints

1. **A file is `.hbs` when it interpolates; never a JSX inline style object
   inside one.**
2. **No hex literal in `packages/ui`** outside the two exempt files. Tokens only.
3. **Barrel export required** — a component not re-exported from
   `packages/ui/src/index.ts` fails a starter test.
4. **Icons come from the closed `IconName` union** in `packages/branding`, drawn
   in `packages/ui/src/primitives/icon.tsx`. Every declared name needs a path.
5. **`packages/branding` must stay free of React and JSX.** It is what
   `packages/ui` imports.
6. **The middleware matcher and the two public-path lists must not widen.** The
   prefix list is a prefix match; a bare root in it opens the application, and a
   test asserts it is never there.
7. **CSP: images and fonts same-origin only, script only via the per-request
   nonce.** A remote logo, a webfont from a CDN, or an inline script without the
   nonce is silently blocked.
8. **Every backticked path in the documentation must be in `git ls-files`.** New
   files must be at least intent-added before the docs test passes.
9. **The session is one organization, verified locally, no network in the hot
   path.** Anything the shell needs per request must come from the cookie or be
   fetched server-side in the layout.
10. **`packages/ui` ships sources and each app lists it in its transpile list.**
    A client directive in a shared component is honoured; a build step would
    have to choose once.
11. **No new runtime dependency should reach `packages/ui` lightly.** The class
    joiner is hand-written specifically to avoid two dependencies in a package
    that ships into every generated product.

---

## 14. Potential impact on generated products

- **`koras-e2e-shop`** — the one existing generated product, profile `product`,
  components web and admin plus api and worker plus twelve capabilities. It is a
  git repository with a clean tree. It receives the shell only through
  explicitly named refresh paths.
- **Any future product** — inherits the shell at generation with no action, which
  is the point.
- **The Control Plane profile** — must inherit **nothing**. The shell lives under
  `profiles/product/template/`, which the control-plane profile does not walk.
  `profiles/_shared/template/` is walked by both and is therefore the wrong
  place for any of it.
- **`.koras/project.yaml`** — no schema change is needed. Capabilities are
  already recorded under components, which is the field a capability-aware
  resolver reads.
- **The template digest** — changes as soon as any template file changes, so
  every existing project reads as behind. That is correct and is what the
  drift check is for.

---

## 15. koras-control-plane is out of scope — confirmation

Explicitly confirmed for this phase:

- **No file in the Control Plane repository was read for this audit and none
  will be written.** Every Control Plane fact above comes from the starter's own
  `profiles/control-plane/template/` and from the contract file
  `profiles/_shared/template/contracts/product-platform.v1.json`.
- **`profiles/control-plane/template/` is read-only for this work**, including
  its portal application, its api-client, its permissions package and its
  migrations. Changing any of them would change a generated Control Plane, which
  is the same prohibition one layer up.
- **`profiles/_shared/template/` must not receive shell code.** Both profiles
  walk it, so a shell component placed there would ship into the Control Plane.
  This is the single most likely accidental violation, and it is structural
  rather than a matter of care: the file's location decides it.
- The product **reads** Control Plane state (plans, entitlements) over HTTP and
  **writes** none of it. That boundary is `koras-profile-product` rule 6 and is
  unchanged by this work.

The end-of-task verification is a `git status` in the Control Plane repository
returning the same tree it started with.
