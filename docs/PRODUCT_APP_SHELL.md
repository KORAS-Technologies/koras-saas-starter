# KORAS Authenticated Product Application Shell

The standard every generated KORAS product inherits for its **signed-in**
surface: one shell, one navigation registry, one access model, one brand
resolution chain.

Read `docs/PRODUCT_SHELL_AUDIT.md` first for what existed before this and why
each decision below extends it rather than replaces it. `docs/PRODUCT_FRONTEND.md`
stays authoritative for the public surface and for the design-token rules both
surfaces obey.

**Out of scope, permanently:** the KORAS Control Plane and the KORAS Customer
Portal. Nothing here ships into `profiles/control-plane/template/` or into
`profiles/_shared/template/`, and the reason is structural rather than a matter
of discipline — both profiles walk the shared layer, so a shell component placed
there would appear in a generated Control Plane. Every file this standard
defines lives under `profiles/product/template/`.

---

## 1. Problem statement

A generated product's signed-in area is one route, one layout and a header with
three elements. Every product team therefore invents its own navigation, its own
header, its own settings area and its own idea of who may see what — and each
invention is a place where hidden navigation quietly becomes the authorization
boundary. Nothing improves for the products already generated, because there is
nothing shared to improve.

## 2. Goals

1. One authenticated shell every product inherits at generation.
2. Product modules declared as **configuration**, never by editing shell internals.
3. Navigation **resolved** from access rules — never a per-role sidebar.
4. The same metadata that hides a link **also refuses the route**, so the two
   cannot drift.
5. Customer branding reaching the shell through the tokens already in place.
6. Product administration inside the same shell, visible only where authorised.
7. Nothing product-specific in the starter. Docoris, LegalApp and Dianova
   modules are examples in documentation and appear in no template file.

## 3. Non-goals

- **Not** a Customer Portal. Billing, subscriptions, domains, SSO, organization
  membership and invitations stay in the portal. The product links out to them
  at most.
- **Not** Control Plane administration. Products, tenants, provisioning and
  infrastructure are not product concerns.
- **Not** a branding editor. Runtime branding support and the configuration
  contract, yes; a management application, no — that is a separate feature.
- **Not** a new tenant model. One session, one organization (see section 13).
- **Not** a per-product grant store. Product access derives from organization
  role today, behind one named seam (section 13).

## 4. Existing architecture findings

Summarised from the audit; each drives a decision below.

| Finding | Consequence for this design |
|---------|-----------------------------|
| `BrandScope` already re-skins the signed-in subtree | the shell renders *inside* it; no new branding mechanism |
| `ProductLogo` already resolves tenant, then product, then a drawn mark | the header calls it and never reaches for an image path |
| Design tokens are runtime CSS custom properties | tenant branding is free; no component learns a tenant exists |
| Icons are a closed union asserted against drawn paths | navigation icons use that union, extended by four names |
| **No permission vocabulary exists** | one must be created, product-local, derived from roles |
| **No product-access model exists** | derived from organization role behind one seam |
| Entitlements are Control Plane state, read over HTTP | one server-side read, degrading like the signup plan read |
| Session carries exactly one organization | a workspace *indicator*, not a switcher |
| `packages/ui` ships sources; apps transpile | client and server components can coexist in the shell |
| Sync is per-named-path | migration is a list of paths, stated in section 24 |

## 5. Proposed shell architecture

```
apps/web/src/app/dashboard/layout.tsx        (server)
  reads session          -> member, organization
  reads tenant branding  -> BrandScope
  builds AccessContext   -> signedInContext()
  resolves navigation    -> resolveNavigation(productConfig.navigation, access)
  renders:
    BrandScope tenant
      AuthenticatedProductShell  (client, serialisable props)
        ProductHeader      logo, workspace badge, profile menu
        ProductSidebar     ProductNavigation
        main               the page
```

Everything the shell receives is plain serialisable data. It never reads a
cookie, never calls the Control Plane, and never decides access — it renders a
decision made on the server.

Desktop:

