import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

/**
 * The product frontend, asserted from the templates that produce it.
 *
 * These are structural checks, not screenshots. Each one guards a failure that
 * is silent at build time -- a generated product compiles, deploys and looks
 * broken -- which is the class of defect a build test cannot catch and a person
 * only finds by opening the page.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')
const PRODUCT = join(PROFILES, 'product', 'template')
const UI = join(PRODUCT, 'packages', 'ui', 'src')

/** Every file under a directory, recursively, as absolute paths. */
function walk(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? walk(path) : [path]
  })
}

/**
 * Read a template, with line endings normalised to LF.
 *
 * A checkout on Windows carries CRLF, so a pattern spanning two lines --
 * `

` for a blank line, say -- matches on the machine that wrote the file
 * and stops matching the moment anybody checks it out. That is not
 * hypothetical: the icon assertion below passed on the working copy that
 * created it and failed on the next checkout, reporting "no IconName union
 * found" about a union sitting in the file.
 *
 * `shared-template-parity.test.ts` learned the same lesson and says so at
 * length; this is the same rule applied at the point of reading.
 */
function read(...segments: string[]): string {
  return readFileSync(join(...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the design system is reachable', () => {
  const barrel = read(UI, 'index.ts')

  /**
   * A component nobody can import is a component that does not exist.
   *
   * Applications import from `@<slug>/ui` and never from a path inside it, so a
   * new file that is not re-exported is invisible however good it is -- and the
   * mistake leaves no trace: everything compiles, and the page that should have
   * used it simply does not.
   */
  it('exports every component module from the barrel', () => {
    const modules = walk(UI)
      .filter((path) => /\.tsx(\.hbs)?$/.test(path))
      .map((path) => path.slice(UI.length + 1).replace(/\\/g, '/').replace(/\.hbs$/, '').replace(/\.tsx$/, ''))

    for (const module of modules) {
      expect(barrel, `packages/ui/src/${module} is not exported from index.ts`).toContain(
        `'./${module}'`,
      )
    }
  })
})

describe('Handlebars and TSX coexist', () => {
  const files = walk(UI).concat(walk(join(PRODUCT, 'apps')))

  /**
   * A file that interpolates the project slug has to be a template.
   *
   * `@<slug>/branding` is written `@{{projectSlug}}/branding` in the source, and
   * the generator only renders files ending in `.hbs`. A component that imports
   * the configuration from a plain `.tsx` is copied verbatim and ships an import
   * of a package literally called `@{{projectSlug}}/branding`, which fails at
   * build time in the generated project rather than here.
   */
  it('gives every file that interpolates a variable the .hbs extension', () => {
    for (const path of files) {
      if (path.endsWith('.hbs')) continue
      const source = readFileSync(path, 'utf8')
      expect(source, `${path} interpolates a template variable but is not a .hbs`).not.toMatch(
        /\{\{\s*project(Name|Slug)\s*\}\}/,
      )
    }
  })

  /**
   * The reverse hazard, and the one that fails loudest.
   *
   * `style={{ ... }}` is ordinary JSX and is also the opening of a Handlebars
   * expression. In a `.hbs` file the generator does not render the file, it
   * refuses to parse it -- `Missing helper: ".."` -- and generation of the whole
   * project stops. Build a style object in a function instead.
   */
  it('keeps inline style object literals out of templates', () => {
    for (const path of files.filter((file) => file.endsWith('.hbs'))) {
      const source = readFileSync(path, 'utf8')
      const offending = [...source.matchAll(/\{\{[^{#/]/g)]
        .map((match) => source.slice(match.index, (match.index ?? 0) + 40))
        .filter((snippet) => !/\{\{\s*(projectName|projectSlug|primaryDomain|ports)/.test(snippet))
        // `{{else}}` is the other half of a `{{#if}}`: a capability's conditional, not an expression.
        .filter((snippet) => !snippet.startsWith('{{else}}'))
      expect(offending, `${path} contains braces Handlebars will read as an expression`).toEqual([])
    }
  })
})

describe('icons', () => {
  /**
   * The configuration names an icon; this package draws it. A name with no
   * drawing behind it renders an empty box in the middle of the feature grid,
   * and TypeScript only catches it because `PATHS` is typed as a total record --
   * which this asserts stays true.
   */
  it('draws every icon the configuration can name', () => {
    const names = /export type IconName =([\s\S]*?)\n\n/.exec(
      read(PRODUCT, 'packages', 'branding', 'src', 'index.ts.hbs'),
    )?.[1]
    expect(names, 'no IconName union found in the branding package').toBeTruthy()

    const declared = [...(names ?? '').matchAll(/'([a-z-]+)'/g)].map((match) => match[1])
    expect(declared.length).toBeGreaterThan(0)

    const icon = read(UI, 'primitives', 'icon.tsx.hbs')
    for (const name of declared) {
      expect(icon, `Icon has no path for "${name}"`).toMatch(new RegExp(`^\\s{2}${name}:`, 'm'))
    }
  })
})

describe('the default configuration', () => {
  const branding = read(PRODUCT, 'packages', 'branding', 'src', 'index.ts.hbs')

  /**
   * Every default link goes somewhere.
   *
   * "Do not render meaningless links merely because they are part of the default
   * configuration" is a rule that only holds if somebody checks. A generated
   * product's header and footer ship with in-page anchors and two account
   * routes, and each has to resolve: the anchors to a section id that the
   * marketing components actually set, the routes to a directory under
   * `apps/web/src/app`.
   */
  it('ships no link that leads nowhere', () => {
    const hrefs = [...branding.matchAll(/href: '([^']+)'/g)].map((match) => match[1])
    expect(hrefs.length).toBeGreaterThan(4)

    const sections = walk(join(UI, 'marketing'))
      .map((path) => readFileSync(path, 'utf8'))
      .join('\n')

    for (const href of hrefs) {
      if (href.startsWith('/#')) {
        const id = href.slice(2)
        expect(sections, `nothing renders id="${id}", which ${href} points at`).toContain(
          `id="${id}"`,
        )
        continue
      }
      expect(href.startsWith('/'), `${href} is not a path`).toBe(true)
      const route = join(PRODUCT, 'apps', 'web', 'src', 'app', href.slice(1))
      expect(existsSync(route), `${href} has no route at apps/web/src/app${href}`).toBe(true)
    }
  })

  /**
   * A generated product has been audited by nobody.
   *
   * The trust section is the one part of a marketing page whose default content
   * can cost somebody a contract, and a certification named there before the
   * certificate exists is a claim the product cannot support. The note in the
   * page says so; this makes sure the claim never arrives by default.
   */
  it('claims no certification it does not have', () => {
    for (const claim of ['SOC 2', 'SOC2', 'HIPAA', 'ISO 27001', 'FedRAMP', 'PCI DSS']) {
      expect(branding, `the default configuration claims ${claim}`).not.toContain(claim)
    }
    expect(branding).toContain('makes no certification claim')
  })

  /**
   * Nothing names KORAS except the platform credit.
   *
   * A generated product's page title, description and copy are its own. The one
   * deliberate exception is the footer credit, which is a toggle.
   */
  it('puts no KORAS branding in a product’s own content', () => {
    const marketing = branding.slice(branding.indexOf('export const productConfig'))
    expect(marketing).not.toMatch(/KORAS|Koras Technologies/)
  })
})

describe('the stylesheet reaches the shared components', () => {
  /**
   * Tailwind cannot see `packages/ui`.
   *
   * Automatic source detection starts at the application root and skips
   * `node_modules`, and the workspace package arrives through a symlink inside
   * it. Without an explicit `@source`, every class used by a shared component is
   * absent from the built stylesheet -- the application compiles, deploys, and
   * renders as unstyled HTML. Nothing warns.
   */
  it.each(['web', 'marketing'])('apps/%s declares packages/ui as a Tailwind source', (app) => {
    const css = read(PRODUCT, 'apps', app, 'src', 'app', 'globals.css.hbs')
    expect(css).toContain('@source "../../../../packages/ui/src"')
    expect(css).toContain('/ui/styles.css"')
  })
})

describe('the brand is configuration, not code', () => {
  /**
   * One place decides what the product is called.
   *
   * The whole point of `productConfig` is that renaming or rebranding a product
   * is one edit. A component that writes the name, a colour or a link into its
   * own source undoes that quietly -- it keeps working, and it keeps showing the
   * old value after the configuration changes.
   */
  it('names the product nowhere but the configuration', () => {
    for (const path of walk(UI)) {
      const source = readFileSync(path, 'utf8')
      expect(source, `${path} interpolates the project name directly`).not.toContain(
        '{{projectName}}',
      )
    }
  })

  /**
   * The wordmark is the exception, and it is the only one.
   *
   * `KorasWordmark` carries two fixed violets because it credits the platform
   * rather than the product, and because one violet cannot clear 4.5:1 on both
   * ink and white. Every other hex literal in a component is a colour that
   * cannot be re-branded, which is what this catches.
   */
  it('leaves brand colours to the tokens', () => {
    const offenders: string[] = []
    for (const path of walk(UI)) {
      if (path.endsWith('product-logo.tsx.hbs') || path.endsWith('tokens.css')) continue
      const source = readFileSync(path, 'utf8')
      for (const match of source.matchAll(/#[0-9a-fA-F]{6}\b/g)) offenders.push(`${path}: ${match[0]}`)
    }
    expect(offenders).toEqual([])
  })
})
