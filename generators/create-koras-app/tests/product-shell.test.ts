import { describe, it, expect } from 'vitest'
import ts from 'typescript'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

/**
 * The authenticated product shell, asserted from the templates that produce it.
 *
 * Structural checks, in the same spirit as `product-frontend.test.ts`: each one
 * guards a failure that is silent at build time. A generated product compiles
 * and deploys with a sidebar entry that leads nowhere, an icon that renders a
 * hole, a permission nothing grants, or -- the one that matters -- a link the
 * sidebar hides and the URL still opens.
 *
 * The resolver's *behaviour* is not tested here. It ships into the generated
 * product and is tested there, in `packages/branding/src/navigation.test.ts`,
 * because that is where it runs. These are the claims that can only be checked
 * across files.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')

/**
 * Every JSX element in a template, with the attribute names it carries.
 *
 * Read from the syntax tree because the claims below are about *which element*
 * has an attribute, and text matching cannot answer that -- it answers whether
 * two strings appear near each other, which a line break, a reordered
 * attribute or a second element of the same name defeats. That weakness is not
 * hypothetical here: the assertion this replaced counted occurrences of
 * `suppressHydrationWarning` and would have been satisfied by two on `<body>`.
 *
 * `layout.tsx.hbs` parses as TSX because its Handlebars is confined to
 * comments and string bodies, so no rendering is needed to ask.
 */
interface JsxElementShape {
  tag: string
  attributes: string[]
}

