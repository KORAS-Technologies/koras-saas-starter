import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Languages in the generated product, asserted from the templates.
 *
 * `packages/i18n` proves its own catalogues and negotiation in the generated
 * project. What these guard is the wiring around it -- the part that compiles
 * whether or not anybody connected it: a layout that still says `lang="en"`,
 * a page that renders copy without asking which language, a public route the
 * switcher posts to that the session gate would redirect.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')
const PRODUCT = join(PROFILES, 'product', 'template')
const I18N = join(PRODUCT, 'packages', 'i18n', 'src')

function walk(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? walk(path) : [path]
  })
}

function read(...segments: string[]): string {
  return readFileSync(join(...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

/** Every key the English catalogue declares. */
function catalogueKeys(): string[] {
  const source = read(I18N, 'messages', 'en.ts')
  return [...source.matchAll(/^\s+'([a-zA-Z0-9.]+)':/gm)].map((match) => match[1]!)
}

describe('the product speaks the language it is asked', () => {
  /**
   * The document declares its language from the request, never from a literal.
   *
   * `lang="en"` on a page rendered in German is the one defect a translated
   * product can ship without anybody noticing: every string is right, and a
   * screen reader pronounces all of them as English.
   */
  it.each(['web', 'admin'])('apps/%s sets lang and dir from the resolved locale', (app) => {
    const layout = read(PRODUCT, 'apps', app, 'src', 'app', 'layout.tsx.hbs')
    expect(layout).not.toContain('lang="en"')
    expect(layout).toContain('lang={locale}')
    expect(layout).toContain('dir={localeDirection(locale)}')
    expect(layout).toContain('currentLocale()')
  })

  it.each(['web', 'admin'])(
    'apps/%s resolves the locale from the cookie and the header, never the URL',
    (app) => {
      const resolver = read(PRODUCT, 'apps', app, 'src', 'lib', 'locale.ts.hbs')
      expect(resolver).toContain('LOCALE_COOKIE')
      expect(resolver).toContain("get('accept-language')")
      // Never the URL: a locale in a query string is a locale somebody can link.
      expect(resolver).not.toMatch(/searchParams|nextUrl|request\.url/)
      expect(resolver).toContain('productConfig.i18n.locales')
    },
  )

  /**
   * The marketing site is the other design, on purpose: the language is in
   * the URL so every page is a static document. What has to hold is that the
   * segment is validated against the *offered* list, that an unknown one is
   * a 404 rather than a fallback, that the document still declares its
   * language from the segment, and that the per-request decision -- where the
   * bare path sends a visitor -- lives in the middleware and nowhere else.
   */
  it('apps/marketing keeps the language in the URL, validated against the offered list', () => {
    expect(existsSync(join(PRODUCT, 'apps', 'marketing', 'src', 'app', 'layout.tsx.hbs'))).toBe(false)
    expect(existsSync(join(PRODUCT, 'apps', 'marketing', 'src', 'app', 'page.tsx.hbs'))).toBe(false)

    const layout = read(PRODUCT, 'apps', 'marketing', 'src', 'app', '[locale]', 'layout.tsx.hbs')
    expect(layout).not.toContain('lang="en"')
    expect(layout).toContain('lang={locale}')
    expect(layout).toContain('dir={localeDirection(locale)}')
    expect(layout).toContain('export const dynamicParams = false')
    expect(layout).toContain('generateStaticParams')
    expect(layout).toContain('localeFromSegment(')
    expect(layout).toContain('notFound()')
    expect(layout).toContain('alternates:')
    // The layout is static: nothing in it reads the request.
    expect(layout).not.toMatch(/cookies\(\)|headers\(\)|currentLocale/)

    const page = read(PRODUCT, 'apps', 'marketing', 'src', 'app', '[locale]', 'page.tsx.hbs')
    expect(page).toContain('localeFromSegment(')
    expect(page).toContain('notFound()')
    expect(page).not.toMatch(/cookies\(\)|headers\(\)|currentLocale/)

    const plans = read(PRODUCT, 'apps', 'marketing', 'src', 'lib', 'plans.ts.hbs')
    expect(plans, 'a no-store fetch would make the page dynamic again').not.toContain("cache: 'no-store'")
    expect(plans).toContain('revalidate')

    const helpers = read(PRODUCT, 'apps', 'marketing', 'src', 'lib', 'locale.ts.hbs')
    expect(helpers).toContain('productConfig.i18n.locales')
    expect(helpers).toContain('productConfig.i18n.defaultLocale')
    expect(helpers).toContain('isLocale(')

    const middleware = read(PRODUCT, 'apps', 'marketing', 'src', 'middleware.ts.hbs')
    expect(middleware).toContain('LOCALE_COOKIE')
    expect(middleware).toContain("get('accept-language')")
    expect(middleware).toContain('preferredLocale(')
    expect(middleware).toContain('NextResponse.rewrite(')
    expect(middleware).toContain('308')
    // The locale route and static files are not the middleware's business.
    expect(middleware).toMatch(/matcher: \['\/\(\(\?!api\//)
  })

  /**
   * Signed in, the web application reads two more sources, and in one order.
   *
   * The member's stored choice outranks the cookie and the organisation's
   * default sits below it; both come from the tenant settings call the shell
   * already makes, so the page pays no request for its language. The other
   * two applications read neither: the marketing site has no session, and the
   * admin application calls the product's API for nothing.
   */
  it('apps/web reads the stored choice and the tenant default, in the documented order', () => {
    const resolver = read(PRODUCT, 'apps', 'web', 'src', 'lib', 'locale.ts.hbs')
    expect(resolver).toContain('tenantSettings()')
    expect(resolver).toContain('currentMember()')
    const stored = resolver.indexOf('stored: settings?.member_locale')
    const cookie = resolver.indexOf('cookie: store.get(LOCALE_COOKIE)')
    const tenant = resolver.indexOf('tenantDefault: settings?.locale')
    const browser = resolver.indexOf("acceptLanguage: requestHeaders.get('accept-language')")
    expect(stored).toBeGreaterThan(-1)
    expect(stored).toBeLessThan(cookie)
    expect(cookie).toBeLessThan(tenant)
    expect(tenant).toBeLessThan(browser)

    for (const app of ['marketing', 'admin']) {
      const other = read(PRODUCT, 'apps', app, 'src', 'lib', 'locale.ts.hbs')
      expect(other, `apps/${app} reads a source only a signed-in member has`).not.toMatch(
        /member_locale|tenantDefault|tenantSettings/,
      )
    }
  })

  /**
   * The pure resolver honours the sources in the same order the web
   * application feeds them, and validates every one.
   */
  it('packages/i18n ranks the stored choice, the cookie, then the tenant default', () => {
    const index = read(I18N, 'index.ts')
    expect(index).toContain(
      'for (const candidate of [input.stored, input.cookie, input.tenantDefault])',
    )
    expect(index).toContain(
      'if (isLocale(candidate) && available.includes(candidate)) return candidate',
    )
  })

  /**
   * Both applications serve the route the switcher posts to.
   *
   * `LanguageSwitcher` posts to a relative `/api/locale`. The marketing site is
   * a separate origin, so a route in `apps/web` alone would leave its switcher
   * posting to a 404 -- or, with `appUrl` set, to a cross-origin post the web
   * route refuses.
   */
  it.each(['web', 'marketing', 'admin'])('apps/%s serves the locale route', (app) => {
    const route = read(PRODUCT, 'apps', app, 'src', 'app', 'api', 'locale', 'route.ts.hbs')
    expect(route).toContain('export async function POST')
    expect(route).not.toContain('export async function GET')
    expect(route).toContain('safeReturnPath(')
    expect(route).toContain('productConfig.i18n.locales.includes(')
    // On the marketing site the language is an address, so the route sends
    // the visitor to the chosen language's copy of the page they were on.
    if (app === 'marketing') expect(route).toContain('localizedPath(requested, next)')
    expect(route).toContain("sameSite: 'lax'")
    expect(route).toContain('httpOnly: true')
    // A cross-origin post is refused before anything is read from the form.
    expect(route).toContain("request.headers.get('origin')")
    expect(route).toContain('status: 403')
  })

  /**
   * Only the web application keeps the choice with the account, and it does
   * so after the cookie and inside the validated branch -- a value that did
   * not pass the offered list is never sent to the API, and the cookie is set
   * whatever the API answers.
   */
  it('apps/web persists a signed-in choice from the locale route; the others do not', () => {
    const route = read(PRODUCT, 'apps', 'web', 'src', 'app', 'api', 'locale', 'route.ts.hbs')
    const cookie = route.indexOf('response.cookies.set(LOCALE_COOKIE')
    const persist = route.indexOf('await rememberLocale(requested)')
    expect(cookie).toBeGreaterThan(-1)
    expect(persist).toBeGreaterThan(cookie)

    const helper = read(PRODUCT, 'apps', 'web', 'src', 'lib', 'locale-preference.ts.hbs')
    expect(helper).toContain('currentMember()')
    expect(helper).toContain('updateMyLocale(')
    // Never throws: a failed write is logged, and the visitor gets the cookie.
    expect(helper).toContain('catch (error)')

    for (const app of ['marketing', 'admin']) {
      const other = read(PRODUCT, 'apps', app, 'src', 'app', 'api', 'locale', 'route.ts.hbs')
      expect(other, `apps/${app} calls the API from its locale route`).not.toContain(
        'rememberLocale',
      )
    }
  })

  /**
   * The organisation's default is a choice about other people, so it is gated
   * on `settings.manage` at the page, in the server action, and by the API.
   */
  it('gates the tenant default on settings.manage at every layer', () => {
    const page = read(PRODUCT, 'apps', 'web', 'src', 'app', 'dashboard', 'settings', 'page.tsx.hbs')
    expect(page).toContain("can(context.access, 'settings.manage')")
    expect(page).toContain('<TenantLocaleForm')
    const action = read(
      PRODUCT, 'apps', 'web', 'src', 'app', 'dashboard', 'settings', 'actions.ts.hbs',
    )
    expect(action).toContain("'use server'")
    expect(action).toContain("can(context.access, 'settings.manage')")
    expect(action).toContain('productConfig.i18n.locales.includes(')
    expect(action).toContain('updateTenantLocale(')
    const router = read(PRODUCT, 'services', 'api', 'koras_api', 'routers', 'tenant.py')
    expect(router).toContain('"settings.manage" not in permissions_for(claims.roles)')
    expect(router).toContain('@router.put("/tenant/settings/locale"')
    expect(router).toContain('@router.put("/me/locale"')
  })

  /**
   * Every page under `apps/web` that renders words asks which language first.
   *
   * A page that imports the design system's translated components and forgets
   * `currentLocale` compiles -- `locale` is a required prop, so it fails
   * typecheck, but only in the generated project, hours later. This is the
   * same check at the source.
   */
  it('gives every page and layout in apps/web and apps/admin a locale', () => {
    const pages = walk(join(PRODUCT, 'apps', 'web', 'src', 'app'))
      .concat(walk(join(PRODUCT, 'apps', 'admin', 'src', 'app')))
      .filter(
        (path) => /(page|layout|not-found)\.tsx(\.hbs)?$/.test(path) && !path.includes('signin'),
      )
    expect(pages.length).toBeGreaterThan(10)
    for (const path of pages) {
      const source = readFileSync(path, 'utf8')
      expect(source, `${path} renders without resolving the locale`).toMatch(
        /currentLocale\(\)|translator\(\)/,
      )
    }
  })

  /**
   * The admin application's refusals are sentences a person reads, and the
   * middleware is the one place they are written. Read from the catalogue,
   * in the language the cookie and the header ask for.
   */
  it('apps/admin says its refusals in the catalogue, and exempts the locale route', () => {
    const middleware = read(PRODUCT, 'apps', 'admin', 'src', 'middleware.ts.hbs')
    expect(middleware).toContain("'/api/locale'")
    expect(middleware).toContain("('admin.mfaRequired')")
    expect(middleware).toContain("('admin.forbidden')")
    expect(middleware).toContain('resolveLocale(')
    expect(middleware).not.toMatch(/new NextResponse\(\s*'[A-Z][a-z]+ [a-z]/)
  })

  /**
   * Nothing in the product's own pages says anything in English directly.
   *
   * A heuristic, and deliberately a narrow one: JSX text that starts with a
   * capital letter and runs to at least three words. Identifiers, class names
   * and code paths do not match it; a sentence somebody typed into a page
   * instead of the catalogue does. The shared components are held to the same
   * rule.
   */
  it('keeps prose out of the pages and components', () => {
    const files = walk(join(PRODUCT, 'apps', 'web', 'src'))
      .concat(walk(join(PRODUCT, 'apps', 'marketing', 'src')))
      .concat(walk(join(PRODUCT, 'apps', 'admin', 'src')))
      .concat(walk(join(PRODUCT, 'packages', 'ui', 'src')))
      .filter((path) => /\.tsx(\.hbs)?$/.test(path))
    const offenders: string[] = []
    for (const path of files) {
      const source = readFileSync(path, 'utf8')
        // Comments are where the English belongs.
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '')
        .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      for (const match of source.matchAll(/>\s*([A-Z][a-z]+(?:\s+[a-z][a-z',’-]*){2,}[^<{]*)</g)) {
        offenders.push(`${path.slice(PRODUCT.length + 1)}: "${match[1]!.trim().slice(0, 60)}"`)
      }
    }
    expect(offenders).toEqual([])
  })
})

describe('the catalogues', () => {
  it('ship English and German, and every locale the product offers has one', () => {
    const index = read(I18N, 'index.ts')
    const supported = /SUPPORTED_LOCALES = \[([^\]]*)\]/.exec(index)?.[1] ?? ''
    const locales = [...supported.matchAll(/'([a-z-]+)'/g)].map((match) => match[1]!)
    expect(locales).toContain('en')
    expect(locales).toContain('de')
    for (const locale of locales) {
      expect(existsSync(join(I18N, 'messages', `${locale}.ts`)), `no catalogue for ${locale}`).toBe(true)
    }

    const branding = read(PRODUCT, 'packages', 'branding', 'src', 'index.ts.hbs')
    const offered = /locales: \[([^\]]*)\]/.exec(branding)?.[1] ?? ''
    for (const locale of [...offered.matchAll(/'([a-z-]+)'/g)].map((match) => match[1]!)) {
      expect(locales, `the product offers "${locale}" but no catalogue exists for it`).toContain(locale)
    }
  })

  /**
   * Every key a template uses exists, and every key that exists is used.
   *
   * The first half is what `tsc` checks in the generated project; here it is
   * caught before generation. The second half `tsc` cannot check: a key nobody
   * reads is a string a translator maintains for nothing, and it is how a
   * catalogue drifts away from the interface it describes.
   */
  it('uses every key it declares, and declares every key it uses', () => {
    const keys = new Set(catalogueKeys())
    expect(keys.size).toBeGreaterThan(100)

    const sources = walk(join(PRODUCT, 'apps'))
      .concat(walk(join(PRODUCT, 'packages', 'ui', 'src')))
      .filter((path) => /\.tsx?(\.hbs)?$/.test(path))
      .map((path) => readFileSync(path, 'utf8'))
      .join('\n')

    const used = new Set(
      [...sources.matchAll(/\bt\('([a-zA-Z0-9.]+)'/g)]
        .concat([...sources.matchAll(/label: '([a-zA-Z0-9.]+\.[a-zA-Z0-9.]+)'/g)])
        .concat([...sources.matchAll(/'(appFrame\.[a-zA-Z0-9.]+)'/g)])
        .map((match) => match[1]!),
    )

    const missing = [...used].filter((key) => !keys.has(key))
    expect(missing, 'keys used by a template that no catalogue declares').toEqual([])

    // The settings catalogue is the one family of keys this scan cannot see.
    //
    // A setting's label is looked up as `t(definition.label_key)` -- the key is
    // named in `settings_catalogue/standard.py` and arrives over the API, so
    // there is no literal in any template to match. Scanning for literals is
    // the right mechanism for every other key and is blind to this one.
    //
    // Exempted here and checked better elsewhere: `product-settings.test.ts`
    // asserts that every key the catalogue names exists in all three
    // catalogues, and that every `settings.*` key here belongs to a definition
    // that is actually shown. That is a stronger statement than "some template
    // mentions it", because it is tied to the thing that renders it.
    const rendered = (key: string) =>
      key.startsWith('settings.def.') ||
      key.startsWith('settings.category.') ||
      key.startsWith('settings.option.')

    const unused = [...keys].filter((key) => !used.has(key) && !rendered(key))
    expect(unused, 'keys declared that nothing renders').toEqual([])
  })

  /**
   * The API stores only what the frontend can render.
   *
   * `SUPPORTED_LOCALES` exists twice -- once in `packages/i18n`, once in the
   * tenant router -- because the two runtimes cannot import each other. This
   * is what keeps them the same list, the way the permission catalogue is
   * kept level across the same seam.
   */
  it('keeps the API allowlist level with the catalogues', () => {
    const index = read(I18N, 'index.ts')
    const supported = /SUPPORTED_LOCALES = \[([^\]]*)\]/.exec(index)?.[1] ?? ''
    const typescript = [...supported.matchAll(/'([a-z-]+)'/g)].map((match) => match[1]!)

    const router = read(PRODUCT, 'services', 'api', 'koras_api', 'routers', 'tenant.py')
    const declared =
      /SUPPORTED_LOCALES: tuple\[str, \.\.\.\] = \(([^)]*)\)/.exec(router)?.[1] ?? ''
    const python = [...declared.matchAll(/"([a-z-]+)"/g)].map((match) => match[1]!)

    expect(python).toEqual(typescript)
    // And the schema refuses anything that is not the shape of a language tag.
    const migration = read(PRODUCT, 'supabase', 'migrations', '00017_locale_preferences.sql')
    expect(migration).toContain("locale ~ '^[a-z]{2}$'")
    expect(migration).toContain('public.current_user_id()')
  })

  /**
   * Every refusal the API can answer with has a sentence a person can read.
   *
   * `ApiErrorCode` in the API is the contract; `errors.<code>` in the
   * catalogue is what the web tier renders for it. A code added on one side
   * and not the other is exactly the gap this closes: the API would answer
   * it, the web tier would fall back to a status, and the English `message`
   * would be the only thing that said what happened. The platform's private
   * contract is exempt -- its callers are machines, never a person.
   */
  it('gives every person-facing API error code a sentence in the catalogue', () => {
    const errors = read(PRODUCT, 'services', 'api', 'koras_api', 'core', 'errors.py')
    const machineOnly = new Set([
      'environment_mismatch',
      'slug_taken',
      'tenant_not_found',
      'machine_identity_required',
      'platform_caller_required',
      'platform_caller_unconfigured',
    ])
    const codes = [...errors.matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)]
      .map((match) => match[1]!)
      .filter((code) => !machineOnly.has(code))
    expect(codes.length).toBeGreaterThan(15)

    const keys = new Set(catalogueKeys())
    const mapping = read(PRODUCT, 'apps', 'web', 'src', 'lib', 'api-errors.ts.hbs')
    for (const code of codes) {
      // Catalogue keys are camelCase; the code is snake_case on the wire.
      const key = 'errors.' + code.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())
      expect(keys, `no catalogue sentence for API error code "${code}"`).toContain(key)
      expect(mapping, `api-errors.ts does not map "${code}"`).toContain(`case '${code}':`)
    }
  })

  it('carries no Handlebars delimiter, because templates import it', () => {
    for (const file of readdirSync(join(I18N, 'messages'))) {
      expect(read(I18N, 'messages', file), `${file} contains a doubled brace`).not.toContain('{{')
    }
  })
})

describe('the packages that speak', () => {
  /**
   * Dependency direction: `i18n` is a leaf, `branding` reads it for the type,
   * `ui` reads both. The reverse edge would make the catalogue depend on the
   * copy it translates.
   */
  it('keeps packages/i18n free of every workspace dependency', () => {
    const manifest = read(PRODUCT, 'packages', 'i18n', 'package.json.hbs')
    expect(manifest).not.toContain('workspace:*')
    for (const file of walk(I18N)) {
      expect(readFileSync(file, 'utf8'), `${file} imports a workspace package`).not.toContain(
        '@{{projectSlug}}/',
      )
    }
  })

  it.each([
    ['packages', 'branding'],
    ['packages', 'ui'],
    ['apps', 'web'],
    ['apps', 'marketing'],
    ['apps', 'admin'],
  ])('%s/%s depends on packages/i18n', (kind, name) => {
    const manifest = read(PRODUCT, kind, name, 'package.json.hbs')
    expect(manifest).toContain('"@{{projectSlug}}/i18n": "workspace:*"')
    if (kind === 'apps') {
      const config = read(PRODUCT, kind, name, 'next.config.ts.hbs')
      expect(config, `${name} does not transpile the i18n package`).toContain("'@{{projectSlug}}/i18n'")
    }
  })
})
