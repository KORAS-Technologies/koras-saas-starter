import { describe, it, expect } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadProfile } from '../src/profiles/index.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { templatePaths } from '../src/profiles/types.js'

/**
 * The capability combinations around `secure_files`, rendered, and checked for the two ways a
 * combination can be broken without any test of its own noticing:
 *
 *   1. a rendered Python module that imports something the combination did not generate (a file
 *      gated by a capability that is off, imported by one that is on), and
 *   2. a file listed under several capabilities in `template_map` that is generated when only
 *      some of them are on.
 *
 * Gating semantics, from `excludedSubtrees` in the generator: every path listed under a
 * component that is NOT selected is excluded. A path listed under several components is therefore
 * excluded when ANY of them is off -- it is generated only when ALL of them are on. Item 2 asserts
 * that against the real render rather than against a reading of the code.
 *
 * Item 1 is a static check (no Python is run): every `import` / `from ... import` of a
 * `koras_api` or `koras_worker` module in the rendered tree -- source and tests -- has to resolve
 * to a file in that same tree, and a name imported from it has to occur in it or be a submodule.
 */

const AXES = ['secure_files', 'storage_governance', 'data_import', 'ai'] as const
type Combo = Record<(typeof AXES)[number], boolean>

function combos(): Combo[] {
  const out: Combo[] = []
  for (let bits = 0; bits < 1 << AXES.length; bits++) {
    out.push(Object.fromEntries(AXES.map((axis, i) => [axis, (bits & (1 << i)) !== 0])) as Combo)
  }
  return out
}

function flags(combo: Combo): { with: string[]; without: string[] } {
  const enabled = AXES.filter((axis) => combo[axis])
  const disabled = AXES.filter((axis) => !combo[axis])
  const withs = [...enabled]
  // The dependencies each capability needs, named the way an operator would (the generator
  // refuses to enable one without them).
  if (combo.secure_files) withs.push('clamd', 'worker')
  if (combo.ai) withs.push('ai_gateway')
  return { with: withs, without: disabled }
}

function render(combo: Combo): Map<string, string> {
  const { manifest, defaults } = loadProfile('product')
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, flags(combo))
  validateSelections(manifest, selections)
  const slug = 'sfmatrix'
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile: 'product',
    manifest,
    defaults,
    selections,
    outputDir: join(tmpdir(), `koras-sf-matrix-${process.pid}`),
    dryRun: true,
    provision: false,
  })
  return new Map(
    renderTemplate(ctx).map((file) => [
      file.outputPath.split(String.fromCharCode(92)).join('/'),
      typeof file.content === 'string' ? file.content : file.content.toString('utf8'),
    ]),
  )
}

// ---- a static import resolver for the rendered Python -----------------------------------------

const ROOTS: Record<string, string> = {
  koras_api: 'services/api',
  koras_worker: 'services/worker',
}

function modulePathsOf(file: string): { root: string; pkg: string[] } | null {
  for (const [top, dir] of Object.entries(ROOTS)) {
    const prefix = `${dir}/${top}/`
    if (file.startsWith(prefix) && file.endsWith('.py')) {
      const parts = file.slice(dir.length + 1, -3).split('/')
      return { root: dir, pkg: parts.slice(0, -1) }
    }
  }
  return null
}

function resolve(tree: Map<string, string>, root: string, parts: string[]): string | null {
  const base = `${root}/${parts.join('/')}`
  if (tree.has(`${base}.py`)) return `${base}.py`
  if (tree.has(`${base}/__init__.py`)) return `${base}/__init__.py`
  return null
}