function jsxElements(source: string): JsxElementShape[] {
  const file = ts.createSourceFile('layout.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const found: JsxElementShape[] = []
  const visit = (node: ts.Node): void => {
    const opening = ts.isJsxOpeningElement(node)
      ? node
      : ts.isJsxSelfClosingElement(node)
        ? node
        : undefined
    if (opening !== undefined) {
      found.push({
        tag: opening.tagName.getText(file),
        attributes: opening.attributes.properties.flatMap((property) =>
          ts.isJsxAttribute(property) ? [property.name.getText(file)] : [],
        ),
      })
    }
    ts.forEachChild(node, visit)
  }
  visit(file)
  return found
}

/** The tag names carrying `suppressHydrationWarning`, sorted and deduplicated. */
function suppressedElements(source: string): string[] {
  return [
    ...new Set(
      jsxElements(source)
        .filter((element) => element.attributes.includes('suppressHydrationWarning'))
        .map((element) => element.tag),
    ),
  ].sort()
}

const PRODUCT = join(PROFILES, 'product', 'template')
const SHARED = join(PROFILES, '_shared', 'template')
const CONTROL_PLANE = join(PROFILES, 'control-plane', 'template')
const UI = join(PRODUCT, 'packages', 'ui', 'src')
const SHELL = join(UI, 'shell')

/** Read a template with line endings normalised, for the reason the sibling
 *  file explains at length: a checkout on Windows carries CRLF, and a pattern
 *  spanning two lines stops matching the moment anybody checks the file out. */
function read(...segments: string[]): string {
  return readFileSync(join(...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function walk(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? walk(path) : [path]
  })
}

const branding = read(PRODUCT, 'packages', 'branding', 'src', 'index.ts.hbs')
const permissions = read(PRODUCT, 'packages', 'permissions', 'src', 'index.ts')

/** The block of `navigation:` inside `productConfig`, which is the only place
 *  the shipped registry is written down. */
function registry(): string {
  const start = branding.indexOf('  navigation: {')
  expect(start, 'productConfig declares no navigation').toBeGreaterThan(-1)
  return branding.slice(start)
}

/** The `groups:` half and the `modules:` half, which share an `id:` shape. */
function groupsBlock(): string {
  return registry().slice(0, registry().indexOf('    modules: ['))
}

function modulesBlock(): string {
  return registry().slice(registry().indexOf('    modules: ['))
}

function declared(name: string): string[] {
  const list = new RegExp(`export const ${name} = \\[([\\s\\S]*?)\\] as const`).exec(permissions)
  expect(list, `${name} is not declared in packages/permissions`).toBeTruthy()
  return [...(list?.[1] ?? '').matchAll(/'([a-z_.]+)'/g)].map((match) => match[1] as string)
}

describe('the shipped navigation registry', () => {
  const modules = [...modulesBlock().matchAll(/id: '([a-z-]+)'/g)].map(
    (match) => match[1] as string,
  )

  it('has modules to check', () => {
    // A regex that quietly matched nothing would make everything below pass for
    // the wrong reason -- the failure mode of every test that reads text.
    expect(modules.length).toBeGreaterThan(1)
  })

  /**
   * A sidebar entry that leads nowhere is worse than a shorter sidebar: it
   * looks like a part of the product and answers with a 404.
   *
   * The default configuration's `href` values are already resolved by
   * `product-frontend.test.ts`, which checks every `href:` in the file. This
   * says so explicitly for the navigation block, because that test's purpose is
   * the marketing links and nothing would notice if its scope narrowed.
   */
  it('points every module at a route the web application really serves', () => {
    const hrefs = [...modulesBlock().matchAll(/href: '([^']+)'/g)].map(
      (match) => match[1] as string,
    )
    expect(hrefs.length).toBe(modules.length)

    for (const href of hrefs) {
      expect(href.startsWith('/'), `${href} is not a path`).toBe(true)
      const route = join(PRODUCT, 'apps', 'web', 'src', 'app', href.slice(1))
      expect(existsSync(route), `${href} has no route at apps/web/src/app${href}`).toBe(true)
    }
  })

  /**
   * An icon with no drawing behind it renders an empty box in the sidebar.
   * TypeScript catches it only because `PATHS` is a total record of the union,
   * which is what the sibling test asserts stays true; this checks the registry
   * against the union directly, so the two cannot both be wrong quietly.
   */
  it('names only icons the union declares', () => {
    const union = /export type IconName =([\s\S]*?)\n\n/.exec(branding)?.[1] ?? ''
    const names = new Set([...union.matchAll(/'([a-z-]+)'/g)].map((match) => match[1] as string))
    expect(names.size).toBeGreaterThan(5)

    for (const match of modulesBlock().matchAll(/icon: '([a-z-]+)'/g)) {
      expect(names.has(match[1] as string), `no icon is drawn for "${match[1]}"`).toBe(true)
    }
  })

  /**
   * A module in a group nobody declared is dropped by the resolver rather than
   * crashing -- which is the right runtime behaviour and the wrong thing to
   * ship. It disappears from the sidebar with no error anywhere.
   */
  it('puts every module in a declared group', () => {
    const groups = new Set(
      [...groupsBlock().matchAll(/id: '([a-z-]+)'/g)].map((match) => match[1] as string),
    )
    expect(groups.size).toBeGreaterThan(0)

    for (const match of modulesBlock().matchAll(/group: '([a-z-]+)'/g)) {
      expect(groups.has(match[1] as string), `no group "${match[1]}" is declared`).toBe(true)
    }
  })

  /**
   * A permission nothing grants hides its module from everybody, for ever, and
   * looks exactly like a bug in the shell.
   */
  it('requires only permissions the catalogue declares', () => {
    const catalogue = new Set(declared('PRODUCT_PERMISSIONS'))
    expect(catalogue.size).toBeGreaterThan(0)

    const required = [...modulesBlock().matchAll(/requiredPermissions: \[([^\]]*)\]/g)].flatMap(
      (match) => [...(match[1] as string).matchAll(/'([a-z_.]+)'/g)].map((one) => one[1] as string),
    )
    expect(required.length).toBeGreaterThan(0)

    for (const permission of required) {
      expect(catalogue.has(permission), `nothing grants "${permission}"`).toBe(true)
    }
  })
})

