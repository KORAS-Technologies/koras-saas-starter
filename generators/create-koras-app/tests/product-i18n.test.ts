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
  it.each(['web', 'marketing'])('apps/%s sets lang and dir from the resolved locale', (app) => {
    const layout = read(PRODUCT, 'apps', app, 'src', 'app', 'layout.tsx.hbs')
    expect(layout).not.toContain('lang="en"')
    expect(layout).toContain('lang={locale}')
    expect(layout).toContain('dir={localeDirection(locale)}')
    expect(layout).toContain('currentLocale()')
  })

  it.each(['web', 'marketing'])('apps/%s resolves the locale from the cookie and the header only', (app) => {
    const resolver = read(PRODUCT, 'apps', app, 'src', 'lib', 'locale.ts.hbs')
    expect(resolver).toContain('LOCALE_COOKIE')
    expect(resolver).toContain("get('accept-language')")
    // Never the URL: a locale in a query string is a locale somebody can link.
    expect(resolver).not.toMatch(/searchParams|nextUrl|request\.url/)
    expect(resolver).toContain('productConfig.i18n.locales')
  })

  /**
   * Both applications serve the route the switcher posts to.
   *
   * `LanguageSwitcher` posts to a relative `/api/locale`. The marketing site is
   * a separate origin, so a route in `apps/web` alone would leave its switcher
   * posting to a 404 -- or, with `appUrl` set, to a cross-origin post the web
   * route refuses.
   */
  it.each(['web', 'marketing'])('apps/%s serves the locale route', (app) => {
    const route = read(PRODUCT, 'apps', app, 'src', 'app', 'api', 'locale', 'route.ts.hbs')
    expect(route).toContain('export async function POST')
    expect(route).not.toContain('export async function GET')
    expect(route).toContain('safeReturnPath(')
    expect(route).toContain('productConfig.i18n.locales.includes(')
    expect(route).toContain("sameSite: 'lax'")
    expect(route).toContain('httpOnly: true')
    // A cross-origin post is refused before anything is read from the form.
    expect(route).toContain("request.headers.get('origin')")
    expect(route).toContain('status: 403')
  })

  /**
   * Every page under `apps/web` that renders words asks which language first.
   *
   * A page that imports the design system's translated components and forgets
   * `currentLocale` compiles -- `locale` is a required prop, so it fails
   * typecheck, but only in the generated project, hours later. This is the
   * same check at the source.
   */
  it('gives every page and layout in apps/web a locale', () => {
    const pages = walk(join(PRODUCT, 'apps', 'web', 'src', 'app')).filter(
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

    const unused = [...keys].filter((key) => !used.has(key))
    expect(unused, 'keys declared that nothing renders').toEqual([])
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
  ])('%s/%s depends on packages/i18n', (kind, name) => {
    const manifest = read(PRODUCT, kind, name, 'package.json.hbs')
    expect(manifest).toContain('"@{{projectSlug}}/i18n": "workspace:*"')
    if (kind === 'apps') {
      const config = read(PRODUCT, kind, name, 'next.config.ts.hbs')
      expect(config, `${name} does not transpile the i18n package`).toContain("'@{{projectSlug}}/i18n'")
    }
  })
})