```
+--------------------------------------------------------------+
| ProductHeader                                                |
+---------------------+----------------------------------------+
| ProductSidebar      | main                                   |
| (expanded/collapsed)|                                        |
+---------------------+----------------------------------------+
```

Small screens:

```
+--------------------------------------------------------------+
| menu | logo, product | profile                               |
+--------------------------------------------------------------+
| main                                                         |
+--------------------------------------------------------------+
```

The sidebar becomes a drawer over the content, closing on navigation and on
Escape.

**Names**, following the repository's existing convention of plain descriptive
component names exported from one barrel:

| Component | File under `packages/ui/src/shell/` |
|-----------|--------------------------------------|
| `AuthenticatedProductShell` | `product-shell.tsx` |
| `ProductHeader` | `product-header.tsx` |
| `ProductNavigation` | `product-navigation.tsx` |
| `ProductProfileMenu` | `profile-menu.tsx` |
| `WorkspaceBadge` | `workspace-badge.tsx` |
| `AccessDenied` | `access-denied.tsx` |

`ProductSidebar` is not a separate export: it is the shell's own aside, and
splitting it would mean passing the collapse state back and forth between two
components that are never used apart.

## 6. Header standard

Left: sidebar toggle, product logo (`ProductLogo` with the tenant), workspace
badge.

Right: profile menu.

Deliberately not in the header until a product has something real behind them:
search, command palette, help and notifications. Each is a slot the shell
accepts rather than a placeholder it renders — an icon that opens nothing is
worse than an absent icon. Primary navigation is never duplicated here; it is
the sidebar's job.

## 7. Sidebar standard

```
[ primary group, no heading ]
  Home
  [ a product's own landing modules ]

[ PRODUCT MODULE GROUPS — declared by the product ]

ADMINISTRATION
  Team & Access
  Settings
```

Group headings come from the registry. A group whose modules all resolve away is
not rendered — no empty headings.

**The starter ships three modules**: Home, Team & Access and Settings, in two
groups. Not a fourth, and in particular not a second "Dashboard" entry beside
Home — there is one landing route, and two entries pointing at it would be the
first invented module. The module groups between the two shipped groups are what
a product adds.

Collapsed, the sidebar shows icons with accessible names and keeps the active
indicator. The preference is stored in browser local storage and read after
mount, so the server render is stable and there is no hydration mismatch. No
database.

## 8. Navigation registry

Declared in `packages/branding/src/index.ts` alongside `product`, `brand` and
`marketing` — the file that is already the single source of what a product says
about itself.

```ts
interface ProductModule {
  id: string
  label: string
  icon: IconName          // the closed union; a name with no drawing fails to compile
  href: string            // must be a real route under apps/web/src/app
  group: string           // a group id declared in the same config
  order: number

  requiredPermissions?: ProductPermission[]
  requiredEntitlements?: string[]
  requiredCapabilities?: string[]
  requiredFeatures?: string[]

  productAdminOnly?: boolean
  ownerOnly?: boolean

  // What happens when a plan or feature gate fails. Default: hide.
  lockedBehavior?: 'hide' | 'lock'
}

interface NavigationGroup { id: string; label: string; order: number }
interface NavigationConfig { groups: NavigationGroup[]; modules: ProductModule[] }
```

An empty group label renders the group without a heading; that is how Home and
Dashboard sit above the first section title.

There is no competing metadata architecture to reconcile: nothing described the
authenticated side before.

## 9. Navigation resolution algorithm

```
visible(module) =
      productSupportsCapability(module.requiredCapabilities)
  AND userHasProductAccess
  AND satisfiesRoleGate(productAdminOnly, ownerOnly)
  AND userHasEveryPermission(module.requiredPermissions)
  AND tenantHasEveryEntitlement(module.requiredEntitlements)
  AND everyFeatureEnabled(module.requiredFeatures)
```

The clauses do **not** fail the same way, and the difference is the whole
design:

| Failing clause | Outcome | Why |
|----------------|---------|-----|
| capability | **hidden** | the code is not in this repository; there is nothing to link to |
| product access | **hidden** | the person may not use the product at all |
| role gate | **hidden** | authorization; a locked hint would leak the shape of admin |
| permission | **hidden** | authorization, same reason |
| entitlement | hidden by default, **locked** where the product asks | a commercial gate, not a security one |
| feature | the same choice | tenant configuration, not authorization |

`resolveNavigation` returns groups, each with its surviving modules in order,
each module carrying a state of available or locked. Empty groups are dropped.

**Entitlements that could not be resolved count as not entitled.** An
unreachable Control Plane therefore hides (or locks) plan-gated modules and
changes nothing else — the product keeps working. The alternative, treating
unknown as entitled, would make an outage the way to obtain a paid feature.

One registry, resolved once. There is no per-role sidebar branch anywhere, and a
test asserts the shell contains no organization-role literal.

## 10. Product capability model

Generation-time and fixed for the life of the repository. The generator writes
the selected capabilities into the product identity, from the same
`enabledCapabilities` it already renders elsewhere, so the value cannot disagree
with `.koras/project.yaml`.

A module naming a capability the product was not generated with is hidden, not
broken — which is what makes a shared registry safe to carry between products
generated with different component sets.

## 11. Feature model

Tenant configuration, from the tenant settings features column — a `jsonb`
column that existed from the first migration and had no reader until
2026-09-01. It has one now: `GET /api/v1/tenant/settings` returns the branding
and the features from the same row, `apps/web/src/lib/tenant-settings.ts` reads
it once per render, and `parseTenantFeatures` keeps the booleans and drops
everything else — a value of `"false"` or `1` is not a switch that is on, and
coercing would let `{ "beta": "no" }` enable the beta. Unknown or unreadable
means absent, which means the feature is off.

## 12. Entitlement model

Control Plane state, read over HTTP, never stored locally, never authored here.
The Control Plane resolves a plan code and a list of effective entitlements for
an organization and a product code; the product reads that pair and nothing
else.

Read in `apps/web/src/lib/entitlements.ts`, server-side only, exactly like the
signup plan catalogue: the platform's address is not the browser's business, a
failure and an empty answer look the same to the customer, and the log
distinguishes them for whoever is on call.

**Authorised by the customer's own token, and by nothing else.** The route is
`GET /api/portal/v1/products/{product_code}/entitlements` on the Control Plane's
customer surface, and it takes no organization id — the organization comes from
the token, so this product cannot ask about a customer other than the one signed
in even by mistake. What that needs is an audience rather than a credential:
sign-in asks ZITADEL to name the platform's project in the token as well, via
`KORAS_CONTROL_PLANE_PROJECT_ID` in `api/auth/start`. Unset means the plan is
simply not read, which is the unresolved case below. A product holds no machine
credential for the platform at runtime, and FOLLOW_UPS F17 records why the two
that were proposed were both worse than the route that already existed.

The wire shape is the portal API's: `plan_code`, and rows of `code`, `enabled`
and `limit_value`. `parseEntitlements` in `packages/branding` maps it, and lives
there rather than beside the fetch because that is where the product's tests
run.

```ts
interface EntitlementSet {
  resolved: boolean          // false when unread, unconfigured or failed
  plan: string | null
  features: Record<string, { enabled: boolean; limit: number | null }>
}
```

The unresolved constant is the value a product ships with, and an unconfigured
Control Plane is not an error — the same bootstrap-order rule (R-001) that makes
registration a skip rather than a failure.

## 13. Product access model

Which of an organization's users may use *this* product, and as what.

```ts
type ProductRole = 'product_admin' | 'product_member'
interface ProductAccess {
  granted: boolean
  role: ProductRole | null
  permissions: readonly ProductPermission[]
}
```

`productAccessFromOrganizationRoles(roles)` in `packages/permissions` is the one
function that produces it, and it is **the seam**. Today a product has no store
of per-product assignments — creating one would mean new tables, a new API and a
new authority the Control Plane does not know about, which
`koras-profile-product` rule 6 exists to prevent. So access derives from the
organization role the verified session already carries:

| Organization role | Product role | Rationale |
|-------------------|--------------|-----------|
| `organization_owner`, `organization_admin` | `product_admin` | the same pair `ADMIN_ROLES` already names |
| `member`, `billing_admin`, `security_admin` | `product_member` | scoped authorities are not product administration |
| none recognised | none; access is not granted | the middleware already refuses this |

When a real assignment store arrives, it replaces the body of that one function
and nothing else changes. That is the same shape `tenant-branding.ts` uses for
the branding read, and it is deliberate: one named place, with the argument for
its emptiness written next to it.

**Organization users belong to the Customer Portal.** Inviting, removing and
changing organization membership are portal operations. Team & Access in the
product answers a different question — who among those users may open *this*
product, and with which product role — and creates no identity records.

## 14. RBAC integration

`packages/permissions` keeps the closed, unranked organization role set it
already has and gains a closed permission set:

```
product.access   team.read   team.manage   settings.read   settings.manage
```

Five, because five is what the shipped routes actually check. A product adds its
own by editing that array in its own repository — one line, one file, and a typo
fails to compile because the type is derived from the array.

`ROLE_PERMISSIONS` maps each organization role to its permissions. It is a map
rather than a ladder for the reason the existing file already gives: a hierarchy
widens silently the moment a role is inserted into the middle of it.

## 15. Team & Access model

The team route under settings, requiring the team read permission.

It shows the caller's own product access, the product roles this product
defines, and where each is decided — including, plainly, that assignment is
derived from organization role until a per-product store exists. It does not
render an empty member table, and it does not offer buttons that cannot act.

That is the honest version of the page and it is worth shipping: it makes the
model visible, it is where the real table lands, and it is guarded by a real
permission so the guard is exercised from day one.

## 16. Route and API security

**Navigation hiding is not authorization**, and this design makes that
structural rather than aspirational: the registry that hides a link is the same
data that refuses the route.

| Layer | Enforcement |
|-------|-------------|
| Sidebar | `resolveNavigation` — presentation |
| Route (edge) | `apps/web/src/middleware.ts` looks the pathname up in the registry and refuses on permission, product access and the two role gates — every dimension derivable from the verified session with no I/O |
| Page (server component) | `signedInContext()` plus an explicit `can()` check, rendering `AccessDenied` |
| Server action | the same check, before any effect |
| API | `require_auth` and `require_tenant`, then the operation's own permission check |
| Data | RLS, forced, scoped by trusted context |

The middleware gate is the important addition. Entitlement and feature gates
stay out of it on purpose — they need a network read, and the middleware's
no-network property is what fixed the redirect loop the session design
documents. A page performing an entitled operation checks the entitlement
server-side itself.

Expected behaviour, end to end, for a caller lacking the team read permission:

```
sidebar                    Team & Access absent
the team settings route    403 from the middleware
API                        403
```

## 17. Customer branding architecture

Unchanged in mechanism, extended in reach.

```
Koras / product default   defaultBranding
        |
Product brand             productConfig.brand
        |
Tenant override           GET /api/v1/tenant/settings -> parseTenantBranding
        |
Resolved theme            brandingFor, brandStyle, custom properties on BrandScope
```

The read is live as of 2026-09-01 and closed F16. It takes no tenant
identifier: the API resolves the tenant from the caller's verified token and
row-level security scopes the row. `docs/PRODUCT_FRONTEND.md` records what
resolving a tenant needed first, which is the reason the route did not exist
sooner.

The shell renders inside `BrandScope`, so the header, the sidebar, the active
navigation state, primary actions and focus rings are the customer's colours
with no component knowing a tenant exists. Semantic colours are not on the
overridable list and are not made overridable by this work.

The logo is passed, not cascaded: `ProductLogo` takes the tenant, in the header
and nowhere else in the shell.

**The underlying product stays identifiable.** The header shows the customer's
logo beside the product's name. A full white-label — the customer's name in
place of the product's — happens only through the existing name override, which
is already capped and escaped.

## 18. Branding fallback model

