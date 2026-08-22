import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Handlebars from 'handlebars'
import type { GenerationContext } from './context.js'
import { contextToTemplateVars } from './context.js'
import { PROJECT_MANIFEST_PATH, renderProjectManifest } from './project-manifest.js'
import { isForbiddenArtifact } from '../git.js'

const STARTER_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../..')
const PROFILES_ROOT = join(STARTER_ROOT, 'profiles')

/**
 * `json` renders arrays and objects as HCL literals.
 *
 * JSON is already valid HCL, but `terraform fmt` wants a space after each
 * separator and inside map braces. Emitting canonical spacing here means the
 * generated Terraform is fmt-clean on the first commit, instead of showing a
 * diff the first time anyone runs `terraform fmt -check`.
 */
Handlebars.registerHelper('json', (value: unknown) => {
  if (Array.isArray(value)) {
    return '[' + value.map((item) => JSON.stringify(item)).join(', ') + ']'
  }
  if (value !== null && typeof value === 'object') {
    const pairs = Object.entries(value as Record<string, unknown>).map(
      ([key, val]) => JSON.stringify(key) + ' : ' + JSON.stringify(val),
    )
    return pairs.length === 0 ? '{}' : '{ ' + pairs.join(', ') + ' }'
  }
  return JSON.stringify(value)
})
Handlebars.registerHelper('eq', (a: unknown, b: unknown) => a === b)

/**
 * `pad` right-pads a value to a fixed width.
 *
 * HCL blocks are aligned on the equals sign, and `terraform fmt` enforces it.
 * Emitting a ragged block means generated Terraform is not fmt-clean, which
 * shows up as a spurious diff the first time anyone checks.
 */
Handlebars.registerHelper('pad', (value: unknown, width: unknown) =>
  String(value).padEnd(typeof width === 'number' ? width : 0),
)

/**
 * `concat` joins its arguments into one string.
 */
Handlebars.registerHelper('concat', (...args: unknown[]) =>
  args.slice(0, -1).map(String).join(''),
)

/**
 * `gh` wraps an expression in GitHub Actions' ${{ ... }} syntax.
 *
 * A template cannot simply write those braces: Handlebars reads `${{{{` as
 * the opening of a raw block and fails to parse the file. This emits them
 * instead, so a workflow can be generated from the components a project
 * actually has rather than hardcoding a list that drifts from reality.
 */
Handlebars.registerHelper('gh', (expression: unknown) =>
  new Handlebars.SafeString('${{ ' + String(expression) + ' }}'),
)

/**
 * `basename` takes the last path segment.
 *
 * The deployment matrix is keyed by the directory an application lives in,
 * not by its component key: control-plane's `platform_admin` lives in
 * `apps/admin`, and the Vercel project, its package name and its secret are
 * all named after the directory.
 */
Handlebars.registerHelper('basename', (value: unknown) =>
  String(value).split('/').pop() ?? String(value),
)

/**
 * `upper` upper-cases a value.
 *
 * Used to build a secret name from a directory name (`apps/web` ->
 * VERCEL_WEB_PROJECT_ID) so the deployment matrix cannot name a component the
 * project does not have.
 */
Handlebars.registerHelper('upper', (value: unknown) => String(value).toUpperCase())

/**
 * Entries that appear inside a source tree but must never be copied out of
 * it. `.terraform` is the one that bites: running any Terraform command inside
 * the shared modules leaves a provider cache there, and a walk of the
 * filesystem then ships a ~50MB `terraform-provider-*.exe` into every
 * generated project. It is gitignored, so it never shows up in review.
 *
 * `.terraform.lock.hcl` is its sibling and slipped through, because skipping a
 * directory named `.terraform` does nothing about a file whose name merely
 * starts the same way. A lock file belongs to a root configuration; the shared
 * modules are not root configurations, so an init run inside one leaves a lock
 * that means nothing -- and `--refresh-modules` then copied it into a real
 * project as though it were part of the module. Generated projects write their
 * own on first init.
 */
const SKIP_ENTRIES = new Set([
  '.terraform',
  '.terraform.lock.hcl',
  '.git',
  'node_modules',
  '.turbo',
  '.next',
  'dist',
])

export interface RenderedFile {
  sourcePath: string
  outputPath: string  // relative to project root
  content: Buffer | string
  isTemplate: boolean
}

/**
 * Builds the set of template subtrees that must be skipped for this generation.
 * Everything comes from the profile manifest's `template_map` — the generator
 * itself carries no profile-specific knowledge.
 */