describe('the permission catalogue', () => {
  /**
   * Every role must be able to open the product.
   *
   * A recognised role that lacks `product.access` is admitted by the middleware
   * -- which checks `hasAnyRole` -- and then refused by every module gate. That
   * is a signed-in account with a working session and an empty application, and
   * nothing in it says why.
   */
  it('lets every organization role open the product', () => {
    const map = /export const ROLE_PERMISSIONS[\s\S]*?\n\}/.exec(permissions)?.[0] ?? ''
    const roles = [...map.matchAll(/^ {2}([a-z_]+):/gm)].map((match) => match[1] as string)
    expect(roles.length).toBeGreaterThan(3)

    for (const role of roles) {
      const line = new RegExp(`^ {2}${role}:(.*)$`, 'm').exec(map)?.[1] ?? ''
      const grantsEverything = line.includes('PRODUCT_PERMISSIONS')
      expect(
        grantsEverything || line.includes("'product.access'"),
        `${role} cannot open the product`,
      ).toBe(true)
    }
  })
})

describe('the shell renders decisions rather than making them', () => {
  const sources = walk(SHELL).map((path) => ({ path, text: readFileSync(path, 'utf8') }))

  it('has shell components to check', () => {
    expect(sources.length).toBeGreaterThan(4)
  })

  /**
   * The failure this whole design exists to prevent, caught at its source.
   *
   * `if (role === 'admin') <AdminSidebar/>` is the shape that stops matching
   * the server's rules the first time somebody adds a role, and it fails in the
   * direction that shows people things. The shell is given a resolved
   * navigation and renders it; naming a role in here means somebody has started
   * deciding access in the browser, on a machine the caller owns.
   */
  it('names no organization or product role', () => {
    const offenders: string[] = []
    for (const { path, text } of sources) {
      for (const role of [
        'organization_owner',
        'organization_admin',
        'billing_admin',
        'security_admin',
        'product_admin',
        'product_member',
      ]) {
        if (text.includes(role)) offenders.push(`${path}: ${role}`)
      }
    }
    expect(offenders).toEqual([])
  })

  /**
   * A component nobody can import is a component that does not exist.
   * `product-frontend.test.ts` asserts this for every module in the package;
   * this names the shell's exports, so a rename that keeps the file path
   * cannot pass both.
   */
  it('exports each shell component from the barrel', () => {
    const barrel = read(UI, 'index.ts')
    for (const name of [
      'AuthenticatedProductShell',
      'ProductHeader',
      'ProductNavigation',
      'ProductProfileMenu',
      'WorkspaceBadge',
      'AccessDenied',
    ]) {
      expect(barrel, `${name} is not exported from packages/ui/src/index.ts`).toContain(name)
    }
  })

  /**
   * The profile menu is where platform management gets added by accident,
   * because every one of these words is a thing a signed-in person plausibly
   * wants. They belong to the Customer Portal, and a product that grows its own
   * has two places to change a price. One outbound link is the whole
   * integration.
   */
  it('keeps portal and platform management out of the profile menu', () => {
    const menu = read(SHELL, 'profile-menu.tsx.hbs')
    // The menu's words live in the catalogue now, so both halves of this check
    // read it: the English catalogue is what a person sees, and the menu is
    // what decides which keys reach them.
    const catalogue = read(PRODUCT, 'packages', 'i18n', 'src', 'messages', 'en.ts')
    const shellStrings = [...catalogue.matchAll(/^\s+'shell\.[a-zA-Z]+': '([^']*)'/gm)].map((m) => m[1])
    for (const forbidden of ['Billing', 'Invoices', 'Domains', 'Provisioning', 'Product catalogue']) {
      expect(menu, `the profile menu offers ${forbidden}`).not.toContain(forbidden)
      expect(shellStrings.join('\n'), `the shell catalogue offers ${forbidden}`).not.toContain(forbidden)
    }
    // The permitted one, and it leaves.
    expect(menu).toContain("t('shell.manageSubscription')")
    expect(catalogue).toContain("'shell.manageSubscription': 'Manage subscription'")
  })
})