```
logo:     tenant logo, then product logo, then the drawn mark  (never broken)
colour:   tenant token, then product token, then the default
radius:   tenant, then product, then default
name:     tenant white-label name, then product name
```

An invalid value is dropped individually; a malformed record degrades to the
product's own brand; nothing throws. This is `parseTenantBranding`'s existing
contract and the twelve tests that already assert it, now covering a much larger
surface because the shell is inside the scope.

## 19. Accessibility

Inherited from the existing foundation: the skip link, the never-removed 3px
focus ring on the brand colour, 44px minimum targets, reduced-motion handling.

Added by the shell, and asserted:

- the sidebar is a labelled navigation landmark; the drawer toggle carries
  `aria-expanded` and `aria-controls` pointing at an element rendered in **both**
  states
- Escape closes the drawer and returns focus to the toggle
- route change closes the drawer
- the current module carries `aria-current="page"`
- collapsed navigation items keep an accessible name; the label is visually
  hidden, not removed
- the profile menu is a disclosure with the same contract, not a custom listbox
- one top-level heading per page; the shell renders none, so pages keep theirs
- locked modules are non-navigating buttons carrying the reason in their
  accessible name, not disabled anchors, which are not a thing

Branding cannot break any of this: focus, active state and destructive or status
semantics are drawn from tokens the tenant may not override.

## 20. Responsive behaviour

| Width | Sidebar | Header |
|-------|---------|--------|
| large and up | persistent, expanded or collapsed | full |
| below large | drawer over the content | menu trigger, logo, profile |

Verified at 375, 390, 768, 1024 and 1440 with no horizontal scrolling, matching
the widths `docs/PRODUCT_FRONTEND.md` already records for the public pages.

## 21. Product settings architecture

```
the settings route         General         requires settings read
the team settings route    Team & Access   requires team read
```

Two areas, because two are what the starter can honour. Integrations, Security
and Developer are documented as the intended shape and shipped by the product
that has something to put in them — adding an empty Integrations page to a
product with no integrations is precisely the empty placeholder this standard
forbids.

Every settings area is a module in the registry like any other, so it is subject
to the same resolution and the same middleware gate.

General carries exactly one control, the language, and the exception is
instructive. Everything else on that page is a description of configuration
that lives in `packages/branding/src/index.ts` and is changed there, in a
reviewed commit, because a settings screen that wrote it at runtime would put
a second authority beside the one the frontend already reads from. The language
is a choice about *this person on this device*: it changes nothing for anybody
else, and the product already has to honour it from a cookie. So the form posts
to the same `POST /api/locale` the header's switcher uses, and stores nothing
anywhere else. The header carries the switcher too, beside the appearance
toggle, and hides both below `sm` where Settings has room for them.

The sidebar's labels and the locked-module reasons are translated; its ids,
routes and gates are not. `navigationFor(locale)` changes labels and nothing
else, and the middleware still reads `productConfig.navigation` directly, so a
German sidebar and the route gate describe one registry. Role and permission
identifiers on the Team & Access page stay as they are: they are code, and a
translated identifier is one nobody can search the repository for.
`docs/PRODUCT_FRONTEND.md` owns the rest of the language design.

## 22. Generator and template integration

Nothing new. The shell is ordinary template content under
`profiles/product/template/`, so:

- a new product gets it from `create-koras-app --profile product`, with no step
  a developer has to remember
- the capability list reaches the registry through `enabledCapabilities`, a
  template variable the generator already computes
- `.koras/project.yaml` needs no schema change
- the template digest moves, which is how existing projects read as behind

```
create product -> declare modules -> shell renders
               -> permissions and entitlements resolve -> branding resolves
```

## 23. Backward compatibility

- The dashboard keeps its path, its gate and its exemption list. Both public
  path lists in the middleware are untouched.
- The session cookie, its claims and both auth readers are untouched.
- The existing `packages/ui` exports are untouched; the shell is additive.
- The product configuration keeps every field; the product section gains a
  capability list and the configuration gains a navigation section.