const FROM = /^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([\s\S]*?\)|[^\n]*)/gm
const IMPORT = /^[ \t]*import[ \t]+([^\n#]+)/gm

function importedNames(spec: string): string[] {
  return spec
    .replace(/#[^\n]*/g, '')
    .replace(/[()]/g, ' ')
    .split(',')
    .map((part) => part.trim().split(/\s+as\s+/)[0]!.trim())
    .filter((name) => name !== '' && name !== '*' && /^\w+$/.test(name))
}

function stripDocstrings(source: string): string {
  // An import written inside a docstring or a comment is prose. Triple-quoted blocks only.
  return source.replace(/("""|''')[\s\S]*?\1/g, (block) => block.replace(/[^\n]/g, ' '))
}

/** Every dangling import in the tree, as `file: statement -> why`. */
function danglingImports(tree: Map<string, string>): string[] {
  const problems: string[] = []
  for (const [file, rawSource] of tree) {
    if (!file.endsWith('.py')) continue
    const source = stripDocstrings(rawSource)
    const own = modulePathsOf(file)
    const inTests = file.startsWith('tests/')
    if (own === null && !inTests) continue

    const check = (parts: string[], root: string, names: string[], statement: string) => {
      const found = resolve(tree, root, parts)
      if (found === null) {
        problems.push(`${file}: ${statement} -> no ${parts.join('.')} in this tree`)
        return
      }
      const text = tree.get(found)!
      for (const name of names) {
        const asSubmodule = resolve(tree, root, [...parts, name]) !== null
        const inText = new RegExp(`\\b${name}\\b`).test(text)
        if (!(asSubmodule || inText)) {
          problems.push(`${file}: ${statement} -> ${name} is not in ${found}`)
        }
      }
    }

    for (const match of source.matchAll(FROM)) {
      const [statement, dots, module, spec] = match as unknown as [string, string, string, string]
      const names = importedNames(spec)
      if (dots.length > 0) {
        if (own === null) continue
        const base = own.pkg.slice(0, own.pkg.length - (dots.length - 1))
        const parts = [...base, ...(module ? module.split('.') : [])]
        check(parts, own.root, names, statement.trim().split('\n')[0]!)
      } else if (module) {
        const [top, ...rest] = module.split('.')
        const root = ROOTS[top!]
        if (root === undefined) continue
        check([top!, ...rest], root, names, statement.trim().split('\n')[0]!)
      }
    }
    for (const match of source.matchAll(IMPORT)) {
      for (const item of match[1]!.split(',')) {
        const module = item.trim().split(/\s+as\s+/)[0]!.trim()
        const [top, ...rest] = module.split('.')
        const root = ROOTS[top!]
        if (root === undefined) continue
        check([top!, ...rest], root, [], `import ${module}`)
      }
    }
  }
  return problems
}

// ---- the matrix -------------------------------------------------------------------------------

/** Which components list each path, from the manifest (exact string). */
function listings(): Map<string, string[]> {
  const { manifest } = loadProfile('product')
  const byPath = new Map<string, string[]>()
  for (const [name, entry] of Object.entries(manifest.template_map.capabilities)) {
    for (const path of templatePaths(entry)) byPath.set(path, [...(byPath.get(path) ?? []), name])
  }
  return byPath
}

const name = (combo: Combo) =>
  AXES.map((axis) => `${axis}=${combo[axis] ? 'on' : 'off'}`).join(' ')

describe('secure_files x storage_governance x data_import x ai', () => {
  const listed = listings()
  const multi = [...listed].filter(([, owners]) => owners.length > 1)

  it('has files listed under several capabilities, so the semantics below are exercised', () => {
    expect(multi.length).toBeGreaterThan(0)
    // The restore and promotion files are the ones that matter: named under two capabilities.
    const restore = listed.get('services/worker/koras_worker/tasks/restore_scan.py')
    expect(restore?.sort()).toEqual(['secure_files', 'storage_governance'])
  })

  for (const combo of combos()) {
    it(
      `renders without a dangling import or a mis-gated shared file: ${name(combo)}`,
      () => {
        const tree = render(combo)

        // 1. nothing imports a module this combination did not generate.
        expect(danglingImports(tree)).toEqual([])

        // 2. a path listed under several capabilities is generated iff ALL of them are on.
        const on = (owner: string) => (combo as Record<string, boolean>)[owner] === true
        for (const [path, owners] of multi) {
          // Only judge a path whose every owner is one of the four axes here; another owner's
          // state is the profile default, which is the same in every combination.
          if (!owners.every((owner) => (AXES as readonly string[]).includes(owner))) continue
          const expected = owners.every(on)
          const present = [...tree.keys()].some((file) => file === path || file.startsWith(`${path}/`))
          expect(present, `${path} (listed under ${owners.join(' + ')})`).toBe(expected)
        }
      },
      120_000,
    )
  }

  it('the resolver is not vacuous: it finds a module that is missing', () => {
    const tree = render({ secure_files: true, storage_governance: true, data_import: false, ai: false })
    expect(danglingImports(tree)).toEqual([])
    const broken = new Map(tree)
    broken.delete('services/api/koras_api/core/file_release.py')
    const problems = danglingImports(broken)
    expect(problems.length).toBeGreaterThan(0)
    expect(problems.join('\n')).toMatch(/file_release/)
  }, 120_000)
})