export function excludedSubtrees(ctx: GenerationContext): string[] {
  const { template_map: map } = ctx.manifest
  const excluded: string[] = []

  const collect = (mapping: Record<string, string>, selected: Record<string, boolean>) => {
    for (const [key, path] of Object.entries(mapping)) {
      if (selected[key] !== true) excluded.push(path)
    }
  }

  collect(map.applications, ctx.selections.applications)
  collect(map.services, ctx.selections.services)
  collect(map.capabilities, ctx.selections.capabilities)

  return excluded
}

function shouldInclude(relPath: string, excluded: string[]): boolean {
  return !excluded.some((prefix) => relPath === prefix || relPath.startsWith(`${prefix}/`))
}

export function renderTemplate(ctx: GenerationContext): RenderedFile[] {
  const templateDir = join(PROFILES_ROOT, ctx.profile, 'template')
  const vars = contextToTemplateVars(ctx)
  const excluded = excludedSubtrees(ctx)
  const all = walkDirectory(templateDir, templateDir, vars)
  return [
    ...all.filter((f) => shouldInclude(f.outputPath, excluded)),
    ...collectSharedAssets(ctx),
    projectManifestFile(ctx),
  ]
}

/**
 * The project manifest is generator-authored, not template-authored: every
 * profile gets exactly the same shape, so duplicating it into each template
 * would only create two things to keep in sync — and its values come from
 * starter/profile metadata rather than from the template context.
 *
 * It is emitted last, after the repository structure, and as an ordinary
 * RenderedFile so that it participates in `--dry-run` listing and in the atomic
 * writer without either needing to know about it.
 */
function projectManifestFile(ctx: GenerationContext): RenderedFile {
  return {
    sourcePath: '(generated)',
    outputPath: PROJECT_MANIFEST_PATH,
    content: renderProjectManifest(ctx),
    isTemplate: false,
  }
}

/**
 * Copies manifest-declared shared asset directories verbatim. Contents are
 * never passed through Handlebars — Terraform's `${...}` interpolation and
 * Handlebars' `{{...}}` do not collide, but these files are shared source of
 * truth and must land byte-identical.
 *
 * Exported because a generated project keeps a private copy of these, so a fix
 * made in the starter does not reach a project already on disk. `--provision-only`
 * plans against that stale copy without saying so; `--refresh-modules` re-copies
 * exactly this set and nothing else.
 */
export function collectSharedAssets(ctx: GenerationContext): RenderedFile[] {
  const results: RenderedFile[] = []

  for (const asset of ctx.manifest.shared_assets) {
    const sourceDir = join(STARTER_ROOT, asset.source)
    if (!existsSync(sourceDir)) {
      throw new Error(
        `Shared asset directory "${asset.source}" declared by profile ` +
          `"${ctx.profile}" does not exist at ${sourceDir}.`,
      )
    }

    for (const file of walkDirectory(sourceDir, sourceDir, {}, false)) {
      results.push({ ...file, outputPath: `${asset.target}/${file.outputPath}` })
    }
  }

  return results
}

function walkDirectory(
  rootDir: string,
  currentDir: string,
  vars: Record<string, unknown>,
  renderTemplates = true,
): RenderedFile[] {
  const results: RenderedFile[] = []
  const entries = readdirSync(currentDir)

  for (const entry of entries) {
    const sourcePath = join(currentDir, entry)
    const stat = statSync(sourcePath)

    if (stat.isDirectory()) {
      if (SKIP_ENTRIES.has(entry)) continue
      results.push(...walkDirectory(rootDir, sourcePath, vars, renderTemplates))
    } else if (isForbiddenArtifact(entry)) {
      // A plan or state file left in a source tree would otherwise be copied
      // into a fresh project, carrying every credential Terraform touched.
      continue
    } else {
      // normalize to forward slashes so paths are platform-independent
      const relPath = relative(rootDir, sourcePath).replace(/\\/g, '/')
      const isTemplate = renderTemplates && entry.endsWith('.hbs')
      const outputRelPath = isTemplate ? relPath.slice(0, -4) : relPath

      if (isTemplate) {
        const raw = readFileSync(sourcePath, 'utf8')
        const compiled = Handlebars.compile(raw)
        results.push({
          sourcePath,
          outputPath: outputRelPath,
          content: compiled(vars),
          isTemplate: true,
        })
      } else {
        results.push({
          sourcePath,
          outputPath: outputRelPath,
          content: readFileSync(sourcePath),
          isTemplate: false,
        })
      }
    }
  }

  return results
}
