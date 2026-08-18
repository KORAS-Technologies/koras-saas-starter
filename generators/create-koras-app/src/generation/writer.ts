import { mkdirSync, writeFileSync, renameSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { randomBytes } from 'node:crypto'
import type { RenderedFile } from './engine.js'
import type { GenerationContext } from './context.js'
import { PROJECT_MANIFEST_PATH } from './project-manifest.js'

export interface WriteResult {
  filesWritten: number
  fileList: string[]
}

export function writeFiles(ctx: GenerationContext, files: RenderedFile[]): WriteResult {
  const projectRoot = join(ctx.outputDir, ctx.projectSlug)
  const fileList: string[] = []

  for (const file of files) {
    const outputAbsPath = join(projectRoot, file.outputPath)
    fileList.push(file.outputPath)

    if (ctx.dryRun) continue

    // Atomic write: write to temp file then rename
    const dir = dirname(outputAbsPath)
    mkdirSync(dir, { recursive: true })

    const tmpPath = `${outputAbsPath}.${randomBytes(4).toString('hex')}.tmp`
    if (typeof file.content === 'string') {
      writeFileSync(tmpPath, file.content, 'utf8')
    } else {
      writeFileSync(tmpPath, file.content)
    }
    renameSync(tmpPath, outputAbsPath)
  }

  return { filesWritten: ctx.dryRun ? 0 : files.length, fileList }
}

function enabled(selected: Record<string, boolean>): string {
  const names = Object.entries(selected)
    .filter(([, on]) => on)
    .map(([name]) => name)
  return names.length > 0 ? names.join(', ') : '(none)'
}

export function printDryRunManifest(ctx: GenerationContext, files: RenderedFile[]): void {
  console.log('\nKORAS Generator — Dry Run')
  console.log(`Profile:  ${ctx.profile}`)
  console.log(`Project:  ${ctx.projectName}`)
  console.log(`Slug:     ${ctx.projectSlug}`)
  console.log(`Output:   ${join(ctx.outputDir, ctx.projectSlug)}`)
  console.log(`Apps:     ${enabled(ctx.selections.applications)}`)
  console.log(`Services: ${enabled(ctx.selections.services)}`)
  console.log(`Register: ${ctx.manifest.registration.registers_as_product ? 'yes' : 'no'}`)
  // Called out by name: it is the file KORAS tooling identifies the project by,
  // and one line in a list of ~180 is easy to miss.
  console.log(`Manifest: ${ctx.projectSlug}/${PROJECT_MANIFEST_PATH}\n`)
  console.log(`FILES TO CREATE (${files.length} files):`)
  // Sorted rather than shown in template-walk order: generator-authored files
  // are appended after the template tree, so walk order buries them at the
  // bottom, far from the neighbours a reader scans for. Sorting also makes the
  // listing stable regardless of how the directory walk happens to enumerate.
  for (const path of files.map((f) => f.outputPath).sort()) {
    console.log(`  ${ctx.projectSlug}/${path}`)
  }
  console.log('\nNo files were written. Remove --dry-run to proceed.')
}
