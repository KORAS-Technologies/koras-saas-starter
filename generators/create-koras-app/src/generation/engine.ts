import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Handlebars from 'handlebars'
import type { GenerationContext } from './context.js'
import { contextToTemplateVars } from './context.js'

const PROFILES_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../../profiles')

export interface RenderedFile {
  sourcePath: string
  outputPath: string  // relative to project root
  content: Buffer | string
  isTemplate: boolean
}

export function renderTemplate(ctx: GenerationContext): RenderedFile[] {
  const templateDir = join(PROFILES_ROOT, ctx.profile, 'template')
  const vars = contextToTemplateVars(ctx)
  return walkDirectory(templateDir, templateDir, vars)
}

function walkDirectory(
  rootDir: string,
  currentDir: string,
  vars: Record<string, unknown>,
): RenderedFile[] {
  const results: RenderedFile[] = []
  const entries = readdirSync(currentDir)

  for (const entry of entries) {
    const sourcePath = join(currentDir, entry)
    const stat = statSync(sourcePath)

    if (stat.isDirectory()) {
      results.push(...walkDirectory(rootDir, sourcePath, vars))
    } else {
      // normalize to forward slashes so paths are platform-independent
      const relPath = relative(rootDir, sourcePath).replace(/\\/g, '/')
      const isTemplate = entry.endsWith('.hbs')
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