describe('the route gate', () => {
  const middleware = read(PRODUCT, 'apps', 'web', 'src', 'middleware.ts.hbs')

  /**
   * Hiding a link is not authorization, and this is the line that makes the
   * claim true. Without it the registry becomes the boundary: typing the
   * address of a hidden module opens it.
   */
  it('refuses a route from the same registry that draws the sidebar', () => {
    expect(middleware).toContain('moduleForPath')
    expect(middleware).toContain('canOpenModule')
    expect(middleware).toContain('status: 403')
  })

  /**
   * The two lists that decide what is reachable without a session. Widening
   * either is how a gate stays present, stays tested and admits everybody --
   * `public-routes.test.ts` owns the general rule; this pins the membership.
   *
   * It used to compare the declaration against one literal string, which
   * caught a widening and nothing else: a path exempted for a route that does
   * not exist would have passed, and so would a `/privacy` exemption serving
   * nothing. Every entry is now checked to lead somewhere, so an exemption
   * cannot outlive the page it was added for.
   */
  it('exempts only paths that serve something public', () => {
    const declaration = /const PUBLIC_PATHS = \[([^\]]*)\]/.exec(middleware)?.[1] ?? ''
    const paths = [...declaration.matchAll(/'([^']+)'/g)].map((match) => match[1] as string)

    expect(paths).toEqual([
      '/login',
      '/signin',
      '/signup',
      // The welcome email's link. The owner has no password yet, so there is
      // nothing to gate it behind (Control Plane R-107).
      '/activate',
      '/api/auth',
      '/privacy',
      '/terms',
      '/faq',
      // The language switcher's target. A stranger choosing German on the
      // sign-in page must not be redirected to the sign-in page.
      '/api/locale',
    ])
    expect(middleware).toContain("const PUBLIC_EXACT_PATHS = ['/']")

    for (const path of paths) {
      // `/api/auth` is a directory of route handlers rather than a page, and
      // resolves the same way.
      const route = join(PRODUCT, 'apps', 'web', 'src', 'app', path.slice(1))
      expect(existsSync(route), `${path} is public and has no route`).toBe(true)
    }
  })

  /**
   * The middleware runs in the edge runtime, and the session design exists to
   * keep a network call out of it: verifying against a remote service on every
   * request is what put a permanent redirect loop in front of the Control
   * Plane. Entitlements and tenant features need a read, so they are checked
   * where the read already happens -- once per render, on the page.
   */
  it('makes no network call to decide a route', () => {
    const gate = middleware.slice(middleware.indexOf('const requested = moduleForPath'))
    expect(gate).not.toContain('fetch(')
    expect(gate).not.toContain('await tenant')
  })
})

describe('the shell belongs to the product profile alone', () => {
  /**
   * Structural, not a matter of care. `profiles/_shared/template` is walked by
   * both profiles, so a shell component placed there would ship into a
   * generated KORAS Control Plane -- which is out of scope for this work by
   * instruction and out of scope for the product profile by architecture.
   *
   * The control-plane template is checked too, because a copy is the other way
   * the same mistake arrives.
   */
  it('puts no shell component in the shared layer or the control plane', () => {
    for (const root of [SHARED, CONTROL_PLANE]) {
      expect(existsSync(join(root, 'packages', 'ui', 'src', 'shell'))).toBe(false)
    }
  })

  it('leaves the control plane with no product navigation registry', () => {
    const theirs = join(CONTROL_PLANE, 'packages', 'branding', 'src')
    for (const path of walk(theirs)) {
      expect(readFileSync(path, 'utf8'), `${path} declares product navigation`).not.toContain(
        'resolveNavigation',
      )
    }
  })
})

