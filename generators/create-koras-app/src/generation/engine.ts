import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Handlebars from 'handlebars'
import type { GenerationContext } from './context.js'
import { contextToTemplateVars } from './context.js'

const STARTER_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../..')
const PROFILES_ROOT = join(STARTER_ROOT, 'profiles')

// `json` renders arrays/objects as JSON — valid HCL list syntax as well.
Handlebars.registerHelper('json', (value: unknown) => JSON.stringify(value))
Handlebars.registerHelper('eq', (a: unknown, b: unknown) => a === b)

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
  ]
}

/**
 * Copies manifest-declared shared asset directories verbatim. Contents are
 * never passed through Handlebars — Terraform's `${...}` interpolation and
 * Handlebars' `{{...}}` do not collide, but these files are shared source of
 * truth and must land byte-identical.
 */
function collectSharedAssets(ctx: GenerationContext): RenderedFile[] {
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
      results.push(...walkDirectory(rootDir, sourcePath, vars, renderTemplates))
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