- A product that ignores the shell entirely still builds: the old dashboard
  layout is replaced, but nothing else imports the shell.

## 24. Migration approach

For an existing product, the supported mechanism is the generator run against
the project on disk — there is no other, and manual copying is not it.

```
create-koras-app <slug> --profile product --output-dir <parent> \
    --no-interactive --check-drift --all          # what is behind
create-koras-app <slug> --profile product --output-dir <parent> \
    --no-interactive --refresh <path> ...         # bring named files forward
```

Refreshing takes explicit paths because a rendered file may carry the project's
own edits; naming it is the consent. The paths this work introduces are listed
in the implementation checklist, and none of them is a file a product is likely
to have edited except `apps/web/src/app/dashboard/layout.tsx` and
`apps/web/src/middleware.ts`, which must be reviewed in the diff before
accepting.

## 25. Testing strategy

Matching what the repository already does — structural assertions in the
generator, behavioural tests inside the generated product.

**In the starter** (`generators/create-koras-app/tests/product-shell.test.ts`):

- every registry href resolves to a real route directory under
  `apps/web/src/app`
- every registry icon is a name the icon union declares
- every registry group is a declared group id
- the shell contains no organization-role literal — no per-role sidebar
- every shell component is exported from the `packages/ui` barrel
- the middleware's registry gate exists and the public path lists are unchanged
- no permission string appears in the registry that the permission catalogue
  does not declare

**In the generated product** (runs in its own test task):

- `packages/branding/src/navigation.test.ts` — the resolver, across permission,
  entitlement, feature, capability, product-access, role-gate, ordering,
  empty-group and locked-versus-hidden cases
- `packages/permissions/src/access.test.ts` — role to product access, role to
  permissions, unknown role names granting nothing
- `packages/branding/src/branding.test.ts` — unchanged, still the branding
  parser

**The sidebar highlights one entry, not an ancestry.** The module that owns the
URL is the longest match, which is the rule `moduleForPath` already uses for the
route gate — so the entry the sidebar marks is the entry whose permissions the
middleware checked. It highlighted every ancestor until 2026-09-01 and called it
a breadcrumb; it is a breadcrumb only where the nesting is visible, and these
render as siblings in one flat list, so `/dashboard/settings/team` lit up both
*Team & Access* and *Settings*. The highlight also disagreed with
`aria-current`, which was on the exact match alone: one component saying one
thing to the eye and another to a screen reader.

**Two plan gates ship in the default registry**, one of each behaviour, so both
are visible in a running product before anyone designs one. `Reports` locks —
greyed, with a lock and a reason in its accessible name. `Insights` hides —
absent entirely. The choice between them is commercial: lock what a customer
could buy, hide what would only confuse them. Both pages refuse on their own as
well, because hiding a link is navigation and not a boundary.

**Added 2026-09-01:** `e2e/shell.spec.ts`, driven by Playwright at 375 and 1440.
It covers the claims this document makes that no text search can check — the
drawer's focus trap, Escape closing it and returning focus to the toggle, the
drawer closing on navigation, the collapsed sidebar keeping every link's
accessible name across a navigation, and a caller with no session reaching the
sign-in page rather than the shell.

The suite is authored in the product template and runs in the factory's
Generator Integration against a freshly generated project, which is FOLLOW_UPS
F18's decision: a browser test needs a running application, so it ships with the
application.

It found something on its first run, which is the argument for having it. The
shell renders the navigation **twice** — once in the sidebar and once inside the
drawer, which stays in the DOM while closed so the toggle's `aria-controls`
points at a real element. Two nodes carry `aria-current="page"` at every
viewport, and at most one is ever reachable. A DOM count says two; the
accessibility tree says one, or at 375 says none until the drawer is opened.
Only a browser can tell those apart, and this document had asserted the
single-`aria-current` rule without one.

## 26. koras-e2e-shop validation strategy

`koras-e2e-shop` is the one generated product. It is synced with the named
refresh paths above, its diff reviewed for anything beyond the shell, and then
validated locally with its own scripts — lint, typecheck, test and build, and
then by its own CI, which runs on every push and deploys to dev.

