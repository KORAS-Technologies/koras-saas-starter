import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import ts from 'typescript'
import { tmpdir } from 'node:os'
import { join, extname, relative } from 'node:path'
import { rmSync, existsSync, readFileSync, readdirSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections, validateSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'

/**
 * Every TypeScript file the generator writes actually parses.
 *
 * **The gap this closes.** A template is Handlebars, and a rendered `.tsx.hbs`
 * is only TypeScript once the engine has walked it. Every other test in this
 * directory reads the template as *text* -- `toContain`, `toMatch`, a sliced
 * block -- and text is happy to contain a well-spelled fragment of a file that
 * no parser would accept. That is not hypothetical: the product's root layout
 * was rendered as
 *
 * ```tsx
 * return (
 *   {/* a comment *\/}
 *   <html lang={locale}>
 * ```
 *
 * which is three syntax errors -- the `{...}` is read as an object literal in
 * expression position, and the element after it has no operator joining it --
 * and every string assertion about that file went on passing.
 *
 * **Why the build does not already cover this.** `generated-builds.test.ts`
 * runs a real `turbo run build` on both profiles and would fail on the layout
 * above, so this is not the only thing that could catch it. It is the only
 * thing that catches it *quickly* and *completely*:
 *
 * - it runs in about a second against 240 files, at the front of the suite,
 *   rather than after an install and two builds;
 * - it names the file, the line and the TypeScript diagnostic, where a build
 *   failure arrives as a turbo task exiting non-zero;
 * - and it sees files a build never reaches. A build parses what its entry
 *   points import. A generated extension-point stub that nothing imports yet
 *   is still a file somebody will open, and no build in the estate parses it.
 *
 * **Syntax, deliberately, and not types.** `ts.transpileModule` with
 * `reportDiagnostics` reports syntactic diagnostics and does not resolve a
 * single import, so this needs no `tsconfig`, no `node_modules` and no install.
 * Typechecking the generated project is a different claim and is already made,
 * properly, by the build test. Widening this one into a compiler pass would buy
 * a slower copy of a check that already exists.
 */

const OUT = join(tmpdir(), `koras-parse-${process.pid}-${Date.now()}`)

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

/** The extensions this parses. `.d.ts` is a `.ts` and is included. */
const TYPESCRIPT = new Set(['.ts', '.tsx'])

/** Directories that never contain generated source, only build or tool output. */
const NOT_SOURCE = new Set(['node_modules', '.next', '.git', '.venv', '.turbo', 'dist'])

function sourceFilesUnder(root: string): string[] {
  const found: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (NOT_SOURCE.has(entry.name)) continue
      const full = join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (TYPESCRIPT.has(extname(entry.name))) found.push(full)
    }
  }
  walk(root)
  return found
}

/**
 * The parse diagnostics for one file's contents, as readable lines.
 *
 * Reusable on purpose: it takes text and a filename rather than reading a
 * generated tree, so the same check covers a fixture, a file from either
 * profile, or anything else that is meant to be TypeScript. `jsx: Preserve`
 * because a `.tsx` here is Next.js source that is compiled downstream, and the
 * script kind follows the extension -- a `.ts` containing JSX is an error worth
 * reporting rather than an input worth accommodating.
 */
export function parseErrors(fileName: string, text: string): string[] {
  const rendered = ts.transpileModule(text, {
    fileName,
    reportDiagnostics: true,
    compilerOptions: { target: ts.ScriptTarget.Latest, jsx: ts.JsxEmit.Preserve },
  })
  return (rendered.diagnostics ?? []).map((diagnostic) => {
    const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')
    if (diagnostic.file && diagnostic.start !== undefined) {
      const at = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start)
      return `${fileName}:${at.line + 1}:${at.character + 1} TS${diagnostic.code}: ${message}`
    }
    return `${fileName} TS${diagnostic.code}: ${message}`
  })
}

async function generate(profile: ProfileName, slug: string): Promise<string> {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  await writeFiles(ctx, renderTemplate(ctx))
  return join(OUT, slug)
}

describe('the guard itself detects a parse error', () => {
  // First, because a checker that reports nothing reports nothing for a
  // correct file and a broken one alike. Every assertion below is a claim that
  // a list is empty, and an empty list is exactly what a checker that has
  // quietly stopped working returns.
  it('accepts the layout as it is written now', () => {
    const good = [
      'export default function RootLayout({ children }: { children: React.ReactNode }) {',
      '  return (',
      '    <html lang="en" suppressHydrationWarning>',
      '      <body>{children}</body>',
      '    </html>',
      '  )',
      '}',
    ].join('\n')
    expect(parseErrors('layout.tsx', good)).toEqual([])
  })

  it('rejects the layout as the hydration work once rendered it', () => {
    // The real defect, verbatim in shape: a JSX comment placed where the
    // returned expression belongs.
    const bad = [
      'export default function RootLayout({ children }: { children: React.ReactNode }) {',
      '  return (',
      '    {/* a comment in the wrong place */}',
      '    <html lang="en">',
      '      <body>{children}</body>',
      '    </html>',
      '  )',
      '}',
    ].join('\n')
    const errors = parseErrors('layout.tsx', bad)
    expect(errors.length).toBeGreaterThan(0)
    // A parse failure, named as one -- not a string match on the input.
    expect(errors.join('\n')).toMatch(/TS\d+:/)
    expect(errors[0]).toContain('layout.tsx:')
  })

  it('reports a truncated file rather than accepting it', () => {
    // The other way a template breaks: a block that a conditional closed in
    // one branch and not the other.
    expect(parseErrors('half.ts', 'export function open() {').length).toBeGreaterThan(0)
  })
})

for (const profile of ['product', 'control-plane'] as const) {
  describe(`every TypeScript file a generated ${profile} project contains parses`, () => {
    let files: string[]
    let root: string

    beforeAll(async () => {
      root = await generate(profile, `parse-${profile}`)
      files = sourceFilesUnder(root)
    })

    it('finds files to check', () => {
      // A walk that silently matched nothing would make the test below pass
      // over an empty list, which is the failure mode this whole file exists
      // to refuse.
      expect(files.length).toBeGreaterThan(profile === 'product' ? 100 : 20)
    })

    it('parses every one of them', () => {
      const broken: string[] = []
      for (const file of files) {
        const errors = parseErrors(relative(root, file), readFileSync(file, 'utf8'))
        if (errors.length > 0) broken.push(errors.join('\n'))
      }
      expect(broken, `${broken.length} generated file(s) do not parse`).toEqual([])
    })
  })
}