describe('the theme script and the hydration warning it necessarily causes', () => {
  /**
   * GR-250-WEB, found in a generated product.
   *
   * `THEME_SCRIPT` runs in `<head>`, before React, and writes `color-scheme`
   * onto `document.documentElement`. That is the whole point of it: the
   * appearance is correct at first paint, so a reader who chose dark never
   * sees a light flash. It also means the client's `<html>` carries a `style`
   * attribute the server never rendered, and React reports that at hydration
   * -- correctly, and every time.
   *
   * The fix is to say so in the one place it is true, rather than to stop the
   * script writing before hydration, which would reintroduce the flash.
   */
  const rootLayout = read(PRODUCT, 'apps', 'web', 'src', 'app', 'layout.tsx.hbs')

  it('still paints the chosen appearance before React runs', () => {
    // The premise. If the script stopped running ahead of hydration, the
    // suppression below would be hiding a real mismatch instead of an
    // intended one.
    const themeToggle = read(PRODUCT, 'packages', 'ui', 'src', 'shell', 'theme-toggle.tsx.hbs')
    expect(themeToggle).toContain('document.documentElement.style.colorScheme')
    expect(rootLayout).toContain('THEME_SCRIPT')
  })

  it('suppresses the warning on exactly the two elements the browser mutates', () => {
    // Read from the syntax tree rather than matched against the text. The
    // question is which *element* carries the attribute, and a regular
    // expression answers a weaker question -- whether the word appears near a
    // tag name -- which a line break or a reordered attribute defeats. This
    // file parses as TSX (its Handlebars is confined to comments and string
    // bodies), so the real answer is available cheaply.
    expect(suppressedElements(rootLayout)).toEqual(['html', 'script'])
  })

  it('puts that suppression on the nonce-bearing script', () => {
    // GR-250-WEB upstream. The nonce is the reason, so the attribute has to be
    // on the element that carries a nonce -- not on some other script added
    // later, which would leave the real mismatch reported and a different
    // element silenced.
    const script = jsxElements(rootLayout).find((element) => element.tag === 'script')
    expect(script?.attributes).toContain('nonce')
    expect(script?.attributes).toContain('suppressHydrationWarning')
  })

  it('suppresses it nowhere else', () => {
    // `suppressHydrationWarning` covers one element's own attributes and text,
    // not its descendants, so each of the two is narrow and neither reaches
    // the other. A third would be someone silencing a real mismatch with the
    // same tool.
    for (const element of jsxElements(rootLayout)) {
      if (element.tag === 'html' || element.tag === 'script') continue
      expect(element.attributes, `${element.tag} suppresses hydration`).not.toContain(
        'suppressHydrationWarning',
      )
    }
  })

  it('says why, where the next person will read it', () => {
    // An unexplained suppression is indistinguishable from one added to make
    // a warning go away, which is the thing it must never be used for.
    expect(rootLayout).toMatch(/appears twice below, on two elements, for two/)
    expect(rootLayout).toMatch(/before React/)
    expect(rootLayout).toContain('descendants')
    // The nonce half has to say *why* the browser empties it, or the next
    // reader cannot tell an expected mismatch from a silenced one.
    expect(rootLayout).toMatch(/clear the `nonce` content attribute/)
  })

  it('explains it in a comment the compiler accepts', () => {
    // Written after getting this wrong. A `{/* ... */}` block placed between
    // `return (` and `<html>` is not a JSX comment -- there is no element for
    // it to be a child of -- and it is a syntax error that every check here
    // sails past, because they all match strings against a template nothing
    // in this repository compiles. The explanation therefore goes above the
    // `return`, as an ordinary line comment.
    expect(rootLayout).toMatch(/\/\/ `suppressHydrationWarning` appears twice below/)
    expect(rootLayout).not.toMatch(/return \(\s*\{\/\*/)
  })
})

// ── R1: the production CSP guard is pointed at production servers ────────────

describe('the CSP guard reads production servers, and all of them', () => {
  /**
   * R1 asserts a *runtime* policy, which makes its value entirely dependent on
   * what the harness starts. Two things could quietly undo it and neither would
   * fail a browser run: pointing a server at `next dev`, where the policy is
   * the same today and will not be once a development allowance exists; and
   * dropping an application from `E2E_CSP_ORIGINS`, which leaves the suite
   * green with half the coverage.
   *
   * So these are asserted here rather than left to the browser, where "an
   * application nobody checked" is indistinguishable from "an application that
   * passed".
   */
  const configs = {
    product: read(PRODUCT, 'playwright.config.ts.hbs'),
    'control-plane': read(join(PROFILES, 'control-plane', 'template'), 'playwright.config.ts.hbs'),
  }

  it('starts every CSP-bearing application with next start', () => {
    for (const [profile, config] of Object.entries(configs)) {
      const commands = [...config.matchAll(/command:\s*`([^`]+)`/g)].map((match) => match[1] as string)
      expect(commands.length, `${profile}: no webServer commands`).toBeGreaterThan(0)
      for (const command of commands) {
        // `identity.mjs` and the API are not Next applications and emit no
        // policy; every Next one must be a production server.
        if (!command.includes('next ')) continue
        expect(command, `${profile}: a Next server that is not next start`).toContain('next start')
        expect(command, `${profile}: a Next server running next dev`).not.toContain('next dev')
      }
    }
  })

  it('names every application that emits a policy', () => {
    // Marketing is absent on purpose: it emits no policy, and listing it would
    // turn a real gap into a passing test.
    const origins = (profile: keyof typeof configs): string[] =>
      [...(configs[profile].match(/E2E_CSP_ORIGINS[\s\S]*?\.join/) ?? [''])[0].matchAll(/`(\w+)=/g)].map(
        (match) => match[1] as string,
      )
    expect(origins('product').sort()).toEqual(['admin', 'web'])
    expect(origins('control-plane').sort()).toEqual(['admin', 'portal'])
  })

  it('builds the applications it starts', () => {
    // A server whose `.next` does not exist exits immediately and takes the
    // whole suite with it -- so `pnpm e2e` has to build every application it
    // then starts. Generator Integration builds the whole workspace first and
    // would not have noticed; a developer's laptop would have, immediately.
    const e2eScript = (manifest: string): string =>
      (manifest.match(/"e2e":\s*"([^"]*)"/) ?? ['', ''])[1] as string

    const product = e2eScript(read(PRODUCT, 'package.json.hbs'))
    expect(product, 'product e2e script not found').toContain('turbo run build')
    expect(product, 'product e2e starts admin without building it').toContain(
      '--filter=@{{projectSlug}}/admin',
    )

    const controlPlane = e2eScript(read(join(PROFILES, 'control-plane', 'template'), 'package.json.hbs'))
    expect(controlPlane, 'control-plane e2e script not found').toContain('turbo run build')
    expect(controlPlane, 'control-plane e2e starts portal without building it').toContain(
      '--filter=@{{projectSlug}}/portal',
    )
  })
})

// ── G7R2-F01: the shell honours accessibility.highContrast ──────────────────

describe('the shell honours the high-contrast setting', () => {
  /**
   * `accessibility.highContrast` was surfaced, translated and drawn on
   * `/dashboard/preferences` and read by nothing -- the PLAT-DEF-001 class the
   * `surfaced=False` rule exists to prevent. The shell now reads it and marks
   * its root, and `tokens.css` re-skins the authenticated subtree from that
   * marker. These are protective guards: each is shown failing against a
   * deliberate mutation (M1-M6 in the test plan) before its passing run counts.
   */
  const shell = read(SHELL, 'product-shell.tsx.hbs')
  const tokens = read(UI, 'styles', 'tokens.css')

  // The override block, and the :root it must not exceed. There are no nested
  // braces in either, so the first `}` closes each.
  const hcBlock = /\[data-contrast="high"\]\s*\{([\s\S]*?)\}/.exec(tokens)?.[1] ?? ''
  const rootBlock = /:root\s*\{([^}]*)\}/.exec(tokens)?.[1] ?? ''
  const properties = (block: string): string[] =>
    [...block.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1] as string)

  it('reads accessibility.highContrast through useSettingValue and drives the marker with it', () => {
    // The read, with a `false` fallback -- the value the hook returns outside a
    // provider and when the settings API could not be reached, which is exactly
    // when no marker must appear (AC2).
    expect(shell).toContain("useSettingValue('accessibility.highContrast', false)")
    // And the value reaches the attribute rather than being read and dropped.
    // Deleting the marker (M1) leaves this failing as well as the next test,
    // which is why the plan binds M1 to both.
    expect(shell).toContain('data-contrast={highContrast ?')
  })

  it('emits data-contrast conditionally, undefined -- not "normal", not "" -- when off', () => {
    expect(shell).toContain("data-contrast={highContrast ? 'high' : undefined}")
    // The false case is the whole point of choosing an attribute over a value:
    // React omits an `undefined` attribute, so the DOM is unchanged from today
    // when the setting is off. A `'normal'` or `''` would leave a hook for a
    // second, undocumented palette state.
    expect(shell).not.toContain("data-contrast={highContrast ? 'high' : 'normal'}")
    expect(shell).not.toContain("data-contrast={highContrast ? 'high' : ''}")
    expect(shell).not.toContain('data-contrast=""')

    // On exactly one element, and that element is a div -- read from the syntax
    // tree, because "which element carries the attribute" is the question a text
    // search cannot answer. The template parses as TSX; its Handlebars is
    // confined to string bodies.
    const carriers = jsxElements(readFileSync(join(SHELL, 'product-shell.tsx.hbs'), 'utf8')).filter(
      (element) => element.attributes.includes('data-contrast'),
    )
    expect(carriers.map((element) => element.tag)).toEqual(['div'])
  })

  it('adds a [data-contrast="high"] rule to tokens.css', () => {
    expect(tokens).toContain('[data-contrast="high"]')
    expect(properties(hcBlock).length, 'the override block declares nothing').toBeGreaterThan(0)
  })

  it('redeclares only custom properties that already exist in :root', () => {
    const inRoot = new Set(properties(rootBlock))
    expect(inRoot.size).toBeGreaterThan(5)
    const overridden = properties(hcBlock)
    expect(overridden.length, 'the override block declares nothing').toBeGreaterThan(0)
    for (const property of overridden) {
      // A property invented inside the override (M4) is a value nothing else in
      // the file reads -- a dead token, and the mistake this catches.
      expect(inRoot.has(property), `${property} is not declared in :root`).toBe(true)
    }
  })

  it('writes every override as a light-dark() pair, so the theme toggle still works', () => {
    const values = [...hcBlock.matchAll(/--[\w-]+\s*:\s*([^;]+);/g)].map((match) =>
      (match[1] as string).trim(),
    )
    expect(values.length).toBeGreaterThan(0)
    for (const value of values) {
      // A flat colour (M5) would pin the appearance and break the theme toggle
      // for exactly the users who most need it.
      expect(value.startsWith('light-dark('), `${value} is not a light-dark() pair`).toBe(true)
    }
  })

  it('uses no !important and leaves the brand identity tokens alone', () => {
    // High contrast wins over a tenant brand by the cascade, not by importance
    // (M6): the marker is on a descendant of the brand's inline style, and an
    // own declaration beats an inherited value whatever its importance.
    expect(hcBlock).not.toContain('!important')
    for (const identity of ['--brand-primary', '--brand-secondary', '--brand-accent']) {
      expect(hcBlock, `high contrast must not touch ${identity}`).not.toContain(identity)
    }
  })
})