This said *local, because R-030 means its private repository has no working CI*.
That stopped being true on the evening of 2026-08-30 and the sentence outlived
it by two days. Local validation is still worth doing — it is faster than a push
and it is what catches a template defect before it reaches a product — but it is
no longer the only thing available.

What the diff must show: new shell files, the new registry, the rewritten
dashboard layout, the extended middleware, and nothing else. What it must not
show: a changed route, a changed product configuration value, a lost custom
module, or any Customer Portal or Control Plane concept.

## 27. Risks

| Risk | Mitigation |
|------|-----------|
| Navigation becomes the de facto boundary | the middleware enforces the same registry; a starter test asserts the gate is present |
| A new permission vocabulary drifts from the platform | it is product-local and never claims platform authority; five strings, all used |
| Entitlement read makes the Control Plane a hard dependency | server-side, once per render, unresolved degrades to hidden or locked |
| The template brace trap stops generation | every shell file that interpolates is a `.hbs` and contains no JSX inline style literal; the existing test enforces it |
| Tenant branding breaks contrast | the overridable list is unchanged; semantic and focus colours are not on it |
| A product edits a refreshed file and loses work | refreshing is per path, preceded by a full drift check |
| Shell code reaches the Control Plane | every file is under `profiles/product/template/`; a starter test asserts the shared layer contains none of it |

## 28. Rollback considerations

The shell is additive except for two rewritten files. Rolling back is a revert
in the starter, and in a synced product, a refresh of the two rewritten paths
from the previous starter commit. No migration runs, no infrastructure changes,
no data is written, and nothing in the Control Plane knows this work happened.

---

## Implementation checklist

### Phase A — access model

- [ ] `packages/permissions/src/index.ts` — the permission catalogue, the role
      map, the product role, product access and its derivation
- [ ] `packages/permissions/src/access.test.ts`
- [ ] `packages/permissions/package.json.hbs` — product override adding a test
      script

### Phase B — registry and resolver

- [ ] `packages/branding/src/index.ts.hbs` — navigation types, the default
      registry, the resolver, the capability list
- [ ] `packages/branding/src/navigation.test.ts`
- [ ] `packages/branding/package.json.hbs` — depend on the permissions package
- [ ] four icon names added to the union and drawn in the icon component

### Phase C — shell components

- [ ] `packages/ui/src/shell/product-shell.tsx.hbs`
- [ ] `packages/ui/src/shell/product-header.tsx.hbs`
- [ ] `packages/ui/src/shell/product-navigation.tsx.hbs`
- [ ] `packages/ui/src/shell/profile-menu.tsx` (no interpolation, so not a template)
- [ ] `packages/ui/src/shell/workspace-badge.tsx`
- [ ] `packages/ui/src/shell/access-denied.tsx`
- [ ] barrel exports in `packages/ui/src/index.ts`

### Phase D — application wiring

- [ ] `apps/web/src/lib/access.ts.hbs` — `signedInContext()`, `can()`, `roleLabel()`
- [ ] `apps/web/src/lib/entitlements.ts.hbs` — the Control Plane read, as the signed-in customer
- [ ] `apps/web/src/lib/tenant-settings.ts.hbs` — the tenant read, cached per render
- [ ] `apps/web/src/lib/tenant-features.ts.hbs` — the feature reader
- [ ] `apps/web/src/app/dashboard/layout.tsx.hbs` — render the shell
- [ ] `apps/web/src/app/dashboard/settings/page.tsx.hbs`
- [ ] `apps/web/src/app/dashboard/settings/team/page.tsx.hbs`
- [ ] `apps/web/src/middleware.ts.hbs` — registry-driven route gate

### Phase E — tests and documentation

- [ ] `generators/create-koras-app/tests/product-shell.test.ts`
- [ ] `docs/PRODUCT_FRONTEND.md` — point at this document
- [ ] `CLAUDE.md` — list both new documents
- [ ] the product profile skill — the shell rules a product agent must follow
